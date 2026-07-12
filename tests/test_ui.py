import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton
from PyQt6.QtGui import QCloseEvent

from kerberus.crypto import generate_identity
from kerberus.ui import EmojiPicker, KerberusWindow, MessageBubble, emoji_catalog, localize_widget, set_language


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_message_bubble_renders_text_and_delivery_state(self):
        bubble = MessageBubble("Messaggio visibile", 1_700_000_000, True, "pending")
        labels = [label.text() for label in bubble.findChildren(QLabel)]
        self.assertIn("Messaggio visibile", labels)
        self.assertTrue(any("In attesa" in label for label in labels))

    def test_complete_searchable_emoji_catalog_and_large_buttons(self):
        self.assertGreaterEqual(len(emoji_catalog()), 5000)
        self.assertTrue(any(value == "❤️" for value, _italian, _english in emoji_catalog()))
        picker = EmojiPicker(lambda _value: None, reaction=True)
        picker.search.setText("cuore")
        self.assertGreater(len(picker._filtered), 1)
        self.assertLess(len(picker._filtered), len(emoji_catalog()))
        picker.close()

        window = KerberusWindow()
        window._build_ui()
        emoji_button = next(button for button in window.findChildren(QToolButton) if button.text() == "☺")
        self.assertGreaterEqual(emoji_button.width(), 50)
        author, _secrets = generate_identity("Alice")
        bubble = MessageBubble("x", 1_700_000_000, False, on_action=lambda *_args: None, author=author)
        self.assertFalse(any(button.text() == "☺+" for button in bubble.findChildren(QToolButton)))
        labels = [label.text() for label in bubble.findChildren(QLabel)]
        self.assertIn("Alice", labels)
        self.assertTrue(any(label.pixmap() and not label.pixmap().isNull() for label in bubble.findChildren(QLabel)))
        window.service.close()

    def test_english_language_translates_dynamic_delivery_state(self):
        set_language("en")
        try:
            bubble = MessageBubble("Visible", 1_700_000_000, True, "delivered")
            labels = [label.text() for label in bubble.findChildren(QLabel)]
            self.assertTrue(any("Delivered" in label for label in labels))
            window = KerberusWindow()
            window._build_ui()
            localize_widget(window)
            self.assertEqual(window.composer.placeholderText(), "Write a message")
            window.service.close()
        finally:
            set_language("it")

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

    def test_opening_large_chat_is_paginated_and_does_not_warm_peer(self):
        window = KerberusWindow()
        window._build_ui()
        contact, _secrets = generate_identity("Bob")
        window.service.contacts = lambda: [contact]
        messages = [{
            "message_id": f"{index:032x}", "contact_id": contact.identity_id,
            "text": f"Messaggio {index}", "time": 1_700_000_000 + index,
            "sent_at": 1_700_000_000 + index, "direction": "in", "status": "received",
        } for index in range(500)]
        window.service.messages_for = lambda _contact: messages
        window.service.warm_contact = Mock()
        window.service.mark_chat_read = Mock(return_value=0)
        window.select_contact(contact.identity_id)
        self.assertEqual(len(window._message_bubbles), window._message_page_size)
        self.assertEqual(window._message_render_start, 500 - window._message_page_size)
        window.service.warm_contact.assert_not_called()
        buttons = [button.text() for button in window.message_container.findChildren(QPushButton)]
        self.assertTrue(any("Carica messaggi precedenti" in text for text in buttons))
        window.service.close()

    def test_incoming_contact_events_reconcile_sidebar(self):
        window = KerberusWindow()
        window._build_ui()
        window.refresh_contacts = Mock()
        window._protocol_event("contact_request_received", "Richiesta valida")
        window.refresh_contacts.assert_called_once()
        window.refresh_contacts.reset_mock()
        window.selected_contact = ""
        window.refresh_messages("new", "peer")
        window.refresh_contacts.assert_called_once()
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

    def test_same_modeless_dialog_opens_only_once(self):
        window = KerberusWindow()
        window.show_ui_console()
        self.app.processEvents()
        first = next(iter(window._open_dialogs))
        window.show_ui_console()
        self.app.processEvents()
        self.assertEqual(len(window._open_dialogs), 1)
        self.assertIs(next(iter(window._open_dialogs)), first)
        first.close()
        self.app.processEvents()
        window.service.close()

    def test_window_x_restores_close_confirmation(self):
        window = KerberusWindow()
        window._shutdown = Mock()
        event = QCloseEvent()
        with patch("kerberus.ui.KerberusMessageDialog.ask", return_value=False) as ask:
            window.closeEvent(event)
        ask.assert_called_once()
        self.assertFalse(event.isAccepted())
        window._shutdown.assert_not_called()
        event = QCloseEvent()
        with patch("kerberus.ui.KerberusMessageDialog.ask", return_value=True):
            window.closeEvent(event)
        self.assertTrue(event.isAccepted())
        window._shutdown.assert_called_once()
        window.service.close()

    def test_tray_exit_runs_complete_shutdown(self):
        window = KerberusWindow()
        window.close = Mock()
        window._shutdown = Mock()
        window.exit_from_tray()
        self.assertTrue(window._allow_close)
        window.close.assert_called_once()
        window._shutdown.assert_called_once()
        window.service.close()

    def test_shutdown_stops_service_router_tray_and_application(self):
        window = KerberusWindow()
        window.service.close = Mock()
        window._tray = Mock()
        window._quit_application = Mock()
        with patch("kerberus.ui.RouterInstaller.stop_running") as stop_router:
            window._shutdown()
            window._shutdown()
        window.service.close.assert_called_once()
        window._tray.hide.assert_called_once()
        stop_router.assert_called_once()
        self.assertEqual(window._quit_application.call_count, 2)


if __name__ == "__main__":
    unittest.main()
