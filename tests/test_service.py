import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from kerberus.config import AppConfig
from kerberus.crypto import destination_b32, generate_identity, pq_available, profile_destination, seal_message, sign_control, update_destination
from kerberus.service import MessengerService
from kerberus.ratchet import accept_init, complete_init, initiate


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

    def test_stream_proof_preference_is_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = MessengerService(AppConfig(vault_path=root / "vault.kbv", sam_keys_path=root / "sam.txt"))
            service.vault.create("password-lunga-di-test")
            self.assertFalse(service.settings()["stream_proof_enabled"])
            service.update_privacy_settings(stream_proof_enabled=True)
            self.assertTrue(service.settings()["stream_proof_enabled"])
            service.close(wait=True)

    def test_obsolete_ipinfo_token_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = MessengerService(AppConfig(vault_path=root / "vault.kbv", sam_keys_path=root / "sam.txt"))
            service.vault.create("password-lunga-di-test")
            service.vault.state["settings"]["ipinfo_token"] = "legacy-token"
            self.assertNotIn("ipinfo_token", service.settings())
            service.close(wait=True)

    def test_identity_id_visibility_is_shared_with_the_contact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            alice, bob = alice_service.identity(), bob_service.identity()
            alice_service.vault.state["contacts"][bob.identity_id] = bob.to_dict()
            bob_service.vault.state["contacts"][alice.identity_id] = alice.to_dict()
            alice_service.vault.save()
            bob_service.vault.save()
            routes = {alice.destination: alice_service, bob.destination: bob_service}

            class Endpoint:
                def send(self, destination, payload):
                    routes[destination]._receive(payload)

                def stop(self):
                    pass

            alice_service.sam = Endpoint()
            bob_service.sam = Endpoint()
            alice_service.update_chat_settings(bob.identity_id, show_identity_id=False)
            self.assertTrue(self._wait_for(
                lambda: not bob_service.chat_settings(alice.identity_id)["remote_identity_id_visible"]
            ))
            self.assertFalse(alice_service.chat_settings(bob.identity_id)["show_identity_id"])
            alice_service.update_chat_settings(bob.identity_id, show_identity_id=True)
            self.assertTrue(self._wait_for(
                lambda: bob_service.chat_settings(alice.identity_id)["remote_identity_id_visible"]
            ))
            alice_service.close(wait=True)
            bob_service.close(wait=True)

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
            self._establish_ratchet(alice_service, bob_service)

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
            tampered["ciphertext"] = tampered["ciphertext"][:-2] + "AA"
            with self.assertRaises(Exception):
                alice_service._receive(json.dumps(tampered).encode("utf-8"))
            second = alice_service.messages_for(bob.identity_id)[1]
            self.assertNotEqual(second["status"], "delivered")
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
            self._establish_ratchet(alice_service, bob_service)
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

    def test_delete_pending_message_removes_local_copy_and_outbox(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            bob = bob_service.identity()
            alice_service.vault.state["contacts"][bob.identity_id] = bob.to_dict()
            alice_service.vault.save()

            class Offline:
                def send(self, *_args):
                    raise ConnectionError("offline")

                def stop(self):
                    pass

            alice_service.sam = Offline()
            alice_service.send_message(bob.identity_id, "da eliminare")
            message_id = alice_service.messages_for(bob.identity_id)[0]["message_id"]
            self.assertTrue(alice_service.delete_message(message_id))
            self.assertEqual(alice_service.messages_for(bob.identity_id), [])
            self.assertEqual(alice_service.vault.state["outbox"], [])
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_forward_creates_fresh_envelope_without_original_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            bob = bob_service.identity()
            alice_service.vault.state["contacts"][bob.identity_id] = bob.to_dict()
            alice_service.vault.save()
            captured = []

            class Endpoint:
                def send(self, _destination, payload):
                    captured.append(json.loads(payload))

                def stop(self):
                    pass

            alice_service.sam = Endpoint()
            alice_service.forward_message(bob.identity_id, "testo inoltrato")
            self.assertEqual(len(captured), 1)
            self.assertNotIn("forwarded_from", captured[0])
            self.assertEqual(captured[0]["type"], "message")
            alice_service.close(wait=True)
            bob_service.close(wait=True)

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

    def test_contact_accept_returns_on_same_full_duplex_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            captured = []

            class Capture:
                def send(self, _destination, payload):
                    captured.append(payload)

                def stop(self):
                    pass

            alice_service.sam = Capture()
            bob_service.sam = Capture()
            alice_service.request_contact(bob_service.contact_code())
            response = bob_service._receive(captured[0], inline_reply=True)
            self.assertIsNotNone(response)
            self.assertEqual(json.loads(response)["type"], "contact_accept")
            self.assertEqual(bob_service.vault.state["control_outbox"], [])
            alice_service._receive(response)
            self.assertEqual(len(alice_service.contacts()), 1)
            self.assertEqual(alice_service.vault.state["pending"], {})
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_pending_contact_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")

            class Offline:
                def send(self, *_args):
                    raise ConnectionError("offline")

                def stop(self):
                    pass

            alice_service.sam = Offline()
            self.assertEqual(alice_service.request_contact(bob_service.contact_code()), "queued")
            pending = alice_service.pending_contacts()
            self.assertEqual(len(pending), 1)
            self.assertTrue(alice_service.cancel_pending_contact(pending[0]["destination"]))
            self.assertEqual(alice_service.pending_contacts(), [])
            self.assertFalse(alice_service.cancel_pending_contact(pending[0]["destination"]))
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_chat_debug_export_contains_delays_without_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            bob = bob_service.identity()
            alice_service.vault.state["contacts"][bob.identity_id] = bob.to_dict()
            alice_service.vault.state["messages"].append({
                "message_id": "d" * 32,
                "contact_id": bob.identity_id,
                "direction": "out",
                "text": "Messaggio diagnostico",
                "time": 100,
                "sent_at": 100,
                "received_at": None,
                "recipient_received_at": 102,
                "delivered_at": 104,
                "read_at": 106,
                "status": "read",
                "reactions": {bob.identity_id: "👍"},
            })
            alice_service.vault.save()
            report = json.loads(alice_service.export_chat_debug(bob.identity_id))
            self.assertEqual(report["format"], "kerberus-chat-debug-v1")
            self.assertEqual(report["diagnostics"]["message_count"], 1)
            exported = report["messages"][0]
            self.assertEqual(exported["text"], "Messaggio diagnostico")
            self.assertEqual(exported["delays_seconds"]["one_way_clock_dependent"], 2)
            self.assertEqual(exported["delays_seconds"]["round_trip_local_clock"], 4)
            self.assertEqual(exported["delays_seconds"]["read_after_send"], 6)
            self.assertNotIn("payload", exported)
            self.assertNotIn("destination", report["contact"])
            self.assertNotIn("secrets", report)
            self.assertNotIn("ratchets", report)
            self.assertNotIn(alice_service.secrets().signing_private, alice_service.export_chat_debug(bob.identity_id))
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

    def test_unsolicited_or_wrong_stream_contact_accept_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            victim = self._service(root / "victim", "Victim")
            attacker = self._service(root / "attacker", "Attacker")
            request_id = "a" * 32
            accept = {
                "version": 1, "type": "contact_accept", "request_id": request_id,
                "sender": attacker.identity().to_dict(),
            }
            accept["signature"] = sign_control(attacker.secrets(), accept)
            with self.assertRaises(ValueError):
                victim._receive(json.dumps(accept).encode())
            self.assertNotIn(attacker.identity().identity_id, victim.vault.state["contacts"])

            destination = profile_destination(attacker.identity().profile_code)
            victim.vault.state["pending"][destination] = {"request_id": request_id, "first_message": ""}
            victim.vault.save()
            wrong_peer = self._service(root / "wrong-peer", "Wrong peer")
            with self.assertRaises(ValueError):
                victim._receive(json.dumps(accept).encode(), wrong_peer.identity().destination)
            self.assertNotIn(attacker.identity().identity_id, victim.vault.state["contacts"])
            victim.close(wait=True)
            attacker.close(wait=True)
            wrong_peer.close(wait=True)

    def test_contact_code_policy_is_persisted_and_rotates_after_use(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self._service(Path(folder) / "bob", "Bob")
            service.update_settings(5, True)
            first = service.contact_code()
            service._consume_contact_code(first, "alice")
            second = service.contact_code()
            self.assertNotEqual(first, second)
            self.assertEqual(service.settings()["contact_code_period_minutes"], 5)
            service.update_privacy_settings(language="en")
            self.assertEqual(service.settings()["language"], "en")
            with self.assertRaises(ValueError):
                service.update_privacy_settings(language="xx")
            service.close(wait=True)

    def test_encrypted_read_receipt_and_reaction_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            alice, bob = alice_service.identity(), bob_service.identity()
            alice_service.vault.state["contacts"][bob.identity_id] = bob.to_dict()
            bob_service.vault.state["contacts"][alice.identity_id] = alice.to_dict()
            alice_service.vault.save()
            bob_service.vault.save()
            routes = {alice.destination: alice_service, bob.destination: bob_service}

            class Endpoint:
                def send(self, destination, payload):
                    routes[destination]._receive(payload)

                def stop(self):
                    pass

            alice_service.sam = Endpoint()
            bob_service.sam = Endpoint()
            alice_service.send_message(bob.identity_id, "Ricevuta cifrata")
            self.assertTrue(self._wait_for(lambda: bool(bob_service.messages_for(alice.identity_id))))
            incoming = bob_service.messages_for(alice.identity_id)[0]
            bob_service.react_to_message(alice.identity_id, incoming["message_id"], "👍")
            bob_service.mark_chat_read(alice.identity_id)
            self.assertTrue(self._wait_for(lambda: alice_service.messages_for(bob.identity_id)[0]["status"] == "read"))
            outgoing = alice_service.messages_for(bob.identity_id)[0]
            self.assertEqual(outgoing["reactions"][bob.identity_id], "👍")
            bob_service.react_to_message(alice.identity_id, incoming["message_id"], "👍")
            self.assertTrue(self._wait_for(lambda: bob.identity_id not in outgoing.get("reactions", {})))
            self.assertNotIn(bob.identity_id, incoming.get("reactions", {}))
            with self.assertRaises(ValueError):
                bob_service.react_to_message(alice.identity_id, incoming["message_id"], "not-an-emoji")
            self.assertEqual(alice_service.vault.state["outbox"], [])
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    def test_read_receipts_can_be_disabled_per_chat(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            alice_service = self._service(root / "alice", "Alice")
            bob_service = self._service(root / "bob", "Bob")
            alice, bob = alice_service.identity(), bob_service.identity()
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

            bob_service.sam = Endpoint()
            bob_service._store_message(alice.identity_id, "in", "Privato", message_id="a" * 32)
            bob_service.update_chat_settings(alice.identity_id, send_read_receipts=False)
            self.assertEqual(bob_service.mark_chat_read(alice.identity_id), 1)
            self.assertEqual(captured, [])
            alice_service.close(wait=True)
            bob_service.close(wait=True)

    @staticmethod
    def _establish_ratchet(first: MessengerService, second: MessengerService) -> None:
        first_identity, second_identity = first.identity(), second.identity()
        init = initiate(first.vault.state.setdefault("ratchets", {}), first_identity, first.secrets(), second_identity)
        ready = accept_init(second.vault.state.setdefault("ratchets", {}), second_identity, second.secrets(), first_identity, init)
        complete_init(first.vault.state["ratchets"], first_identity, first.secrets(), second_identity, ready)
        first.vault.save()
        second.vault.save()

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
