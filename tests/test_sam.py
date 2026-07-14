import unittest
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, call, patch

from kerberus.sam import NativeSamTransport, SamClient, SamError, _write_private_text


class FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class SamTests(unittest.TestCase):
    def test_native_request_reports_python_and_go_stages_separately(self):
        transport = object.__new__(NativeSamTransport)
        transport._pending = {}
        transport._pending_lock = threading.Lock()

        def respond(command):
            event, result = transport._pending[command["id"]]
            result.update({
                "ok": True,
                "metrics": {
                    "queue_wait_us": 1250,
                    "handler_us": 1000,
                    "sam_handshake_us": 2500,
                    "i2p_stream_open_us": 3500,
                    "cold_stream": True,
                },
            })
            event.set()

        transport._write = respond
        metrics = transport.request("probe", "peer")
        self.assertEqual(metrics["queue_wait_ms"], 1.25)
        self.assertEqual(metrics["sam_handshake_ms"], 2.5)
        self.assertEqual(metrics["i2p_stream_open_ms"], 3.5)
        self.assertTrue(metrics["cold_stream"])
        self.assertGreaterEqual(metrics["python_helper_roundtrip_ms"], 0)
        self.assertGreaterEqual(metrics["python_helper_ipc_overhead_ms"], 0)
        self.assertEqual(metrics["backend"], "go-native")

    def test_persistent_destination_is_written_as_a_private_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sam-destination.txt"
            _write_private_text(path, "private-key")
            self.assertEqual(path.read_text("ascii"), "private-key")
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_persistent_session_does_not_send_transient_signature_option(self):
        from tempfile import TemporaryDirectory

        class SessionSocket:
            def settimeout(self, _value):
                pass

            def close(self):
                pass

        with TemporaryDirectory() as folder:
            keys = Path(folder) / "sam.keys"
            keys.write_text("persistent-private-key", encoding="ascii")
            client = SamClient("127.0.0.1", 7656, keys)
            commands = []

            def command(_sock, value):
                commands.append(value)
                if value.startswith("NAMING LOOKUP"):
                    return "NAMING REPLY RESULT=OK VALUE=public-destination"
                return "SESSION STATUS RESULT=OK"

            with patch.object(client, "_connect", return_value=SessionSocket()), patch(
                "kerberus.sam._command", side_effect=command
            ), patch("kerberus.sam._native_helper_path", return_value=None), patch("kerberus.sam.threading.Thread"):
                client.start_session()
            session = next(value for value in commands if value.startswith("SESSION CREATE"))
            self.assertNotIn("SIGNATURE_TYPE", session)
            self.assertIn("i2cp.leaseSetEncType=6,4", session)

    def test_each_process_client_uses_a_unique_session_id(self):
        first = SamClient("127.0.0.1", 7656, Path("one"))
        second = SamClient("127.0.0.1", 7656, Path("two"))
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertTrue(first.session_id.startswith("kerberus-"))

    def test_latency_profiles_keep_redundancy_and_never_allow_zero_hop(self):
        client = SamClient("127.0.0.1", 7656, Path("unused"))
        standard = client._session_options()
        self.assertIn("inbound.length=3 outbound.length=3", standard)
        self.assertIn("i2p.streaming.initialAckDelay=25", standard)
        self.assertIn("inbound.quantity=3 outbound.quantity=3", standard)
        self.assertIn("inbound.backupQuantity=1 outbound.backupQuantity=1", standard)
        self.assertIn("inbound.allowZeroHop=false outbound.allowZeroHop=false", standard)

        self.assertFalse(client.configure_low_latency(True, restart=False))
        low_latency = client._session_options()
        self.assertIn("inbound.length=2 outbound.length=2", low_latency)
        self.assertIn("i2p.streaming.initialAckDelay=0", low_latency)
        self.assertNotIn("length=1", low_latency)

    def test_changing_latency_profile_restarts_only_an_active_session(self):
        client = SamClient("127.0.0.1", 7656, Path("unused"))
        client.start_session = Mock(return_value="destination")
        self.assertFalse(client.configure_low_latency(True))
        client.start_session.assert_not_called()
        client._control = Mock()
        self.assertTrue(client.configure_low_latency(False))
        client.start_session.assert_called_once_with(force=True)

    def test_send_recreates_missing_session(self):
        client = SamClient("127.0.0.1", 7656, Path("unused"))
        client.start_session = Mock(return_value="destination")
        client._send_once = Mock(side_effect=[SamError("RESULT=INVALID_ID"), None])
        client.send("peer", b"payload")
        self.assertIn(call(force=True, expected_generation=0), client.start_session.call_args_list)
        self.assertEqual(client._send_once.call_count, 2)

    def test_cant_reach_peer_does_not_destroy_session(self):
        client = SamClient("127.0.0.1", 7656, Path("unused"))
        client.start_session = Mock(return_value="destination")
        client._send_once = Mock(side_effect=SamError("RESULT=CANT_REACH_PEER"))
        with self.assertRaises(SamError):
            client.send("peer", b"payload")
        self.assertEqual(client.start_session.call_args_list, [call()])

    def test_socket_reset_reopens_only_peer_stream(self):
        client = SamClient("127.0.0.1", 7656, Path("unused"))
        client.start_session = Mock(return_value="destination")
        client._drop_outbound = Mock()
        client._send_once = Mock(side_effect=[ConnectionResetError(), None])
        client.send("peer", b"payload")
        self.assertEqual(client._send_once.call_count, 2)
        self.assertFalse(any(kwargs.get("force") for _args, kwargs in client.start_session.call_args_list))

    def test_destination_command_injection_is_rejected(self):
        client = SamClient("127.0.0.1", 7656, Path("unused"))
        with self.assertRaises(ValueError):
            client.send("peer\nSTREAM ACCEPT ID=stolen", b"payload")

    @patch("kerberus.sam.select.select", return_value=([], [], []))
    @patch("kerberus.sam._command", return_value="STREAM STATUS RESULT=OK")
    def test_messages_reuse_outbound_stream(self, _command, _select):
        class Stream:
            def __init__(self):
                self.frames = []

            def settimeout(self, _value):
                pass

            def sendall(self, value):
                self.frames.append(value)

            def close(self):
                pass

        stream = Stream()
        client = SamClient("127.0.0.1", 7656, Path("unused"))
        client._connect = Mock(return_value=stream)
        client.start_session = Mock(return_value="destination")
        client._send_once("peer", b"one")
        client._send_once("peer", b"two")
        self.assertEqual(client._connect.call_count, 1)
        self.assertEqual(stream.frames[-2:], [b"\x00\x00\x00\x03one", b"\x00\x00\x00\x03two"])
        before = list(stream.frames)
        client.warm("peer")
        self.assertEqual(stream.frames, before)

    @patch("kerberus.sam._command", return_value="DEST REPLY PUB=public-key PRIV=private-key")
    @patch.object(SamClient, "_connect", return_value=FakeSocket())
    def test_destination_reply_does_not_require_result_ok(self, _connect, _command):
        with self.subTest("valid reply"):
            from tempfile import TemporaryDirectory
            from pathlib import Path

            with TemporaryDirectory() as folder:
                client = SamClient("127.0.0.1", 7656, Path(folder) / "sam.txt")
                self.assertEqual(client.generate_persistent_destination(), "public-key")
                self.assertEqual(client.keys_path.read_text("ascii"), "private-key")

    @patch("kerberus.sam._command", return_value="DEST REPLY RESULT=I2P_ERROR")
    @patch.object(SamClient, "_connect", return_value=FakeSocket())
    def test_invalid_destination_reply_is_rejected(self, _connect, _command):
        from pathlib import Path

        with self.assertRaises(SamError):
            SamClient("127.0.0.1", 7656, Path("unused")).generate_persistent_destination()


if __name__ == "__main__":
    unittest.main()
