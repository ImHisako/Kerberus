import copy
import unittest

from kerberus.crypto import generate_identity
from kerberus.ratchet import RatchetError, accept_init, complete_init, decrypt, encrypt, initiate


class DoubleRatchetTests(unittest.TestCase):
    def setUp(self):
        self.alice, self.alice_secrets = generate_identity("Alice")
        self.bob, self.bob_secrets = generate_identity("Bob")
        self.alice_states = {}
        self.bob_states = {}
        init = initiate(self.alice_states, self.alice, self.alice_secrets, self.bob)
        ready = accept_init(self.bob_states, self.bob, self.bob_secrets, self.alice, init)
        complete_init(self.alice_states, self.alice, self.alice_secrets, self.bob, ready)

    def test_content_is_rejected_before_both_ephemeral_keys_are_contributed(self):
        states = {}
        initiate(states, self.alice, self.alice_secrets, self.bob)
        with self.assertRaises(RatchetError):
            encrypt(states, self.alice, self.alice_secrets, self.bob, {"text": "too early"})

    def test_alternating_messages_advance_dh_ratchet(self):
        first = encrypt(self.alice_states, self.alice, self.alice_secrets, self.bob, {"text": "one"})
        self.assertEqual(decrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, first)["text"], "one")
        reply = encrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, {"text": "two"})
        self.assertEqual(decrypt(self.alice_states, self.alice, self.alice_secrets, self.bob, reply)["text"], "two")
        third = encrypt(self.alice_states, self.alice, self.alice_secrets, self.bob, {"text": "three"})
        self.assertEqual(decrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, third)["text"], "three")
        self.assertNotEqual(first["dh"], third["dh"])

    def test_out_of_order_messages_use_bounded_skipped_keys(self):
        messages = [
            encrypt(self.alice_states, self.alice, self.alice_secrets, self.bob, {"text": str(index)})
            for index in range(3)
        ]
        self.assertEqual(decrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, messages[2])["text"], "2")
        self.assertEqual(decrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, messages[0])["text"], "0")
        self.assertEqual(decrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, messages[1])["text"], "1")
        self.assertLessEqual(len(self.bob_states[self.alice.identity_id]["skipped"]), 256)

    def test_current_state_cannot_decrypt_consumed_message_key(self):
        first = encrypt(self.alice_states, self.alice, self.alice_secrets, self.bob, {"text": "past"})
        decrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, first)
        compromised_current_state = copy.deepcopy(self.bob_states)
        with self.assertRaises(RatchetError):
            decrypt(compromised_current_state, self.bob, self.bob_secrets, self.alice, first)

    def test_tamper_does_not_advance_receiver_state(self):
        message = encrypt(self.alice_states, self.alice, self.alice_secrets, self.bob, {"text": "auth"})
        before = copy.deepcopy(self.bob_states)
        tampered = dict(message)
        tampered["ratchet_ciphertext"] = tampered["ratchet_ciphertext"][:-2] + "AA"
        with self.assertRaises(RatchetError):
            decrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, tampered)
        self.assertEqual(self.bob_states, before)
        self.assertEqual(decrypt(self.bob_states, self.bob, self.bob_secrets, self.alice, message)["text"], "auth")


if __name__ == "__main__":
    unittest.main()
