import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from kerberus.sam import SamClient, SamError


class FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class SamTests(unittest.TestCase):
    def test_each_process_client_uses_a_unique_session_id(self):
        first = SamClient("127.0.0.1", 7656, Path("one"))
        second = SamClient("127.0.0.1", 7656, Path("two"))
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertTrue(first.session_id.startswith("kerberus-"))

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
