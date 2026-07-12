import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from kerberus.config import AppConfig
from kerberus.crypto import destination_b32, generate_identity, pq_available, seal_message, update_destination
from kerberus.service import MessengerService


@unittest.skipUnless(pq_available(), "pqcrypto non installato")
class ServiceTests(unittest.TestCase):
    @staticmethod
    def _wait_for(predicate, timeout=3):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    def test_replayed_message_is_stored_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = MessengerService(AppConfig(vault_path=root / "vault.kbv", sam_keys_path=root / "sam.txt"))
            service.vault.create("password-lunga-di-test")
            bob = service.create_identity("Bob")
            alice, alice_secrets = generate_identity("Alice", "alice-destination")
            service.vault.state["contacts"][alice.identity_id] = alice.to_dict()
            service.vault.save()
            service.sam = type("Endpoint", (), {"send": lambda *_args: None, "stop": lambda *_args: None})()
            envelope = seal_message(alice, alice_secrets, bob, "una sola volta")
            raw = json.dumps(envelope).encode("utf-8")
            service._receive(raw)
            service._receive(raw)
            self.assertEqual(len(service.messages_for(alice.identity_id)), 1)
            stored = service.messages_for(alice.identity_id)[0]
            self.assertIsInstance(stored["sent_at"], int)
            self.assertIsInstance(stored["received_at"], int)
            service.close(wait=True)

    def test_signed_ack_can_return_on_same_full_duplex_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            alice = alice_service.identity()
            bob = bob_service.identity()
            alice_service.vault.state["contacts"][bob.identity_id] = bob.to_dict()
            bob_service.vault.state["contacts"][alice.identity_id] = alice.to_dict()
            alice_service.vault.save()
            bob_service.vault.save()

            captured = []

            class Endpoint:
                def send(self, _destination, payload):
                    captured.append(payload)

                def stop(self):
                    pass

            alice_service.sam = Endpoint()
            alice_service.send_message(bob.identity_id, "ACK inline")
            reply = bob_service._receive(captured[0], inline_reply=True)
            self.assertIsNotNone(reply)
            self.assertEqual(bob_service.vault.state["control_outbox"], [])
            alice_service._receive(reply)
            delivered = alice_service.messages_for(bob.identity_id)[0]
            self.assertEqual(delivered["status"], "delivered")
            self.assertIsInstance(delivered["recipient_received_at"], int)
            self.assertIsInstance(delivered["delivered_at"], int)

            alice_service.send_message(bob.identity_id, "Timing alterato")
            tampered_reply = bob_service._receive(captured[1], inline_reply=True)
            tampered = json.loads(tampered_reply)
            tampered["received_at"] += 10_000
            alice_service._receive(json.dumps(tampered).encode("utf-8"))
            second = alice_service.messages_for(bob.identity_id)[1]
            self.assertEqual(second["status"], "delivered")
            self.assertIsNone(second["recipient_received_at"])
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_code_request_creates_both_chats_and_delivers_first_message(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            routes = {}
            for service in (alice_service, bob_service):
                identity = service.identity()
                routes[identity.destination] = service
                routes[destination_b32(identity.destination)] = service

            class Endpoint:
                def send(self, destination, payload):
                    routes[destination]._receive(payload)

                def stop(self):
                    pass

            alice_service.sam = Endpoint()
            bob_service.sam = Endpoint()
            bob = bob_service.identity()
            alice = alice_service.identity()
            one_time_code = bob_service.contact_code()
            alice_service.request_contact(one_time_code, "Ciao Bob")
            self.assertTrue(self._wait_for(lambda: bob.identity_id in alice_service.vault.state["contacts"]))
            self.assertIn(bob.identity_id, alice_service.vault.state["contacts"])
            self.assertIn(alice.identity_id, bob_service.vault.state["contacts"])
            self.assertEqual(bob_service.messages_for(alice.identity_id)[0]["text"], "Ciao Bob")
            avatar = base64.urlsafe_b64encode(b"\x89PNG\r\n\x1a\nprofile").decode("ascii").rstrip("=")
            alice_service.update_profile("Alice Nova", avatar)
            updated = bob_service.vault.state["contacts"][alice.identity_id]
            self.assertEqual(updated["name"], "Alice Nova")
            self.assertEqual(updated["avatar_data"], avatar)
            before = len(alice_service.vault.state["contacts"])
            alice_service.request_contact(one_time_code, "Secondo tentativo")
            self.assertEqual(len(alice_service.vault.state["contacts"]), before)
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_offline_message_is_delivered_after_recipient_returns(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            alice = alice_service.identity()
            bob = bob_service.identity()
            alice_service.vault.state["contacts"][bob.identity_id] = bob.to_dict()
            bob_service.vault.state["contacts"][alice.identity_id] = alice.to_dict()
            alice_service.vault.save()
            bob_service.vault.save()
            routes = {
                alice.destination: alice_service,
                destination_b32(alice.destination): alice_service,
            }

            class Endpoint:
                def send(self, destination, payload):
                    if destination not in routes:
                        raise ConnectionError("destinatario offline")
                    routes[destination]._receive(payload)

                def stop(self):
                    pass

            alice_service.sam = Endpoint()
            bob_service.sam = Endpoint()
            self.assertEqual(alice_service.send_message(bob.identity_id, "Arriva dopo"), "queued")
            self.assertEqual(len(alice_service.vault.state["outbox"]), 1)
            self.assertEqual(alice_service.messages_for(bob.identity_id)[0]["status"], "pending")
            routes[bob.destination] = bob_service
            routes[destination_b32(bob.destination)] = bob_service
            message_id = alice_service.vault.state["outbox"][0]["message_id"]
            alice_service._attempt_outbox(message_id, force=True)
            self.assertTrue(self._wait_for(lambda: not alice_service.vault.state["outbox"]))
            self.assertEqual(alice_service.vault.state["outbox"], [])
            self.assertEqual(alice_service.messages_for(bob.identity_id)[0]["status"], "delivered")
            self.assertEqual(bob_service.messages_for(alice.identity_id)[0]["text"], "Arriva dopo")
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_manual_retry_delivers_queued_message_immediately(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            alice = alice_service.identity()
            bob = bob_service.identity()
            alice_service.vault.state["contacts"][bob.identity_id] = bob.to_dict()
            bob_service.vault.state["contacts"][alice.identity_id] = alice.to_dict()
            alice_service.vault.save()
            bob_service.vault.save()
            routes = {}

            class Endpoint:
                def send(self, destination, payload):
                    if destination not in routes:
                        raise ConnectionError("offline")
                    routes[destination]._receive(payload)

                def stop(self):
                    pass

            alice_service.sam = Endpoint()
            bob_service.sam = Endpoint()
            self.assertEqual(alice_service.send_message(bob.identity_id, "Retry ora"), "queued")
            routes[bob.destination] = bob_service
            routes[destination_b32(bob.destination)] = bob_service
            routes[alice.destination] = alice_service
            routes[destination_b32(alice.destination)] = alice_service
            status = alice_service.retry_all_now()
            self.assertEqual(status["messages"], 1)
            self.assertTrue(self._wait_for(lambda: not alice_service.vault.state["outbox"]))
            self.assertEqual(bob_service.messages_for(alice.identity_id)[0]["text"], "Retry ora")
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_optional_warm_failure_does_not_replace_protocol_status(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self._service(Path(folder) / "alice", "Alice")

            class UnavailableSam:
                def warm(self, _destination):
                    raise ConnectionRefusedError(10061, "SAM non ancora pronto")

                def stop(self):
                    pass

            service.sam = UnavailableSam()
            service.last_protocol_event = "Connessione I2P in preparazione"
            self.assertFalse(service._warm_destination("peer"))
            self.assertEqual(service.last_protocol_event, "Connessione I2P in preparazione")
            service.close(wait=True)

    def test_contact_accept_is_retried_when_requester_is_temporarily_unreachable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            alice = alice_service.identity()
            bob = bob_service.identity()
            routes = {
                bob.destination: bob_service,
                destination_b32(bob.destination): bob_service,
            }

            class Endpoint:
                def send(self, destination, payload):
                    if destination not in routes:
                        raise ConnectionError("requester tunnels not ready")
                    routes[destination]._receive(payload)

                def stop(self):
                    pass

            alice_service.sam = Endpoint()
            bob_service.sam = Endpoint()
            alice_service.request_contact(bob_service.contact_code())
            self.assertNotIn(bob.identity_id, alice_service.vault.state["contacts"])
            self.assertEqual(len(bob_service.vault.state["control_outbox"]), 1)

            routes[alice.destination] = alice_service
            routes[destination_b32(alice.destination)] = alice_service
            control = bob_service.vault.state["control_outbox"][0]
            control["last_attempt"] = 0
            bob_service.flush_control_outbox()
            self.assertIn(bob.identity_id, alice_service.vault.state["contacts"])
            self.assertEqual(bob_service.vault.state["control_outbox"], [])
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_recent_previous_minute_contact_code_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self._service(Path(folder) / "bob", "Bob")
            identity = service.identity()
            from kerberus.crypto import rotating_contact_code

            now = int(time.time())
            settings = service.vault.state["settings"]
            settings["contact_code_anchor_time"] = now - 120
            service.vault.save()
            previous = rotating_contact_code(
                identity,
                service.secrets(),
                period_minutes=1,
                generation=settings["contact_code_generation"],
                anchor_time=settings["contact_code_anchor_time"],
                timestamp=now - 60,
            )
            service._consume_contact_code(previous)
            with self.assertRaises(ValueError):
                service._consume_contact_code(previous)
            service.close(wait=True)

    def test_contact_code_policy_is_persisted_and_rotates_after_use(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self._service(Path(folder) / "bob", "Bob")
            service.update_settings(5, True)
            first = service.contact_code()
            service._consume_contact_code(first, "alice")
            second = service.contact_code()
            self.assertNotEqual(first, second)
            self.assertEqual(service.settings()["contact_code_period_minutes"], 5)
            service.close(wait=True)

    @staticmethod
    def _service(root: Path, name: str) -> MessengerService:
        root.mkdir(parents=True)
        service = MessengerService(AppConfig(vault_path=root / "vault.kbv", sam_keys_path=root / "sam.txt"))
        service.vault.create("password-lunga-di-test")
        identity = service.create_identity(name)
        standard = base64.b64encode(os.urandom(400)).decode("ascii")
        destination = standard.replace("+", "-").replace("/", "~")
        update_destination(identity, service.secrets(), destination)
        service.vault.state["identity"] = identity.to_dict()
        service.vault.save()
        return service


if __name__ == "__main__":
    unittest.main()
