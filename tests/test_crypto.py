import base64
import os
import unittest

from kerberus.crypto import (
    destination_b32,
    generate_identity,
    open_message,
    pq_available,
    profile_destination,
    rotating_contact_code,
    seal_message,
    update_destination,
)


@unittest.skipUnless(pq_available(), "pqcrypto non installato")
class CryptoTests(unittest.TestCase):
    def test_hybrid_round_trip_and_signature(self):
        alice, alice_secrets = generate_identity("Alice", "alice-destination")
        bob, bob_secrets = generate_identity("Bob", "bob-destination")
        envelope = seal_message(alice, alice_secrets, bob, "messaggio segreto")
        self.assertEqual(open_message(bob, bob_secrets, alice, envelope), "messaggio segreto")
        envelope["ciphertext"] = envelope["ciphertext"][:-2] + "AA"
        with self.assertRaises(Exception):
            open_message(bob, bob_secrets, alice, envelope)

    def test_identity_bundle_verifies(self):
        identity, _ = generate_identity("Alice")
        identity.verify()
        identity.name = "Mallory"
        with self.assertRaises(Exception):
            identity.verify()

    def test_similar_messages_use_same_size_bucket(self):
        alice, alice_secrets = generate_identity("Alice", "alice-destination")
        bob, _ = generate_identity("Bob", "bob-destination")
        short = seal_message(alice, alice_secrets, bob, "ciao")
        longer = seal_message(alice, alice_secrets, bob, "ciao, questo testo è un po' più lungo")
        self.assertEqual(len(short["ciphertext"]), len(longer["ciphertext"]))

    def test_profile_code_is_bound_to_i2p_destination(self):
        identity, secrets = generate_identity("Alice")
        standard = base64.b64encode(os.urandom(400)).decode("ascii")
        destination = standard.replace("+", "-").replace("/", "~")
        update_destination(identity, secrets, destination)
        self.assertRegex(identity.profile_code, r"^[A-Z2-9]{4}-KERBERUS-[a-z2-7]{52}$")
        self.assertEqual(profile_destination(identity.profile_code), destination_b32(destination))
        identity.verify()

    def test_contact_code_rotates_each_minute(self):
        identity, secrets = generate_identity("Alice")
        standard = base64.b64encode(os.urandom(400)).decode("ascii")
        destination = standard.replace("+", "-").replace("/", "~")
        update_destination(identity, secrets, destination)
        first = rotating_contact_code(identity, secrets, minute=100)
        second = rotating_contact_code(identity, secrets, minute=101)
        self.assertNotEqual(first, second)
        self.assertEqual(profile_destination(first), profile_destination(second))
        self.assertRegex(first, r"^[A-Z2-9]{4}-KERBERUS-[A-Z2-9]{16}-[a-z2-7]{52}$")


if __name__ == "__main__":
    unittest.main()
