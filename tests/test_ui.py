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

    def test_delivery_status_updates_bubble_without_rebuilding_chat(self):
        window = KerberusWindow()
        window._build_ui()
        window.selected_contact = "peer"
        messages = [{
            "message_id": "1" * 32,
            "contact_id": "peer",
            "text": "Stato stabile",
            "time": 1_700_000_000,
            "sent_at": 1_700_000_000,
            "direction": "out",
            "status": "sent",
        }]
        window.service.messages_for = lambda _contact: messages
        window.refresh_messages("new", "peer")
        self.app.processEvents()
        original = window._message_bubbles["1" * 32]
        messages[0]["status"] = "delivered"
        window.refresh_messages("status", "peer")
        self.assertIs(window._message_bubbles["1" * 32], original)
        labels = [label.text() for label in original.findChildren(QLabel)]
        self.assertTrue(any("Consegnato" in label for label in labels))
        window.service.close()

    def test_new_message_is_appended_without_rebuilding_existing_bubbles(self):
        window = KerberusWindow()
        window._build_ui()
        window.selected_contact = "peer"
        messages = [{
            "message_id": "1" * 32,
            "contact_id": "peer",
            "text": "Primo",
            "time": 1_700_000_000,
            "sent_at": 1_700_000_000,
            "direction": "out",
            "status": "sent",
        }]
        window.service.messages_for = lambda _contact: messages
        window.refresh_messages("select", "peer")
        self.app.processEvents()
        original = window._message_bubbles["1" * 32]
        messages.append({
            "message_id": "2" * 32,
            "contact_id": "peer",
            "text": "Secondo",
            "time": 1_700_000_001,
            "sent_at": 1_700_000_001,
            "direction": "out",
            "status": "pending",
        })
        window.refresh_messages("new", "peer")
        self.assertIs(window._message_bubbles["1" * 32], original)
        self.assertEqual(len(window._message_bubbles), 2)
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
