import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from kerberus.config import AppConfig
from kerberus.service import MessengerService


@unittest.skipUnless(os.environ.get("KERBERUS_LIVE_I2P") == "1", "requires a live local I2P router")
class LiveI2PTests(unittest.TestCase):
    def test_two_real_sam_destinations_complete_contact_exchange(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            services = []
            for name in ("Alice", "Bob"):
                service = MessengerService(AppConfig(
                    vault_path=root / name / "vault.kbv",
                    sam_keys_path=root / name / "sam.keys",
                ))
                service.vault.create("password-lunga-live")
                service.create_identity(name)
                services.append(service)

            errors = []

            def connect(service):
                try:
                    service.connect_router()
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=connect, args=(service,)) for service in services]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(180)
            self.assertFalse(errors)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            if os.environ.get("KERBERUS_REQUIRE_NATIVE") == "1":
                self.assertTrue(all(service.sam.native_active for service in services))

            alice, bob = services
            events = {"alice": [], "bob": []}
            alice.on_protocol_event = lambda kind, detail: events["alice"].append((kind, detail))
            bob.on_protocol_event = lambda kind, detail: events["bob"].append((kind, detail))
            result = alice.request_contact(bob.contact_code(), "live hello")
            deadline = time.time() + 180
            while time.time() < deadline:
                if alice.contacts() and bob.contacts():
                    break
                time.sleep(2)
            diagnostics = (
                f"send={result} alice_contacts={len(alice.contacts())} bob_contacts={len(bob.contacts())} "
                f"alice_pending={len(alice.vault.state['pending'])} "
                f"bob_control={len(bob.vault.state['control_outbox'])} events={events}"
            )
            self.assertEqual(len(alice.contacts()), 1, diagnostics)
            self.assertEqual(len(bob.contacts()), 1, diagnostics)
            deadline = time.time() + 180
            while time.time() < deadline:
                if bob.messages_for(alice.identity().identity_id):
                    break
                time.sleep(1)
            self.assertEqual(bob.messages_for(alice.identity().identity_id)[0]["text"], "live hello")
            deadline = time.time() + 60
            while time.time() < deadline:
                if any(message.get("status") == "delivered" for message in alice.messages_for(bob.identity().identity_id)):
                    break
                time.sleep(1)
            self.assertTrue(
                any(message.get("status") == "delivered" for message in alice.messages_for(bob.identity().identity_id)),
                f"first ACK failed: events={events}",
            )
            bob.send_message(alice.identity().identity_id, "live reply")
            deadline = time.time() + 180
            while time.time() < deadline:
                replies = alice.messages_for(bob.identity().identity_id)
                if any(message["direction"] == "in" and message["text"] == "live reply" for message in replies):
                    break
                time.sleep(2)
            self.assertTrue(
                any(
                    message["direction"] == "in" and message["text"] == "live reply"
                    for message in alice.messages_for(bob.identity().identity_id)
                ),
                f"bidirectional delivery failed: events={events}",
            )
            deadline = time.time() + 60
            while time.time() < deadline:
                replies = bob.messages_for(alice.identity().identity_id)
                if any(message["direction"] == "out" and message.get("status") == "delivered" for message in replies):
                    break
                time.sleep(1)
            self.assertTrue(
                any(
                    message["direction"] == "out" and message.get("status") == "delivered"
                    for message in bob.messages_for(alice.identity().identity_id)
                ),
                f"reply ACK failed: events={events}",
            )
            burst_started = time.perf_counter()
            for index in range(5):
                alice.send_message(bob.identity().identity_id, f"native burst {index}")
            deadline = time.time() + 30
            while time.time() < deadline:
                received = bob.messages_for(alice.identity().identity_id)
                if sum(message["text"].startswith("native burst") for message in received) == 5:
                    break
                time.sleep(0.05)
            burst_seconds = time.perf_counter() - burst_started
            received = bob.messages_for(alice.identity().identity_id)
            self.assertEqual(sum(message["text"].startswith("native burst") for message in received), 5)
            self.assertLess(burst_seconds, 30)
            print(f"native_hot_stream_5_messages={burst_seconds:.3f}s")
            if os.environ.get("KERBERUS_REQUIRE_NATIVE") == "1":
                self.assertGreater(
                    sum(service.sam._native.frames_received for service in services if service.sam._native),
                    0,
                    "nessun frame è stato ricevuto dal percorso Go",
                )
            for service in services:
                service.close()
