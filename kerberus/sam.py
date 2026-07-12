from __future__ import annotations

import socket
import secrets
import select
import threading
from pathlib import Path
from typing import Callable


FrameReceiver = Callable[[bytes], bytes | None]


class SamError(RuntimeError):
    pass


def _line(sock: socket.socket) -> str:
    data = bytearray()
    while not data.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            raise SamError("Connessione SAM chiusa")
        data.extend(chunk)
        if len(data) > 65536:
            raise SamError("Risposta SAM troppo lunga")
    return data.decode("utf-8", "replace").strip()


def _command(sock: socket.socket, command: str) -> str:
    sock.sendall(command.encode("ascii") + b"\n")
    return _line(sock)


def _check(reply: str) -> str:
    if "RESULT=OK" not in reply:
        raise SamError(reply)
    return reply


class SamClient:
    def __init__(self, host: str, port: int, keys_path: Path):
        self.host = host
        self.port = port
        self.keys_path = keys_path
        self.session_id = f"kerberus-{secrets.token_hex(6)}"
        self.destination = ""
        self._control: socket.socket | None = None
        self._accept_socket: socket.socket | None = None
        self._stop = threading.Event()
        self._session_lock = threading.RLock()
        self._accept_lock = threading.Lock()
        self._streams_lock = threading.RLock()
        self._outbound_sockets: dict[str, socket.socket] = {}
        self._peer_locks: dict[str, threading.Lock] = {}
        self._inbound_sockets: set[socket.socket] = set()
        self._generation = 0
        self._receiver: FrameReceiver | None = None

    def set_receiver(self, receiver: FrameReceiver) -> None:
        self._receiver = receiver

    def available(self, timeout: float = 0.8) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout) as sock:
                _check(_command(sock, "HELLO VERSION MIN=3.1 MAX=3.3"))
            return True
        except (OSError, SamError):
            return False

    def _connect(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=15)
        try:
            _check(_command(sock, "HELLO VERSION MIN=3.1 MAX=3.3"))
            return sock
        except Exception:
            sock.close()
            raise

    def start_session(self, force: bool = False, expected_generation: int | None = None) -> str:
        with self._session_lock:
            if expected_generation is not None and self._generation != expected_generation and self._control is not None:
                return self.destination
            if self._control is not None and not force:
                return self.destination
            self._close_session_locked()
            self.session_id = f"kerberus-{secrets.token_hex(6)}"
            sock = self._connect()
            sock.settimeout(300)
            try:
                private_destination = self.keys_path.read_text("ascii").strip() if self.keys_path.exists() else "TRANSIENT"
                reply = _command(
                    sock,
                    f"SESSION CREATE STYLE=STREAM ID={self.session_id} "
                    f"DESTINATION={private_destination} SIGNATURE_TYPE=7 "
                    "i2cp.leaseSetEncType=6,4 inbound.quantity=3 outbound.quantity=3 "
                    "inbound.backupQuantity=1 outbound.backupQuantity=1 "
                    "i2cp.reduceOnIdle=false i2cp.closeOnIdle=false i2cp.fastReceive=true "
                    "i2p.streaming.profile=2 i2p.streaming.initialAckDelay=25",
                )
                _check(reply)
                lookup = _check(_command(sock, "NAMING LOOKUP NAME=ME"))
                values = dict(part.split("=", 1) for part in lookup.split() if "=" in part)
                destination = values.get("VALUE", "")
                if not destination:
                    raise SamError("SAM non ha restituito la destination della sessione")
                self.destination = destination
                sock.settimeout(None)
                self._control = sock
                self._generation += 1
                generation = self._generation
                threading.Thread(
                    target=self._monitor_control,
                    args=(sock, generation),
                    daemon=True,
                    name=f"sam-control-{generation}",
                ).start()
                return self.destination
            except Exception:
                sock.close()
                raise

    def generate_persistent_destination(self) -> str:
        with self._connect() as sock:
            reply = _command(sock, "DEST GENERATE SIGNATURE_TYPE=7")
        values = dict(part.split("=", 1) for part in reply.split() if "=" in part)
        if not reply.startswith("DEST REPLY") or "PUB" not in values or "PRIV" not in values:
            raise SamError(reply)
        private = values["PRIV"]
        public = values["PUB"]
        self.keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.keys_path.write_text(private, encoding="ascii")
        return public

    def send(self, destination: str, payload: bytes) -> None:
        if len(payload) > 4_000_000:
            raise ValueError("Messaggio troppo grande")
        retried_stream = False
        retried_session = False
        while True:
            self.start_session()
            with self._session_lock:
                generation = self._generation
            try:
                self._send_once(destination, payload)
                return
            except SamError as exc:
                message = str(exc)
                if "INVALID_ID" in message and not retried_session:
                    self.start_session(force=True, expected_generation=generation)
                    retried_session = True
                    retried_stream = False
                    continue
                raise
            except OSError:
                self._drop_outbound(destination)
                if not retried_stream:
                    retried_stream = True
                    continue
                raise

    def warm(self, destination: str) -> None:
        """Open and retain a peer stream without emitting an application frame."""
        retried_stream = False
        retried_session = False
        while True:
            self.start_session()
            with self._session_lock:
                generation = self._generation
            try:
                with self._peer_lock(destination):
                    self._stream_locked(destination)
                return
            except SamError as exc:
                if "INVALID_ID" in str(exc) and not retried_session:
                    self.start_session(force=True, expected_generation=generation)
                    retried_session = True
                    retried_stream = False
                    continue
                raise
            except OSError:
                self._drop_outbound(destination)
                if not retried_stream:
                    retried_stream = True
                    continue
                raise

    def _send_once(self, destination: str, payload: bytes) -> None:
        peer_lock = self._peer_lock(destination)
        with peer_lock:
            sock = self._stream_locked(destination)
            try:
                sock.sendall(len(payload).to_bytes(4, "big") + payload)
            except OSError:
                self._drop_outbound(destination, sock)
                raise

    def _stream_locked(self, destination: str) -> socket.socket:
        with self._streams_lock:
            sock = self._outbound_sockets.get(destination)
        if sock is not None and self._socket_closed(sock):
            self._drop_outbound(destination, sock)
            sock = None
        if sock is None:
            sock = self._connect()
            try:
                sock.settimeout(120)
                _check(_command(
                    sock,
                    f"STREAM CONNECT ID={self.session_id} DESTINATION={destination} SILENT=false",
                ))
                sock.settimeout(None)
            except Exception:
                sock.close()
                raise
            with self._streams_lock:
                self._outbound_sockets[destination] = sock
            if self._receiver:
                threading.Thread(
                    target=self._read_outbound_stream,
                    args=(destination, sock, self._receiver),
                    daemon=True,
                    name="sam-outbound-reader",
                ).start()
        return sock

    def listen(self, callback: FrameReceiver) -> None:
        self._receiver = callback
        self._stop.clear()
        while not self._stop.is_set():
            try:
                self.start_session()
                sock = self._connect()
                handed_off = False
                try:
                    sock.settimeout(30)
                    _check(_command(sock, f"STREAM ACCEPT ID={self.session_id} SILENT=false"))
                    sock.settimeout(None)
                    with self._accept_lock:
                        self._accept_socket = sock
                    remote = _line(sock)
                    if remote.startswith("STREAM STATUS"):
                        raise SamError(remote)
                    with self._streams_lock:
                        self._inbound_sockets.add(sock)
                    handed_off = True
                    threading.Thread(
                        target=self._read_inbound_stream,
                        args=(sock, callback),
                        daemon=True,
                        name="sam-inbound",
                    ).start()
                finally:
                    if not handed_off:
                        sock.close()
                    with self._accept_lock:
                        if self._accept_socket is sock:
                            self._accept_socket = None
            except SamError as exc:
                if "INVALID_ID" in str(exc):
                    try:
                        with self._session_lock:
                            generation = self._generation
                        self.start_session(force=True, expected_generation=generation)
                    except (OSError, SamError):
                        pass
                self._stop.wait(1.5)
            except socket.timeout:
                self._stop.wait(0.2)
            except OSError:
                if self._stop.is_set():
                    break
                try:
                    self.start_session()
                except (OSError, SamError):
                    pass
                self._stop.wait(1.5)

    def _read_inbound_stream(self, sock: socket.socket, callback: FrameReceiver) -> None:
        try:
            sock.settimeout(180)
            while not self._stop.is_set():
                size = int.from_bytes(self._read_exact(sock, 4), "big")
                if size > 4_000_000:
                    raise SamError("Frame troppo grande")
                payload = self._read_exact(sock, size)
                try:
                    response = callback(payload)
                    if response:
                        if len(response) > 4_000_000:
                            raise SamError("Risposta troppo grande")
                        sock.sendall(len(response).to_bytes(4, "big") + response)
                except Exception:
                    continue
        except (OSError, SamError, socket.timeout):
            pass
        finally:
            with self._streams_lock:
                self._inbound_sockets.discard(sock)
            sock.close()

    def _read_outbound_stream(self, destination: str, sock: socket.socket, callback: FrameReceiver) -> None:
        try:
            sock.settimeout(180)
            while not self._stop.is_set():
                size = int.from_bytes(self._read_exact(sock, 4), "big")
                if size > 4_000_000:
                    raise SamError("Frame troppo grande")
                payload = self._read_exact(sock, size)
                try:
                    response = callback(payload)
                    if response:
                        sock.sendall(len(response).to_bytes(4, "big") + response)
                except Exception:
                    continue
        except (OSError, SamError, socket.timeout):
            pass
        finally:
            self._drop_outbound(destination, sock)

    def _monitor_control(self, sock: socket.socket, generation: int) -> None:
        try:
            while not self._stop.is_set():
                line = _line(sock)
                if line.startswith("PING"):
                    sock.sendall(("PONG" + line[4:] + "\n").encode("utf-8"))
                elif "RESULT=OK" not in line:
                    raise SamError(line)
        except (OSError, SamError):
            pass
        finally:
            with self._session_lock:
                if self._control is sock and self._generation == generation:
                    self._control = None
                    self._close_data_sockets()

    def _peer_lock(self, destination: str) -> threading.Lock:
        with self._streams_lock:
            return self._peer_locks.setdefault(destination, threading.Lock())

    @staticmethod
    def _socket_closed(sock: socket.socket) -> bool:
        try:
            readable, _, _ = select.select([sock], [], [], 0)
            return bool(readable) and not sock.recv(1, socket.MSG_PEEK)
        except OSError:
            return True

    def _drop_outbound(self, destination: str, expected: socket.socket | None = None) -> None:
        with self._streams_lock:
            current = self._outbound_sockets.get(destination)
            if current is None or (expected is not None and current is not expected):
                return
            self._outbound_sockets.pop(destination, None)
        current.close()

    @staticmethod
    def _read_exact(sock: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise SamError("Frame incompleto")
            data.extend(chunk)
        return bytes(data)

    def stop(self) -> None:
        self._stop.set()
        with self._accept_lock:
            if self._accept_socket:
                self._accept_socket.close()
                self._accept_socket = None
        with self._session_lock:
            self._close_session_locked()

    def _close_control(self) -> None:
        if self._control:
            self._control.close()
            self._control = None

    def _close_session_locked(self) -> None:
        self._close_control()
        self._close_data_sockets()

    def _close_data_sockets(self) -> None:
        with self._accept_lock:
            if self._accept_socket:
                self._accept_socket.close()
                self._accept_socket = None
        with self._streams_lock:
            sockets = list(self._outbound_sockets.values()) + list(self._inbound_sockets)
            self._outbound_sockets.clear()
            self._inbound_sockets.clear()
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass
