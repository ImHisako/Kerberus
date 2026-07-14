from __future__ import annotations

import base64
import json
import os
import queue
import re
import secrets
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable


FrameReceiver = Callable[[bytes, str], bytes | None]


class SamError(RuntimeError):
    pass


def _restrict_private_file(path: Path) -> None:
    """Restrict POSIX access; Windows keeps the user-profile inherited DACL."""
    try:
        path.chmod(0o600)
    except OSError:
        if os.name != "nt":
            raise


def _write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(value)
        os.replace(temporary, path)
        _restrict_private_file(path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _hidden_startupinfo():
    if os.name != "nt":
        return None
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return startup


def _validate_destination(destination: str) -> str:
    if not isinstance(destination, str) or not re.fullmatch(r"[A-Za-z0-9=._~-]{1,4096}", destination):
        raise ValueError("Destination I2P non valida")
    return destination


def _native_helper_path() -> Path | None:
    """Find the optional Go transport bundled by the release build."""
    executable = "kerberus-native.exe" if os.name == "nt" else "kerberus-native"
    candidates = []
    override = os.environ.get("KERBERUS_NATIVE_HELPER")
    if override:
        candidates.append(Path(override))
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / executable)
    root = Path(__file__).resolve().parents[1]
    candidates.extend((root / "build" / "native" / executable, root / executable))
    return next((path for path in candidates if path.is_file()), None)


