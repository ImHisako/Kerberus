import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from kerberus.ui import MessageBubble


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_message_bubble_renders_text_and_delivery_state(self):
        bubble = MessageBubble("Messaggio visibile", 1_700_000_000, True, "pending")
        labels = [label.text() for label in bubble.findChildren(QLabel)]
        self.assertIn("Messaggio visibile", labels)
        self.assertTrue(any("In attesa" in label for label in labels))


if __name__ == "__main__":
    unittest.main()
