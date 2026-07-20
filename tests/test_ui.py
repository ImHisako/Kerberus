import os
import base64
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QStyleOptionViewItem, QToolButton
from PyQt6.QtCore import QBuffer, QEvent, QIODevice, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QCloseEvent, QImage, QPainter, QWheelEvent
from PyQt6.QtTest import QSignalSpy, QTest

from kerberus.crypto import generate_identity
from kerberus.ui import (
    STYLE, EmojiPanel, EmojiPicker, ExternalLinkDialog, InlineConfirmationPanel, KerberusWindow, MessageBubble, ModernComboBox,
    NetworkInsightsPanel, SettingsToggleRow, ToggleSwitch, VirtualChatView, emoji_catalog, is_emoji_reaction,
    audio_device_id, localize_widget, resolve_audio_device,
    open_external_link, set_language, set_window_capture_exclusion,
)


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._windows: list[KerberusWindow] = []
        original_init = KerberusWindow.__init__

        def tracked_init(window, *args, **kwargs):
            original_init(window, *args, **kwargs)
            self._windows.append(window)

        self._window_init_patcher = patch.object(KerberusWindow, "__init__", tracked_init)
        self._window_init_patcher.start()

    def tearDown(self):
        # KerberusWindow owns Python workers in addition to its Qt children.
        # Drain them before deferred Qt deletion to avoid callbacks reaching
        # already-destroyed widgets and aborting the whole test process.
        try:
            for window in self._windows:
                for dialog in list(window._open_dialogs):
                    dialog.close()
                window._release_resources(wait=True)
            self.app.processEvents()
            for window in self._windows:
                window.hide()
                window.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
        finally:
            self._window_init_patcher.stop()

    def test_message_bubble_renders_text_and_delivery_state(self):
        bubble = MessageBubble("Messaggio visibile", 1_700_000_000, True, "pending")
        labels = [label.text() for label in bubble.findChildren(QLabel)]
        self.assertIn("Messaggio visibile", labels)
        self.assertTrue(any("In attesa" in label for label in labels))

    def test_virtual_message_bubbles_follow_the_content_width(self):
        window = KerberusWindow()
        window._build_ui()
        local_identity, _secrets = generate_identity("Edward")
        window.message_view.chat_delegate.configure(local_identity, None, None, None, False)
        delegate = window.message_view.chat_delegate
        short = delegate._layout(
            {"text": "M", "direction": "out", "sent_at": 1_700_000_000, "status": "sent"},
            820, window.font(),
        )
        long = delegate._layout(
            {"text": "Questo è un messaggio abbastanza lungo da occupare gran parte della riga della conversazione.",
             "direction": "out", "sent_at": 1_700_000_000, "status": "sent"},
            820, window.font(),
        )
        self.assertLess(short["bubble_width"], 180)
        self.assertGreater(long["bubble_width"], short["bubble_width"])
        window.service.close()

    def test_voice_message_has_a_compact_clickable_player(self):
        view = VirtualChatView()
        view.resize(760, 240)
        local, _secrets = generate_identity("Alice")
        view.configure(local, None, None, None, False)
        message = {
            "message_id": "a" * 32,
            "kind": "voice",
            "voice": {"duration_ms": 12_400},
            "text": "Messaggio vocale",
            "direction": "out",
            "sent_at": 1_700_000_000,
            "status": "sent",
        }
        geometry = view.chat_delegate._layout(message, 760, view.font())
        self.assertTrue(geometry["voice_message"])
        self.assertEqual(geometry["voice_duration"], "0:12")
        self.assertGreaterEqual(geometry["bubble_width"], 250)
        row = QRect(0, 0, 760, int(geometry["row_height"]))
        bubble = view.chat_delegate._bubble_rect(row, geometry)
        point = QPoint(
            bubble.left() + 30,
            bubble.top() + int(geometry["author_height"]) + 25,
        )
        self.assertTrue(view.chat_delegate.voice_at(message, row, view.font(), point))

        view.chat_model.set_messages([message])
        option = QStyleOptionViewItem()
        option.rect = row
        option.font = view.font()
        image = QImage(row.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            view.chat_delegate.paint(painter, option, view.chat_model.index(0, 0))
        finally:
            painter.end()

    def test_microphone_action_has_the_expected_icon(self):
        window = KerberusWindow()
        window._build_ui()
        self.assertFalse(window.voice_button.icon().isNull())
        self.assertIn("vocale", window.voice_button.toolTip().lower())
        self.assertEqual(window.voice_button.iconSize().width(), 21)
        window.service.close()

    def test_attachment_button_precedes_composer_and_attachment_cards_are_interactive(self):
        window = KerberusWindow()
        window._build_ui()
        window.show()
        self.app.processEvents()
        self.assertFalse(window.attachment_button.icon().isNull())
        composer_layout = window.attachment_button.parentWidget().layout()
        self.assertLess(composer_layout.indexOf(window.attachment_button), composer_layout.indexOf(window.composer))
        self.assertIn("100 MB", window.attachment_button.toolTip())

        delegate = window.message_view.chat_delegate
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        image_message = {
            "message_id": "1" * 32, "kind": "attachment", "direction": "in", "sent_at": 1_700_000_000,
            "attachment": {"name": "foto.png", "mime": "image/png", "size": len(png),
                           "sha256": "image", "data": base64.b64encode(png).decode("ascii")},
        }
        image_layout = delegate._layout(image_message, 760, window.font())
        self.assertTrue(image_layout["attachment_image"])
        self.assertGreater(image_layout["body_height"], 100)

        file_message = {
            "message_id": "2" * 32, "kind": "attachment", "direction": "out", "sent_at": 1_700_000_000,
            "status": "sent", "attachment": {"name": "documento.pdf", "mime": "application/pdf",
            "size": 100, "sha256": "file", "data": base64.b64encode(b"x" * 100).decode("ascii")},
        }
        geometry = delegate._layout(file_message, 760, window.font())
        row = QRect(0, 0, 760, int(geometry["row_height"]))
        bubble = delegate._bubble_rect(row, geometry)
        save_point = QPoint(
            bubble.right() - 14 - 50,
            bubble.top() + 10 + int(geometry["author_height"]) + 35,
        )
        self.assertEqual(delegate.attachment_action_at(file_message, row, window.font(), save_point), "save_attachment")

        transferring = {
            **file_message,
            "message_id": "3" * 32,
            "attachment": {**file_message["attachment"], "state": "transferring", "progress": 42,
                           "completed_chunks": 2, "total_chunks": 5, "transfer_id": "a" * 32},
        }
        transfer_geometry = delegate._layout(transferring, 760, window.font())
        self.assertGreater(transfer_geometry["body_height"], transfer_geometry["attachment_content_height"])
        transfer_row = QRect(0, 0, 760, int(transfer_geometry["row_height"]))
        transfer_bubble = delegate._bubble_rect(transfer_row, transfer_geometry)
        controls_y = (
            transfer_bubble.top() + 10 + int(transfer_geometry["author_height"])
            + int(transfer_geometry["attachment_content_height"]) + 12
        )
        pause_point = QPoint(transfer_bubble.right() - 14 - 150, controls_y + 15)
        cancel_point = QPoint(transfer_bubble.right() - 14 - 50, controls_y + 15)
        self.assertEqual(delegate.attachment_action_at(transferring, transfer_row, window.font(), pause_point), "pause_attachment")
        self.assertEqual(delegate.attachment_action_at(transferring, transfer_row, window.font(), cancel_point), "cancel_attachment")
        window.message_view.chat_model.set_messages([transferring])
        option = QStyleOptionViewItem()
        option.rect = transfer_row
        option.font = window.font()
        rendered = QImage(transfer_row.size(), QImage.Format.Format_ARGB32_Premultiplied)
        rendered.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rendered)
        try:
            delegate.paint(painter, option, window.message_view.chat_model.index(0, 0))
        finally:
            painter.end()
        window.hide()
        window.service.close()
        window._attachment_temp_dir.cleanup()

    def test_saved_audio_device_is_resolved_or_falls_back(self):
        class Device:
            def __init__(self, value: bytes):
                self.value = value

            def id(self):
                return self.value

        default = Device(b"default")
        selected = Device(b"headphones")
        self.assertEqual(audio_device_id(selected), b"headphones".hex())
        self.assertIs(resolve_audio_device([selected], b"headphones".hex(), default), selected)
        self.assertIs(resolve_audio_device([selected], "missing", default), default)

    def test_emoji_only_messages_are_recognized_as_compact_reactions(self):
        self.assertTrue(is_emoji_reaction("🎄"))
        self.assertTrue(is_emoji_reaction("👍 ❤️"))
        self.assertTrue(is_emoji_reaction("👨‍👩‍👧‍👦"))
        self.assertFalse(is_emoji_reaction("Ciao 👍"))
        self.assertFalse(is_emoji_reaction(""))

        window = KerberusWindow()
        window._build_ui()
        local_identity, _secrets = generate_identity("Edward")
        window.message_view.chat_delegate.configure(local_identity, None, None, None, False)
        geometry = window.message_view.chat_delegate._layout(
            {"text": "👍", "direction": "out", "sent_at": 1_700_000_000, "status": "read",
             "reactions": {"peer": "❤️"}},
            820, window.font(),
        )
        self.assertTrue(geometry["emoji_reaction"])
        self.assertLess(geometry["bubble_width"], 180)
        self.assertEqual(geometry["reactions"], ("❤️",))
        window.service.close()

    def test_multiple_reactions_render_as_clickable_owned_chips(self):
        view = VirtualChatView()
        view.resize(760, 260)
        local, _local_secrets = generate_identity("Alice")
        remote, _remote_secrets = generate_identity("Bob")
        view.configure(local, remote, None, None, False)
        message = {
            "message_id": "a" * 32,
            "direction": "out",
            "text": "Più reazioni",
            "sent_at": 1_700_000_000,
            "status": "delivered",
            "reactions": {
                local.identity_id: ["👍", "❤️"],
                remote.identity_id: ["👍"],
            },
        }
        actions = []
        view.on_action = lambda action, selected: actions.append((action, selected["message_id"]))
        view.sync_messages([message])
        view.show()
        self.app.processEvents()
        index = view.chat_model.index(0, 0)
        regions = view.chat_delegate.reaction_regions(
            message, view.visualRect(index), view.font()
        )
        self.assertEqual([(emoji, len(owners)) for emoji, owners, _rect in regions], [("👍", 2), ("❤️", 1)])
        geometry = view.chat_delegate._layout(message, view.width(), view.font())
        chip_texts = [chip[2] for row in geometry["reaction_rows"] for chip in row]
        self.assertEqual(chip_texts, ["👍 2", "❤️ 1"])
        bubble = view.chat_delegate._bubble_rect(view.visualRect(index), geometry)
        self.assertTrue(all(rect.top() > bubble.bottom() for _emoji, _owners, rect in regions))
        self.assertEqual(regions[-1][2].right(), bubble.right())
        incoming = dict(message, direction="in")
        incoming_geometry = view.chat_delegate._layout(incoming, view.visualRect(index).width(), view.font())
        incoming_bubble = view.chat_delegate._bubble_rect(view.visualRect(index), incoming_geometry)
        incoming_regions = view.chat_delegate.reaction_regions(
            incoming, view.visualRect(index), view.font()
        )
        self.assertEqual(incoming_regions[0][2].left(), incoming_bubble.left())
        heart = next(rect for emoji, _owners, rect in regions if emoji == "❤️")
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=heart.center())
        self.assertEqual(actions, [("react:❤️", "a" * 32)])
        view.close()

    def test_virtual_link_previews_only_exist_for_messages_with_urls(self):
        window = KerberusWindow()
        window._build_ui()
        delegate = window.message_view.chat_delegate
        preview_image = QImage(320, 180, QImage.Format.Format_RGB32)
        preview_image.fill(Qt.GlobalColor.darkCyan)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(preview_image.save(buffer, "PNG"))
        url = "https://example.com/article"
        cache = {url: {
            "url": url, "site": "Example", "title": "Titolo moderno",
            "author": "Autore", "description": "Descrizione completa dell'anteprima.",
            "image": bytes(buffer.data()),
        }}
        delegate.configure(None, None, None, None, True, cache, Mock())
        plain = delegate._layout({"text": "Messaggio senza collegamenti", "direction": "in"}, 820, window.font())
        linked = delegate._layout({"text": f"Leggi {url}", "direction": "in"}, 820, window.font())
        self.assertEqual(plain["link"], "")
        self.assertIsNone(plain["preview_geometry"])
        self.assertEqual(plain["link_height"], 0)
        self.assertEqual(linked["link"], url)
        self.assertEqual(linked["preview_geometry"]["state"], "ready")
        self.assertGreater(linked["preview_geometry"]["image_height"], 0)
        self.assertGreater(linked["link_height"], 100)
        window.service.close()

    def test_links_in_virtual_messages_are_clickable_with_or_without_previews(self):
        window = KerberusWindow()
        window._build_ui()
        view = window.message_view
        message = {
            "message_id": "a" * 32, "direction": "in", "sent_at": 1_700_000_000,
            "text": "Uno https://example.com/a e due http://example.org/b",
        }
        view.configure(None, None, None, None, False)
        view.chat_model.set_messages([message])
        view.resize(820, 220)
        view.show()
        self.app.processEvents()
        row_rect = view.visualRect(view.chat_model.index(0, 0))
        regions = view.chat_delegate.link_regions(message, row_rect, view.font())
        self.assertEqual({url for url, _rect in regions}, {
            "https://example.com/a", "http://example.org/b",
        })
        opened = Mock()
        view.on_open_link = opened
        first_url, first_rect = regions[0]
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first_rect.center().toPoint())
        opened.assert_called_once_with(first_url)

        view.configure(None, None, None, None, True, {
            "https://example.com/a": {
                "url": "https://example.com/a", "site": "Example",
                "title": "Anteprima cliccabile", "description": "Descrizione", "image": b"",
            },
        }, Mock())
        self.app.processEvents()
        row_rect = view.visualRect(view.chat_model.index(0, 0))
        preview_regions = view.chat_delegate.link_regions(message, row_rect, view.font())
        preview_region = max(
            (rect for url, rect in preview_regions if url == "https://example.com/a"),
            key=lambda rect: rect.height(),
        )
        opened.reset_mock()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=preview_region.center().toPoint())
        opened.assert_called_once_with("https://example.com/a")
        window.service.close()

    def test_external_links_require_confirmation_before_browser(self):
        url = "https://example.com/path?source=kerberus"
        with (
            patch.object(ExternalLinkDialog, "confirm", return_value=False) as confirm,
            patch("kerberus.ui.QDesktopServices.openUrl") as browser,
        ):
            self.assertFalse(open_external_link(None, url))
            confirm.assert_called_once_with(None, url)
            browser.assert_not_called()
        with (
            patch.object(ExternalLinkDialog, "confirm", return_value=True),
            patch("kerberus.ui.QDesktopServices.openUrl", return_value=True) as browser,
        ):
            self.assertTrue(open_external_link(None, url))
            self.assertEqual(browser.call_args.args[0].toString(), url)

        dialog = ExternalLinkDialog(url)
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        self.assertIn("example.com", labels)
        self.assertIn("Stai per lasciare Kerberus", labels)
        self.assertEqual(dialog.url_field.text(), url)
        dialog.close()

        set_language("en")
        try:
            dialog = ExternalLinkDialog(url)
            localize_widget(dialog)
            texts = [label.text() for label in dialog.findChildren(QLabel)]
            texts.extend(button.text() for button in dialog.findChildren(QPushButton))
            self.assertIn("You are about to leave Kerberus", texts)
            self.assertIn("Open in browser", texts)
            dialog.close()
        finally:
            set_language("it")

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
        emoji_button = window.emoji_button
        self.assertEqual(emoji_button.text(), "")
        self.assertFalse(emoji_button.icon().isNull())
        self.assertEqual(emoji_button.iconSize().width(), 22)
        author, _secrets = generate_identity("Alice")
        bubble = MessageBubble("x", 1_700_000_000, False, on_action=lambda *_args: None, author=author)
        self.assertFalse(any(button.text() == "☺+" for button in bubble.findChildren(QToolButton)))
        labels = [label.text() for label in bubble.findChildren(QLabel)]
        self.assertIn("Alice", labels)
        self.assertTrue(any(label.pixmap() and not label.pixmap().isNull() for label in bubble.findChildren(QLabel)))
        window.service.close()

    def test_composer_emoji_picker_is_embedded_and_stays_open(self):
        window = KerberusWindow()
        window._build_ui()
        self.assertIsInstance(window.emoji_panel, EmojiPanel)
        self.assertTrue(window.emoji_panel.isHidden())
        with patch("kerberus.ui.EmojiPicker.exec") as popup:
            window.show_emoji_menu()
        popup.assert_not_called()
        self.assertFalse(window.emoji_panel.isHidden())
        self.assertEqual(window.emoji_panel.panel_title.text(), "Emoji e simboli")
        self.assertIn("QFrame#emojiCategories", STYLE)
        self.assertIn("QToolButton#emojiPager", STYLE)
        window.emoji_panel._select("🔥")
        window.emoji_panel._select("❤️")
        self.assertEqual(window.composer.toPlainText(), "🔥❤️")
        self.assertFalse(window.emoji_panel.isHidden())
        self.assertEqual(window.emoji_panel._recent[:2], ["❤️", "🔥"])
        close = next(
            button for button in window.emoji_panel.findChildren(QToolButton)
            if button.toolTip() == "Chiudi pannello emoji"
        )
        close.click()
        self.assertTrue(window.emoji_panel.isHidden())
        window.show_emoji_menu()
        self.assertFalse(window.emoji_panel.isHidden())
        window.show_emoji_menu()
        self.assertTrue(window.emoji_panel.isHidden())
        window.service.close()

    def test_emoji_footer_stays_below_the_scrollable_grid(self):
        panel = EmojiPanel()
        panel.resize(860, 440)
        panel.show()
        self.app.processEvents()
        scroll = panel.findChild(QScrollArea, "emojiScroll")
        footer = panel.findChild(QFrame, "emojiFooter")
        self.assertIsNotNone(scroll)
        self.assertIsNotNone(footer)
        scroll_bottom = scroll.mapTo(panel, scroll.rect().bottomLeft()).y()
        footer_top = footer.mapTo(panel, footer.rect().topLeft()).y()
        self.assertGreater(footer_top, scroll_bottom)
        self.assertEqual(footer.height(), 40)
        self.assertIn("QFrame#emojiFooter", STYLE)
        panel.close()

    def test_contact_profile_can_be_opened_from_chat_header(self):
        window = KerberusWindow()
        window._build_ui()
        contact, _secrets = generate_identity("Bob")
        window.service.contacts = lambda: [contact]
        window.selected_contact = contact.identity_id
        open_dialogs = len(window._open_dialogs)
        window.show_contact_profile()
        self.assertTrue(window._contact_profile_panel_open)
        self.assertFalse(window.contact_profile_panel.isHidden())
        self.assertEqual(len(window._open_dialogs), open_dialogs)
        self.assertEqual(window.contact_profile_panel.name.text(), "Bob")
        profile_buttons = [
            button for button in window.findChildren(QToolButton)
            if button.toolTip() == "Apri profilo"
        ]
        self.assertTrue(profile_buttons)
        window.service.close()

    def test_contact_can_hide_identity_id_from_profile_ui(self):
        window = KerberusWindow()
        window._build_ui()
        contact, _secrets = generate_identity("Bob")
        window.service.contacts = lambda: [contact]
        window.service.chat_settings = lambda _contact: {"remote_identity_id_visible": False}
        window.selected_contact = contact.identity_id
        window.show_contact_profile()
        self.assertTrue(window.contact_profile_panel.identity_field.isHidden())
        self.assertFalse(window.contact_profile_panel.hidden_identity.isHidden())
        self.assertNotEqual(window.contact_profile_panel.identity_field.text(), contact.identity_id)
        window.service.close()

    def test_chat_settings_are_an_internal_toggleable_panel(self):
        window = KerberusWindow()
        window._build_ui()
        contact, _secrets = generate_identity("Bob")
        window.service.contacts = lambda: [contact]
        window.selected_contact = contact.identity_id
        open_dialogs = len(window._open_dialogs)
        window.show_chat_settings()
        self.assertTrue(window._chat_settings_panel_open)
        self.assertFalse(window.chat_settings_panel.isHidden())
        self.assertEqual(len(window._open_dialogs), open_dialogs)
        self.assertEqual(window.chat_settings_panel.contact_name.text(), "Bob")
        window.show_chat_settings()
        self.assertFalse(window._chat_settings_panel_open)
        self.assertTrue(window.chat_settings_panel.isHidden())
        window.service.close()

    def test_contact_profile_and_chat_settings_share_one_internal_drawer(self):
        window = KerberusWindow()
        window._build_ui()
        contact, _secrets = generate_identity("Bob")
        window.service.contacts = lambda: [contact]
        window.selected_contact = contact.identity_id
        window.show_contact_profile()
        self.assertIs(window.chat_side_panel.currentWidget(), window.contact_profile_panel)
        window.show_chat_settings()
        self.assertFalse(window._contact_profile_panel_open)
        self.assertTrue(window._chat_settings_panel_open)
        self.assertIs(window.chat_side_panel.currentWidget(), window.chat_settings_panel)
        window.service.close()

    def test_chat_settings_panel_is_localized_in_english(self):
        set_language("en")
        try:
            window = KerberusWindow()
            window._build_ui()
            localize_widget(window)
            contact, _secrets = generate_identity("Bob")
            window.service.contacts = lambda: [contact]
            window.selected_contact = contact.identity_id
            window.show_chat_settings()
            labels = [label.text() for label in window.chat_settings_panel.findChildren(QLabel)]
            self.assertIn("Chat settings", labels)
            self.assertIn("Show my Identity ID", labels)
            self.assertNotIn("Impostazioni chat", labels)
            window.service.close()
        finally:
            set_language("it")

    def test_full_reaction_picker_reuses_embedded_panel(self):
        window = KerberusWindow()
        window._build_ui()
        message = {"message_id": "1" * 32, "text": "Ciao"}
        with patch("kerberus.ui.EmojiPicker.exec") as popup:
            window.message_action("reaction_picker", message)
        popup.assert_not_called()
        self.assertTrue(window._emoji_panel_open)
        self.assertTrue(window.emoji_panel._reaction_mode)
        self.assertEqual(window.emoji_panel.panel_title.text(), "Reazioni al messaggio")
        self.assertIs(window._emoji_reaction_message, message)
        window.service.close()

    def test_message_timing_dialog_is_compact_and_scrollable(self):
        window = KerberusWindow()
        window._build_ui()
        window.show_message_timing({
            "kind": "voice",
            "direction": "out",
            "sent_at": 1_700_000_000,
            "voice": {"duration_ms": 2_300, "codec": "kerberus-ima-adpcm-v1"},
            "voice_metrics": {"encode_ms": 39.48, "decode_ms": 28.085},
            "transport_metrics": {
                "python_helper_ipc_overhead_ms": 0.853,
                "python_helper_roundtrip_ms": 0.853,
                "queue_wait_ms": None,
                "sam_handshake_ms": None,
                "sam_connect_command_ms": None,
            },
        })
        self.app.processEvents()
        dialog = next(iter(window._open_dialogs))
        scroll = dialog.findChild(QScrollArea, "timingScroll")
        self.assertIsNotNone(scroll)
        self.assertLessEqual(dialog.height(), 640)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        rows = dialog.findChildren(QFrame, "timingRow")
        self.assertGreaterEqual(len(rows), 10)
        # Text scaling may legitimately grow a wrapped diagnostics row while
        # it must remain compact enough to keep several entries visible.
        self.assertTrue(all(row.height() <= 72 for row in rows))
        dialog.close()
        window.service.close()

    def test_settings_rework_has_organized_icon_navigation_and_switches(self):
        window = KerberusWindow()
        window._build_ui()
        window.show_settings()
        self.app.processEvents()
        dialog = next(iter(window._open_dialogs))
        navigation = [
            button for button in dialog.findChildren(QPushButton)
            if button.objectName() == "settingsNav"
        ]
        self.assertEqual([button.text() for button in navigation], [
            "Generali", "Aspetto", "Privacy", "Rete", "Sicurezza", "Diagnostica",
        ])
        self.assertTrue(all(not button.icon().isNull() for button in navigation))
        self.assertGreaterEqual(len(dialog.findChildren(ToggleSwitch)), 6)
        navigation[4].click()
        self.app.processEvents()
        stream_switch = next(switch for switch in dialog.findChildren(ToggleSwitch) if switch.isVisible())
        switch_position = stream_switch.mapTo(dialog, stream_switch.rect().topLeft())
        self.assertLessEqual(switch_position.x() + stream_switch.width(), dialog.width())
        dialog.close()
        window.service.close()

    def test_appearance_page_previews_all_themes_text_scale_and_density(self):
        previous_style = self.app.styleSheet()
        window = KerberusWindow()
        window._build_ui()
        window.show_settings()
        self.app.processEvents()
        dialog = next(iter(window._open_dialogs))
        navigation = [
            button for button in dialog.findChildren(QPushButton)
            if button.objectName() == "settingsNav"
        ]
        navigation[1].click()
        theme = dialog.findChild(ModernComboBox, "applicationTheme")
        text_scale = dialog.findChild(ModernComboBox, "textScale")
        density = dialog.findChild(ModernComboBox, "uiDensity")
        self.assertEqual([theme.itemData(index) for index in range(theme.count())], [
            "default", "pink", "orange", "white", "dark",
        ])
        self.assertEqual([text_scale.itemData(index) for index in range(text_scale.count())], [90, 100, 110, 120])
        self.assertEqual([density.itemData(index) for index in range(density.count())], [
            "compact", "comfortable", "spacious",
        ])
        white_swatch = dialog.findChild(QFrame, "themeSwatch-white")
        self.assertIn("background: #ffffff", white_swatch.styleSheet())
        self.assertNotIn("#16865f", white_swatch.styleSheet())
        theme.setCurrentIndex(1)
        text_scale.setCurrentIndex(2)
        density.setCurrentIndex(0)
        self.app.processEvents()
        self.assertIn("#f472b6", self.app.styleSheet())
        self.assertIn("font-size: 15px", self.app.styleSheet())
        dialog.reject()
        self.app.processEvents()
        self.assertIn("#35d09a", self.app.styleSheet())
        self.app.setStyleSheet(previous_style)
        window.service.close()

    def test_rebuilding_ui_for_theme_preserves_connected_i2p_indicator(self):
        window = KerberusWindow()
        window._router_connected = True
        window._router_detail = "I2P: connesso"

        window._build_ui()

        self.assertEqual(window.router_text.text(), "I2P: connesso")
        self.assertEqual(window.router_meta.text(), "Tunnel pronto · SAM locale")
        self.assertEqual(window.router_text.toolTip(), "I2P: connesso")
        window.service.close()

    def test_audio_settings_list_devices_and_route_tests_to_selected_output(self):
        class Device:
            def __init__(self, identifier: bytes, description: str):
                self._identifier = identifier
                self._description = description

            def id(self):
                return self._identifier

            def description(self):
                return self._description

        microphone = Device(b"usb-microphone", "Microfono USB")
        headphones = Device(b"usb-headphones", "Cuffie USB")
        window = KerberusWindow()
        window._build_ui()
        with (
            patch("kerberus.ui.available_audio_inputs", return_value=[microphone]),
            patch("kerberus.ui.available_audio_outputs", return_value=[headphones]),
            patch.object(window, "_play_voice_wav") as play,
        ):
            window.show_settings()
            self.app.processEvents()
            dialog = next(iter(window._open_dialogs))
            audio_input = dialog.findChild(ModernComboBox, "audioInputDevice")
            audio_output = dialog.findChild(ModernComboBox, "audioOutputDevice")
            self.assertEqual(audio_input.itemText(1), "Microfono USB")
            self.assertEqual(audio_output.itemText(1), "Cuffie USB")
            audio_output.setCurrentIndex(1)
            dialog.findChild(QPushButton, "audioOutputTest").click()
            self.app.processEvents()
            self.assertEqual(play.call_args.args[0][:4], b"RIFF")
            self.assertEqual(play.call_args.args[1], b"usb-headphones".hex())
            self.assertFalse(dialog.findChild(QPushButton, "audioInputTest").icon().isNull())
            dialog.close()
        window.service.close()

    def test_network_settings_include_private_per_ip_insights(self):
        window = KerberusWindow()
        window._build_ui()
        window.show_settings()
        self.app.processEvents()
        dialog = next(iter(window._open_dialogs))
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        self.assertIn("Paesi e peer I2P", labels)
        self.assertNotIn("GRATIS · NESSUNA CHIAVE API", labels)
        panel = dialog.findChild(NetworkInsightsPanel)
        self.assertIsNotNone(panel)
        panel.set_peers([{"ip": "8.8.8.8", "port": 443}])
        self.assertFalse(panel.peer_host.isHidden())
        panel.disclosure.click()
        self.assertTrue(panel.peer_host.isHidden())
        panel.disclosure.click()
        self.assertFalse(panel.peer_host.isHidden())
        self.assertIn("chevron-down.svg", STYLE)
        self.assertIn("QMenu::item:selected", STYLE)
        dialog.close()
        window.service.close()

    def test_low_latency_requires_non_movable_inline_confirmation(self):
        window = KerberusWindow()
        window._build_ui()
        window.show_settings()
        self.app.processEvents()
        dialog = next(iter(window._open_dialogs))
        navigation = [
            button for button in dialog.findChildren(QPushButton)
            if button.objectName() == "settingsNav"
        ]
        navigation[3].click()
        self.app.processEvents()
        row = dialog.findChild(SettingsToggleRow, "lowLatencySetting")
        switch = row.findChild(ToggleSwitch)
        confirmation = dialog.findChild(InlineConfirmationPanel)
        self.assertIsNotNone(confirmation)
        self.assertFalse(confirmation.isWindow())
        self.assertFalse(switch.isChecked())
        switch.click()
        self.app.processEvents()
        self.assertFalse(switch.isChecked())
        self.assertTrue(confirmation.isVisible())
        confirm = confirmation.findChild(QPushButton, "confirmLowLatency")
        confirm.click()
        self.app.processEvents()
        self.assertTrue(switch.isChecked())
        self.assertFalse(confirmation.isVisible())
        dialog.close()
        window.service.close()

    def test_network_insights_refresh_and_ip_details_are_automatic(self):
        peers = [{"ip": "8.8.8.8", "port": 443}]
        details = {"country": "United States", "country_code": "US", "as_name": "Google"}
        with (
            patch("kerberus.ui.collect_i2p_peer_connections", return_value=peers) as collect,
            patch("kerberus.ui.lookup_ip_geolocation", return_value=details) as lookup,
        ):
            window = KerberusWindow()
            window._build_ui()
            window.show_settings()
            QTest.qWait(250)
            self.app.processEvents()
            dialog = next(iter(window._open_dialogs))
            panel = dialog.findChild(NetworkInsightsPanel)
            collect.assert_called()
            # A lookup started by a previous modeless settings dialog may
            # complete while this patch is active; require the expected call
            # without assuming it is globally the last background lookup.
            lookup.assert_any_call("8.8.8.8")
            self.assertIn("Google", panel._detail_labels["8.8.8.8"].text())
            self.assertTrue(panel.auto_refresh.isActive())
            dialog.close()
            window.service.close()

    def test_closed_dropdown_ignores_mouse_wheel_and_has_roomy_popup(self):
        combo = ModernComboBox()
        combo.addItems(["Prima scelta", "Una seconda scelta molto più lunga"])
        combo.setCurrentIndex(0)
        event = Mock(spec=QWheelEvent)
        combo.wheelEvent(event)
        event.ignore.assert_called_once()
        self.assertEqual(combo.currentIndex(), 0)
        self.assertGreaterEqual(
            combo.itemDelegate().sizeHint(QStyleOptionViewItem(), combo.model().index(0, 0)).height(), 40
        )
        combo.close()

    def test_modern_dropdown_uses_compact_styled_popup_and_selection_check(self):
        combo = ModernComboBox()
        combo.addItems(["Automatico (disattivo)", "Attivo", "Disattivo"])
        combo.setCurrentIndex(1)
        combo.resize(280, 42)
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        popup = combo._popup
        self.assertIsNotNone(popup)
        self.assertTrue(popup.isVisible())
        self.assertFalse(combo.view().isVisible())
        self.assertEqual(len(popup.buttons), 3)
        self.assertLessEqual(popup.height(), 150)
        self.assertTrue(popup.buttons[1].property("selected"))
        self.assertFalse(popup.buttons[0].property("selected"))
        QTest.keyClick(popup.buttons[1], Qt.Key.Key_Down)
        self.assertIs(QApplication.focusWidget(), popup.buttons[2])
        popup.buttons[2].click()
        self.app.processEvents()
        self.assertEqual(combo.currentIndex(), 2)
        self.assertIn("QFrame#dropdownPopup", STYLE)
        combo.close()

    def test_new_settings_pages_are_fully_localized_in_english(self):
        set_language("en")
        try:
            window = KerberusWindow()
            window._build_ui()
            window.show_settings()
            self.app.processEvents()
            dialog = next(iter(window._open_dialogs))
            texts = [widget.text() for widget in dialog.findChildren(QLabel)]
            texts.extend(widget.text() for widget in dialog.findChildren(QPushButton))
            self.assertIn("General", texts)
            self.assertIn("Security", texts)
            self.assertIn("Streaming protection", texts)
            self.assertIn("Hide Kerberus during streaming and screen sharing", texts)
            self.assertIn("I2P countries and peers", texts)
            self.assertIn("Low-latency mode", texts)
            self.assertIn("Keep recent contacts ready", texts)
            self.assertTrue(any("Disable it for maximum privacy" in text for text in texts))
            self.assertIn("Mask which contacts are recent", texts)
            self.assertTrue(any("Does not spoof I2P" in text for text in texts))
            self.assertIn("Open UI console", texts)
            self.assertNotIn("Generali", texts)
            self.assertNotIn("Protezione streaming", texts)
            dialog.close()
            window.service.close()
        finally:
            set_language("it")

    def test_ui_console_translates_runtime_protocol_and_ack_details(self):
        set_language("en")
        try:
            window = KerberusWindow()
            window._build_ui()
            window._protocol_event(
                "message_stream_sent",
                "Frame scritto sullo stream in 0.42s; attendo conferma cifrata",
            )
            window._protocol_event("message_delivered", "Messaggio consegnato e confermato")
            window.show_ui_console()
            self.app.processEvents()
            dialog = next(iter(window._open_dialogs))
            console = dialog.findChild(QPlainTextEdit)
            contents = console.toPlainText()
            self.assertIn("Protocol event: message_stream_sent", contents)
            self.assertIn("Frame written to the stream in 0.42s; waiting for encrypted ACK", contents)
            self.assertIn("Protocol event: message_delivered · Message delivered and confirmed", contents)
            self.assertIn("Opening UI console", contents)
            self.assertNotIn("Frame scritto sullo stream", contents)
            self.assertEqual(dialog.windowTitle(), "UI console")
            self.assertEqual(window.statusBar().currentMessage(), "Message delivered and confirmed")
            dialog.close()
            window.service.close()
        finally:
            set_language("it")

    def test_stream_proof_setting_is_applied_to_main_window(self):
        window = KerberusWindow()
        window.service.vault.state["settings"]["stream_proof_enabled"] = True
        with patch("kerberus.ui.set_window_capture_exclusion", return_value=(True, "ok")) as protect:
            self.assertTrue(window._apply_stream_proof_setting())
        protect.assert_called_once_with(window, True)
        self.assertTrue(window._stream_proof_active)
        window._build_ui()
        with patch("kerberus.ui.set_window_capture_exclusion", return_value=(True, "ok")) as protect:
            window.show_ui_console()
            self.app.processEvents()
        self.assertTrue(any(isinstance(call.args[0], QDialog) for call in protect.call_args_list))
        for dialog in list(window._open_dialogs):
            dialog.close()
        window.service.close()

    def test_linux_stream_proof_uses_supported_privacy_curtain_mode(self):
        window = KerberusWindow()
        with patch("kerberus.ui.sys.platform", "linux"):
            success, detail = set_window_capture_exclusion(window, True)
        self.assertTrue(success)
        self.assertIn("Linux", detail)
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
        model = window.message_view.chat_model
        reset = QSignalSpy(model.modelReset)
        messages[0]["status"] = "delivered"
        window.refresh_messages("status", "peer")
        self.assertIs(window.message_view.chat_model, model)
        self.assertEqual(len(reset), 0)
        self.assertEqual(model.messages[0]["status"], "delivered")
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
        model = window.message_view.chat_model
        reset = QSignalSpy(model.modelReset)
        inserted = QSignalSpy(model.rowsInserted)
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
        self.assertIs(window.message_view.chat_model, model)
        self.assertEqual(len(reset), 0)
        self.assertEqual(len(inserted), 1)
        self.assertEqual(model.rowCount(), 2)
        window.service.close()

    def test_opening_large_chat_is_virtualized_and_does_not_warm_peer(self):
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
        self.assertEqual(window.message_view.chat_model.rowCount(), 500)
        self.assertFalse(window.message_view.findChildren(MessageBubble))
        window.service.warm_contact.assert_not_called()
        window.service.close()

    def test_full_history_has_stable_scrollbar_without_paginated_jumps(self):
        window = KerberusWindow()
        window._build_ui()
        contact, _secrets = generate_identity("Bob")
        window.service.contacts = lambda: [contact]
        messages = [{
            "message_id": f"{index:032x}", "contact_id": contact.identity_id,
            "text": f"Messaggio {index}", "time": 1_700_000_000 + index,
            "sent_at": 1_700_000_000 + index, "direction": "in", "status": "received",
        } for index in range(240)]
        window.service.messages_for = lambda _contact: messages
        window.service.mark_chat_read = Mock(return_value=0)
        window.show()
        window.select_contact(contact.identity_id)
        QTest.qWait(250)
        scrollbar = window.message_view.verticalScrollBar()
        maximum = scrollbar.maximum()
        self.assertGreater(maximum, 0)
        self.assertEqual(window.message_view.chat_model.rowCount(), 240)
        viewport = window.message_view.viewport()

        def visible_row() -> int:
            center = viewport.height() // 2
            for distance in range(0, 20):
                for y in (center + distance, center - distance):
                    index = window.message_view.indexAt(QPoint(viewport.width() // 2, y))
                    if index.isValid():
                        return index.row()
            return -1

        forward_rows = []
        positions = [0, maximum // 4, maximum // 2, maximum * 3 // 4, maximum]
        for position in positions:
            scrollbar.setValue(position)
            self.app.processEvents()
            self.assertEqual(scrollbar.value(), position)
            forward_rows.append(visible_row())
        self.assertTrue(all(left < right for left, right in zip(forward_rows, forward_rows[1:])))

        backward_rows = []
        for position in reversed(positions):
            scrollbar.setValue(position)
            self.app.processEvents()
            backward_rows.append(visible_row())
        self.assertTrue(all(left > right for left, right in zip(backward_rows, backward_rows[1:])))
        self.assertEqual(scrollbar.value(), 0)
        self.assertEqual(scrollbar.maximum(), maximum)
        scrollbar.setValue(maximum)
        self.assertEqual(scrollbar.value(), maximum)
        window.hide()
        window.service.close()

    def test_wheel_over_message_moves_immediately_in_both_directions(self):
        window = KerberusWindow()
        window._build_ui()
        contact, _secrets = generate_identity("Bob")
        window.service.contacts = lambda: [contact]
        messages = [{
            "message_id": f"{index:032x}", "contact_id": contact.identity_id,
            "text": (f"Messaggio lungo {index} ") * 4, "time": 1_700_000_000 + index,
            "sent_at": 1_700_000_000 + index, "direction": "in", "status": "received",
        } for index in range(120)]
        window.service.messages_for = lambda _contact: messages
        window.service.mark_chat_read = Mock(return_value=0)
        window.show()
        window.select_contact(contact.identity_id)
        QTest.qWait(450)
        scrollbar = window.message_scroll.verticalScrollBar()
        before = scrollbar.value()
        target = window.message_view.viewport()
        upward_values = []
        for _ in range(3):
            event = QWheelEvent(
                QPointF(4, 4), QPointF(4, 4), QPoint(), QPoint(0, 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate, False,
            )
            QApplication.sendEvent(target, event)
            upward_values.append(scrollbar.value())
        self.assertGreater(before, 0)
        self.assertTrue(all(left > right for left, right in zip([before, *upward_values], upward_values)))
        self.assertGreaterEqual(before - scrollbar.value(), 200)
        after_up = scrollbar.value()
        down_event = QWheelEvent(
            QPointF(4, 4), QPointF(4, 4), QPoint(), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate, False,
        )
        QApplication.sendEvent(target, down_event)
        self.assertGreater(scrollbar.value(), after_up)
        window.hide()
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