class NativeSamTransport:
    """Small JSON-lines adapter for the bundled Go SAM stream multiplexer.

    Only already-encrypted application frames cross this process boundary. The
    identity, vault password and private message keys remain in the Python client.
    """

    def __init__(
        self,
        executable: Path,
        host: str,
        port: int,
        session_id: str,
        receiver: FrameReceiver | None,
        on_exit: Callable[[], None] | None = None,
    ):
        self._receiver = receiver
        self._on_exit = on_exit
        self._closing = False
        self.frames_received = 0
        self.last_accept_error = ""
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        self._frames: queue.Queue[dict | None] = queue.Queue(maxsize=1024)
        self._process = subprocess.Popen(
            [str(executable), "--host", host, "--port", str(port), "--session", session_id],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=_hidden_startupinfo(),
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="kerberus-native-reader")
        self._frame_worker = threading.Thread(
            target=self._frame_loop,
            daemon=True,
            name="kerberus-native-frames",
        )
        self._reader.start()
        self._frame_worker.start()

    def request(
        self,
        operation: str,
        destination: str,
        payload: bytes | None = None,
        timeout: float = 6,
    ) -> dict:
        request_id = uuid.uuid4().hex
        event = threading.Event()
        result: dict = {}
        with self._pending_lock:
            self._pending[request_id] = (event, result)
        command = {"id": request_id, "op": operation, "destination": destination}
        if payload is not None:
            command["payload"] = base64.b64encode(payload).decode("ascii")
        try:
            started = time.perf_counter_ns()
            self._write(command)
            if not event.wait(timeout):
                raise TimeoutError("Timeout helper SAM nativo")
            roundtrip_ms = (time.perf_counter_ns() - started) / 1_000_000
            if not result.get("ok"):
                raise SamError(str(result.get("error") or "Errore helper SAM nativo"))
            metrics = {}
            for key, value in dict(result.get("metrics") or {}).items():
                if key.endswith("_us") and isinstance(value, (int, float)):
                    metrics[key.removesuffix("_us") + "_ms"] = round(value / 1000, 3)
                else:
                    metrics[key] = value
            metrics["python_helper_roundtrip_ms"] = round(roundtrip_ms, 3)
            go_elapsed_ms = sum(
                float(metrics.get(key, 0)) for key in ("queue_wait_ms", "handler_ms")
                if isinstance(metrics.get(key, 0), (int, float))
            )
            metrics["python_helper_ipc_overhead_ms"] = round(max(0.0, roundtrip_ms - go_elapsed_ms), 3)
            metrics["backend"] = "go-native"
            return metrics
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def probe_connect(self, destination: str, timeout: float = 80) -> dict:
        """Measure a real STREAM STATUS round-trip without changing normal sends."""
        return self.request("probe", destination, timeout=timeout)

    def _write(self, command: dict) -> None:
        process_input = self._process.stdin
        if self._process.poll() is not None or process_input is None:
            raise SamError("Helper SAM nativo non disponibile")
        encoded = json.dumps(command, separators=(",", ":")) + "\n"
        with self._write_lock:
            process_input.write(encoded)
            process_input.flush()

    def _read_loop(self) -> None:
        output = self._process.stdout
        if output is None:
            return
        try:
            for line in output:
                try:
                    message = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    continue
                if message.get("event") == "frame":
                    # Keep the stdout reader free for request responses. Protocol
                    # callbacks may synchronously send another frame.
                    self._frames.put(message)
                    continue
                if message.get("event") == "accept_error":
                    self.last_accept_error = str(message.get("error", ""))
                    continue
                request_id = message.get("id")
                with self._pending_lock:
                    pending = self._pending.get(request_id)
                if pending:
                    pending[1].update(message)
                    pending[0].set()
        finally:
            with self._pending_lock:
                pending = list(self._pending.values())
            for event, result in pending:
                result.update({"ok": False, "error": "Helper SAM nativo terminato"})
                event.set()
            if not self._closing and self._on_exit:
                self._on_exit()

    def _frame_loop(self) -> None:
        while True:
            message = self._frames.get()
            if message is None:
                return
            self._handle_frame(message)

    def _handle_frame(self, message: dict) -> None:
        if not self._receiver:
            return
        try:
            payload = base64.b64decode(message["payload"], validate=True)
            self.frames_received += 1
            response = self._receiver(payload, str(message.get("destination", "")))
            if response:
                self._write({
                    "op": "reply",
                    "stream": str(message.get("stream", "")),
                    "payload": base64.b64encode(response).decode("ascii"),
                })
        except Exception:
            return

    def close(self) -> None:
        self._closing = True
        try:
            self._frames.put_nowait(None)
        except queue.Full:
            pass
        try:
            self._write({"op": "stop"})
        except Exception:
            pass
        try:
            self._process.terminate()
        except OSError:
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
        self._native: NativeSamTransport | None = None
        self._fallback_listener: threading.Thread | None = None
        self._low_latency = False

    @property
    def low_latency(self) -> bool:
        return self._low_latency

    def configure_low_latency(self, enabled: bool, *, restart: bool = True) -> bool:
        """Select the tunnel profile and rebuild an active SAM session if needed."""
        enabled = bool(enabled)
        with self._session_lock:
            changed = enabled != self._low_latency
            self._low_latency = enabled
            active = self._control is not None
        if changed and active and restart:
            self.start_session(force=True)
            return True
        return False

    def _session_options(self) -> str:
        # Two hops are an explicit latency/anonymity trade-off documented by
        # I2P. Never permit zero-hop fallback, and retain three live tunnels plus
        # one backup so the latency profile does not reduce delivery resilience.
        tunnel_length = 2 if self._low_latency else 3
        ack_delay = 0 if self._low_latency else 25
        return (
            "i2cp.leaseSetEncType=6,4 inbound.quantity=3 outbound.quantity=3 "
            "inbound.backupQuantity=1 outbound.backupQuantity=1 "
            f"inbound.length={tunnel_length} outbound.length={tunnel_length} "
            "inbound.lengthVariance=0 outbound.lengthVariance=0 "
            "inbound.allowZeroHop=false outbound.allowZeroHop=false "
            "i2cp.reduceOnIdle=false i2cp.closeOnIdle=false i2cp.fastReceive=true "
            "i2p.streaming.profile=2 i2p.streaming.connectDelay=125 "
            f"i2p.streaming.initialAckDelay={ack_delay} "
            "i2p.streaming.inactivityAction=2 i2p.streaming.inactivityTimeout=30000"
        )

    def set_receiver(self, receiver: FrameReceiver) -> None:
        self._receiver = receiver
        if self._native is not None:
            self._native._receiver = receiver

    @property
    def native_active(self) -> bool:
        return self._native is not None and self._native._process.poll() is None

    def ensure_fallback_listener(self) -> threading.Thread | None:
        if self.native_active or self._receiver is None or self._stop.is_set():
            return None
        if self._fallback_listener is None or not self._fallback_listener.is_alive():
            self._fallback_listener = threading.Thread(
                target=self.listen,
                args=(self._receiver,),
                daemon=True,
                name="sam-python-fallback",
            )
            self._fallback_listener.start()
        return self._fallback_listener

    def _native_exited(self) -> None:
        self._native = None
        self.ensure_fallback_listener()

    def available(self, timeout: float = 0.8) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout) as sock:
                _check(_command(sock, "HELLO VERSION MIN=3.1 MAX=3.3"))
            return True
        except (OSError, SamError):
            return False

    def _connect(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=4)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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
                if self.keys_path.exists():
                    _restrict_private_file(self.keys_path)
                private_destination = self.keys_path.read_text("ascii").strip() if self.keys_path.exists() else "TRANSIENT"
                signature_option = " SIGNATURE_TYPE=7" if private_destination == "TRANSIENT" else ""
                reply = _command(
                    sock,
                    f"SESSION CREATE STYLE=STREAM ID={self.session_id} "
                    f"DESTINATION={private_destination}{signature_option} "
                    f"{self._session_options()}",
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
                helper = _native_helper_path()
                if helper:
                    try:
                        self._native = NativeSamTransport(
                            helper,
                            self.host,
                            self.port,
                            self.session_id,
                            self._receiver,
                            self._native_exited,
                        )
                    except (OSError, SamError):
                        self._native = None
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
        _write_private_text(self.keys_path, private)
        return public

    def send(self, destination: str, payload: bytes) -> dict:
        _validate_destination(destination)
        if len(payload) > 4_000_000:
            raise ValueError("Messaggio troppo grande")
        retried_stream = False
        retried_session = False
        while True:
            self.start_session()
            with self._session_lock:
                generation = self._generation
            try:
                return self._send_once(destination, payload)
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
        _validate_destination(destination)
        retried_stream = False
        retried_session = False
        while True:
            self.start_session()
            with self._session_lock:
                generation = self._generation
            try:
                if self._native is not None:
                    self._native.request("warm", destination)
                    return
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

    def _send_once(self, destination: str, payload: bytes) -> dict:
        if self._native is not None:
            try:
                return self._native.request("send", destination, payload)
            except (OSError, SamError, TimeoutError):
                self._native.close()
                self._native = None
                self.ensure_fallback_listener()
        peer_lock = self._peer_lock(destination)
        started = time.perf_counter_ns()
        with peer_lock:
            sock = self._stream_locked(destination)
            try:
                sock.sendall(len(payload).to_bytes(4, "big") + payload)
            except OSError:
                self._drop_outbound(destination, sock)
                raise
        return {
            "backend": "python-fallback",
            "python_transport_roundtrip_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
        }

    def probe_connect(self, destination: str, timeout: float = 80) -> dict:
        """Run the explicit native STREAM STATUS latency probe."""
        _validate_destination(destination)
        self.start_session()
        if self._native is None:
            raise SamError("La sonda di apertura I2P richiede l'helper Go nativo")
        return self._native.probe_connect(destination, timeout=timeout)

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
                # SILENT plus connectDelay allows the first application frame to
                # ride in the streaming SYN (0-RTT). Delivery ACKs/outbox retries
                # remain the authoritative success signal.
                sock.sendall(
                    f"STREAM CONNECT ID={self.session_id} DESTINATION={destination} SILENT=true\n".encode("ascii")
                )
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
                        args=(sock, callback, remote.split()[0]),
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

    def _read_inbound_stream(self, sock: socket.socket, callback: FrameReceiver, remote: str) -> None:
        try:
            sock.settimeout(None)
            while not self._stop.is_set():
                size = int.from_bytes(self._read_exact(sock, 4), "big")
                if size > 4_000_000:
                    raise SamError("Frame troppo grande")
                payload = self._read_exact(sock, size)
                try:
                    response = callback(payload, remote)
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
            sock.settimeout(None)
            while not self._stop.is_set():
                size = int.from_bytes(self._read_exact(sock, 4), "big")
                if size > 4_000_000:
                    raise SamError("Frame troppo grande")
                payload = self._read_exact(sock, size)
                try:
                    response = callback(payload, destination)
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
        if self._native:
            self._native.close()
            self._native = None
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
