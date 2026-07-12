import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from kerberus.ui import KerberusWindow, MessageBubble


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_message_bubble_renders_text_and_delivery_state(self):
        bubble = MessageBubble("Messaggio visibile", 1_700_000_000, True, "pending")
        labels = [label.text() for label in bubble.findChildren(QLabel)]
        self.assertIn("Messaggio visibile", labels)
        self.assertTrue(any("In attesa" in label for label in labels))

    def test_resize_border_does_not_cover_chat_scrollbar(self):
        window = KerberusWindow()
        self.assertLess(window._resize_margin, 12)
        window.service.close()

    def test_operational_dialogs_are_modeless(self):
        window = KerberusWindow()
        window.show_ui_console()
        self.app.processEvents()
        self.assertTrue(window._open_dialogs)
        self.assertTrue(all(not dialog.isModal() for dialog in window._open_dialogs))
        self.assertTrue(window.isEnabled())
        for dialog in list(window._open_dialogs):
            dialog.close()
        window.service.close()


if __name__ == "__main__":
    unittest.main()
