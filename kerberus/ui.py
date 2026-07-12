from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from PyQt6.QtCore import QByteArray, QBuffer, QEvent, QIODevice, QObject, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QResizeEvent,
    QRegion,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig
from . import __version__
from .crypto import IdentityBundle, b64, destination_b32, pq_available, pq_unavailable_reason, unb64
from .router import I2P_VERSION, RouterInstaller
from .service import MessengerService
from .updates import UpdateInfo, check_for_update, download_update


COLORS = {
    "window": "#0c0f13",
    "sidebar": "#12161b",
    "surface": "#171c22",
    "surface_2": "#20262e",
    "surface_3": "#29313b",
    "border": "#2d3540",
    "text": "#f2f5f7",
    "muted": "#909aa6",
    "faint": "#626d79",
    "accent": "#35d09a",
    "accent_hover": "#50ddb0",
    "accent_dark": "#174d3b",
    "cyan": "#4dbbd5",
    "warning": "#f0b35a",
    "danger": "#ef6b73",
}

ICON_DIR = Path(__file__).resolve().parent / "assets" / "lucide"


def lucide_icon(name: str, color: str = "#aeb8c4", size: int = 24) -> QIcon:
    source = (ICON_DIR / f"{name}.svg").read_text("utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def avatar_pixmap(identity: IdentityBundle, size: int) -> QPixmap:
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    if identity.avatar_data:
        image = QImage.fromData(unb64(identity.avatar_data), "PNG")
        scaled = image.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - size) // 2)
        y = max(0, (scaled.height() - size) // 2)
        painter.drawImage(0, 0, scaled.copy(x, y, size, size))
    else:
        painter.fillPath(path, QColor(COLORS["accent_dark"]))
        painter.setPen(QColor(COLORS["accent"]))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(max(13, size // 2))
        painter.setFont(font)
        painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, identity.name[:1].upper() or "?")
    painter.end()
    return canvas


def set_avatar(label: QLabel, identity: IdentityBundle, size: int) -> None:
    label.setFixedSize(size, size)
    label.setPixmap(avatar_pixmap(identity, size))


STYLE = f"""
* {{
    font-family: "Segoe UI";
    font-size: 14px;
    color: {COLORS['text']};
}}
QMainWindow {{ background: transparent; }}
QDialog {{ background: transparent; }}
QFrame#appShell, QFrame#dialogShell {{ background: {COLORS['window']}; border: 1px solid {COLORS['border']}; border-radius: 12px; }}
QFrame#titlebar {{ background: {COLORS['sidebar']}; border-bottom: 1px solid {COLORS['border']}; }}
QFrame#sidebar {{ background: {COLORS['sidebar']}; border-right: 1px solid {COLORS['border']}; }}
QFrame#topbar {{ background: {COLORS['window']}; border-bottom: 1px solid {COLORS['border']}; }}
QFrame#composer {{ background: {COLORS['window']}; border-top: 1px solid {COLORS['border']}; }}
QLabel#brand {{ font-size: 20px; font-weight: 700; color: {COLORS['text']}; }}
QLabel#pageTitle {{ font-size: 18px; font-weight: 650; }}
QLabel#dialogTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#muted, QLabel#contactMeta, QLabel#timestamp {{ color: {COLORS['muted']}; }}
QLabel#eyebrow {{ color: {COLORS['accent']}; font-size: 12px; font-weight: 700; }}
QLineEdit, QPlainTextEdit {{
    background: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 7px;
    padding: 10px 12px;
    selection-background-color: {COLORS['accent_dark']};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {COLORS['accent']}; }}
QPushButton {{
    background: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 7px;
    padding: 9px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {COLORS['surface_3']}; border-color: #46515e; }}
QPushButton:pressed {{ background: #101419; }}
QPushButton#primary {{ background: {COLORS['accent']}; color: #07120e; border: 0; }}
QPushButton#primary:hover {{ background: {COLORS['accent_hover']}; }}
QPushButton#ghost {{ background: transparent; border: 0; color: {COLORS['muted']}; }}
QPushButton#ghost:hover {{ color: {COLORS['text']}; background: {COLORS['surface_2']}; }}
QToolButton {{
    background: transparent;
    border: 0;
    border-radius: 7px;
    padding: 8px;
}}
QToolButton:hover {{ background: {COLORS['surface_2']}; }}
QToolButton#sendButton {{ background: {COLORS['accent']}; color: #07120e; }}
QToolButton#sendButton:hover {{ background: {COLORS['accent_hover']}; }}
QToolButton#timingButton {{ padding: 1px; border-radius: 4px; }}
QToolButton#windowButton {{ border-radius: 0; padding: 0; }}
QToolButton#windowButton:hover {{ background: {COLORS['surface_3']}; }}
QToolButton#closeButton {{ border-radius: 0; padding: 0; }}
QToolButton#closeButton:hover {{ background: {COLORS['danger']}; }}
QListWidget {{ background: transparent; border: 0; outline: 0; padding: 0; }}
QListWidget::item {{ border: 0; padding: 0; }}
QListWidget::item:selected {{ background: {COLORS['surface_2']}; border-radius: 6px; }}
QListWidget::item:hover:!selected {{ background: #181e24; border-radius: 6px; }}
QScrollArea {{ background: transparent; border: 0; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 1px 2px 1px 0; }}
QScrollBar::handle:vertical {{ background: #3a434e; border-radius: 4px; min-height: 32px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QProgressBar {{ background: {COLORS['surface_2']}; border: 0; border-radius: 5px; min-height: 10px; }}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 5px; }}
QComboBox {{ background: {COLORS['surface_2']}; border: 1px solid {COLORS['border']}; border-radius: 7px; padding: 9px 12px; }}
QCheckBox {{ spacing: 9px; }}
"""


class AppSignals(QObject):
    message_received = pyqtSignal(str, str)
    contacts_changed = pyqtSignal(str)
    protocol_event = pyqtSignal(str, str)
    router_changed = pyqtSignal(bool, str)
    task_done = pyqtSignal(object)
    task_error = pyqtSignal(str)
    download_progress = pyqtSignal(int, int)


class DialogTitleBar(QFrame):
    def __init__(self, dialog: QDialog, title: str):
        super().__init__(dialog)
        self.dialog = dialog
        self.setObjectName("titlebar")
        self.setFixedHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        mark = QLabel("K")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(24, 24)
        mark.setStyleSheet(f"background: {COLORS['accent_dark']}; color: {COLORS['accent']}; border-radius: 5px; font-weight: 800;")
        caption = QLabel(title)
        caption.setStyleSheet("font-weight: 650;")
        close = QToolButton()
        close.setObjectName("closeButton")
        close.setIcon(lucide_icon("x"))
        close.setIconSize(QSize(14, 14))
        close.setFixedSize(46, 41)
        close.setToolTip("Chiudi")
        close.clicked.connect(dialog.reject)
        layout.addWidget(mark)
        layout.addSpacing(8)
        layout.addWidget(caption)
        layout.addStretch()
        layout.addWidget(close)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.dialog.windowHandle():
            self.dialog.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)


class KerberusDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None, width: int = 520):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(width)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        shell = QFrame()
        shell.setObjectName("dialogShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(DialogTitleBar(self, title))
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(28, 26, 28, 26)
        self.body_layout.setSpacing(12)
        shell_layout.addWidget(body)
        root.addWidget(shell)

    def resizeEvent(self, event: QResizeEvent) -> None:
        path = QPainterPath()
        path.addRoundedRect(8, 8, max(0, self.width() - 16), max(0, self.height() - 16), 12, 12)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)


class KerberusMessageDialog(KerberusDialog):
    def __init__(self, title: str, message: str, parent: QWidget | None = None, confirm: bool = False):
        super().__init__(title, parent, 500)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(lucide_icon("info", COLORS["accent"], 28).pixmap(28, 28))
        text = QLabel(message)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        row.addWidget(text, 1)
        self.body_layout.addLayout(row)
        actions = QHBoxLayout()
        actions.addStretch()
        if confirm:
            cancel = QPushButton("Annulla")
            cancel.setObjectName("ghost")
            cancel.clicked.connect(self.reject)
            actions.addWidget(cancel)
        accept = QPushButton("Continua" if confirm else "Chiudi")
        accept.setObjectName("primary")
        accept.clicked.connect(self.accept)
        actions.addWidget(accept)
        self.body_layout.addLayout(actions)

    @classmethod
    def show_message(cls, parent: QWidget | None, title: str, message: str) -> None:
        cls(title, message, parent).exec()

    @classmethod
    def ask(cls, parent: QWidget | None, title: str, message: str) -> bool:
        return cls(title, message, parent, confirm=True).exec() == QDialog.DialogCode.Accepted


class KerberusProgressDialog(KerberusDialog):
    def __init__(self, title: str, message: str, parent: QWidget | None = None):
        super().__init__(title, parent, 500)
        label = QLabel(message)
        label.setObjectName("muted")
        self.body_layout.addWidget(label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.body_layout.addWidget(self.progress)

    def setMaximum(self, maximum: int) -> None:
        self.progress.setMaximum(maximum)

    def setValue(self, value: int) -> None:
        self.progress.setValue(value)


class PasswordDialog(KerberusDialog):
    def __init__(self, create: bool, parent: QWidget | None = None):
        super().__init__("Crea vault" if create else "Sblocca Kerberus", parent, 440)
        layout = self.body_layout
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("Proteggi il tuo spazio" if create else "Bentornato")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        subtitle = QLabel("Crea una password locale" if create else "Inserisci la password del vault")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password")
        layout.addWidget(self.password)
        self.confirm = None
        if create:
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm.setPlaceholderText("Ripeti password")
            layout.addWidget(self.confirm)
        layout.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Crea vault" if create else "Sblocca")
        submit.setObjectName("primary")
        submit.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(submit)
        layout.addLayout(buttons)
        self.password.returnPressed.connect(self._submit)
        if self.confirm:
            self.confirm.returnPressed.connect(self._submit)

    def _submit(self) -> None:
        if self.confirm is not None and self.password.text() != self.confirm.text():
            KerberusMessageDialog.show_message(self, "Vault", "Le password non coincidono.")
            return
        self.accept()


class ContactDialog(KerberusDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("Nuovo contatto", parent, 600)
        layout = self.body_layout
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(12)
        eyebrow = QLabel("CONNESSIONE PRIVATA")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("Aggiungi un contatto")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        layout.addSpacing(8)
        self.code = QLineEdit()
        self.code.setPlaceholderText("XXXX-KERBERUS-...")
        self.code.setClearButtonEnabled(True)
        layout.addWidget(self.code)
        self.first_message = QPlainTextEdit()
        self.first_message.setPlaceholderText("Primo messaggio (opzionale)")
        self.first_message.setFixedHeight(88)
        layout.addWidget(self.first_message)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Invia richiesta")
        submit.setObjectName("primary")
        submit.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(submit)
        layout.addLayout(buttons)
        self.code.setFocus()


class ComposerEdit(QPlainTextEdit):
    send_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class ContactRow(QWidget):
    def __init__(self, contact: IdentityBundle, last_message: str = ""):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(11)
        avatar = QLabel()
        set_avatar(avatar, contact, 40)
        layout.addWidget(avatar)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(contact.name)
        name.setStyleSheet("font-weight: 650;")
        preview = QLabel(last_message or contact.identity_id[:18])
        preview.setObjectName("contactMeta")
        preview.setMaximumWidth(185)
        text.addWidget(name)
        text.addWidget(preview)
        layout.addLayout(text, 1)


class PendingContactRow(QWidget):
    def __init__(self, pending: dict, on_cancel: Callable[[str], None]):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(11)
        mark = QLabel("…")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(40, 40)
        mark.setStyleSheet(
            f"background: {COLORS['surface_2']}; color: {COLORS['warning']}; "
            "border-radius: 20px; font-size: 18px; font-weight: 700;"
        )
        layout.addWidget(mark)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel("Richiesta in attesa")
        title.setStyleSheet("font-weight: 650;")
        attempts = int(pending.get("attempts", 0))
        meta = QLabel(f"Conferma non ancora ricevuta · tentativi {attempts}")
        meta.setObjectName("contactMeta")
        text.addWidget(title)
        text.addWidget(meta)
        layout.addLayout(text, 1)
        cancel = QToolButton()
        cancel.setIcon(lucide_icon("x", COLORS["danger"], 16))
        cancel.setToolTip("Annulla richiesta")
        destination = str(pending.get("destination", ""))
        cancel.clicked.connect(lambda: on_cancel(destination))
        layout.addWidget(cancel)
        self.setToolTip("La chat sarà disponibile dopo la conferma firmata dell’altro dispositivo")


class MessageBubble(QWidget):
    def __init__(
        self,
        text: str,
        timestamp: int,
        outgoing: bool,
        status: str = "",
        timing: dict | None = None,
        on_timing: Callable[[dict], None] | None = None,
        on_action: Callable[[str, dict], None] | None = None,
        link_preview: bool = False,
    ):
        super().__init__()
        self.message = timing or {"text": text, "status": status}
        self.outgoing = outgoing
        self.on_action = on_action
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 4, 20, 4)
        if outgoing:
            outer.addStretch(1)
        bubble = QFrame()
        bubble.setMaximumWidth(560)
        color = COLORS["accent_dark"] if outgoing else COLORS["surface_2"]
        border = "transparent" if outgoing else COLORS["border"]
        bubble.setStyleSheet(f"QFrame {{ background: {color}; border: 1px solid {border}; border-radius: 8px; }}")
        content = QVBoxLayout(bubble)
        content.setContentsMargins(13, 10, 13, 8)
        content.setSpacing(5)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet("border: 0; background: transparent;")
        content.addWidget(body)
        if link_preview:
            match = re.search(r"https?://[^\s<>]+", text)
            if match:
                url = match.group(0).rstrip(".,;:!?)")
                parsed = urlsplit(url)
                preview = QLabel(f"🔗  {parsed.hostname or 'Link'}\n{url}")
                preview.setWordWrap(True)
                preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                preview.setToolTip("Anteprima locale: Kerberus non ha contattato il sito")
                preview.setStyleSheet(
                    f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
                    f"background: {COLORS['surface']}; padding: 8px; color: {COLORS['muted']};"
                )
                content.addWidget(preview)
        self._timestamp = timestamp
        self.time_label = QLabel()
        self.time_label.setObjectName("timestamp")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.time_label.setStyleSheet("border: 0; background: transparent; font-size: 11px;")
        metadata = QHBoxLayout()
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(4)
        metadata.addStretch()
        metadata.addWidget(self.time_label)
        timing_button = QToolButton()
        timing_button.setObjectName("timingButton")
        timing_button.setIcon(lucide_icon("clock", COLORS["muted"], 13))
        timing_button.setIconSize(QSize(13, 13))
        timing_button.setFixedSize(20, 20)
        timing_button.setToolTip("Dettagli di invio e ritardo")
        if timing is not None and on_timing is not None:
            timing_button.clicked.connect(lambda: on_timing(timing))
        else:
            timing_button.setEnabled(False)
        metadata.addWidget(timing_button)
        content.addLayout(metadata)
        self.reactions_label = QLabel()
        self.reactions_label.setStyleSheet("border: 0; background: transparent; font-size: 14px;")
        content.addWidget(self.reactions_label, alignment=Qt.AlignmentFlag.AlignRight)
        self.update_message(self.message)
        outer.addWidget(bubble)
        if not outgoing:
            outer.addStretch(1)

    def _show_context_menu(self, position: QPoint) -> None:
        if self.on_action is None:
            return
        menu = QMenu(self)
        reaction_menu = menu.addMenu("Reagisci")
        reaction_actions = {reaction_menu.addAction(emoji): emoji for emoji in ("👍", "❤️", "😂", "😮", "😢", "🔥")}
        copy_action = menu.addAction("Copia")
        forward_action = menu.addAction("Inoltra…")
        menu.addSeparator()
        delete_action = menu.addAction("Elimina da questo dispositivo")
        selected = menu.exec(self.mapToGlobal(position))
        if selected in reaction_actions:
            self.on_action("react:" + reaction_actions[selected], self.message)
        elif selected is copy_action:
            self.on_action("copy", self.message)
        elif selected is forward_action:
            self.on_action("forward", self.message)
        elif selected is delete_action:
            self.on_action("delete", self.message)

    def update_message(self, message: dict) -> None:
        self.message = message
        status = str(message.get("status", ""))
        time_text = datetime.fromtimestamp(self._timestamp).strftime("%H:%M")
        if self.outgoing:
            marks = {
                "pending": ("◷ In attesa", COLORS["muted"]),
                "sent": ("✓ Inviato", COLORS["muted"]),
                "delivered": ("✓✓ Consegnato", COLORS["muted"]),
                "read": ("✓✓ Letto", COLORS["cyan"]),
            }
            mark, color = marks.get(status, ("✓", COLORS["muted"]))
            time_text += f"  {mark}"
            self.time_label.setStyleSheet(f"border: 0; background: transparent; font-size: 11px; color: {color};")
        self.time_label.setText(time_text)
        reactions = message.get("reactions", {})
        values = list(reactions.values()) if isinstance(reactions, dict) else []
        self.reactions_label.setText(" ".join(values))
        self.reactions_label.setVisible(bool(values))


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class TitleBar(QFrame):
    def __init__(self, window: "KerberusWindow"):
        super().__init__(window)
        self.window = window
        self.setObjectName("titlebar")
        self.setFixedHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(8)
        mark = QLabel("K")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(24, 24)
        mark.setStyleSheet(f"background: {COLORS['accent_dark']}; color: {COLORS['accent']}; border-radius: 5px; font-weight: 800;")
        title = QLabel("Kerberus")
        title.setStyleSheet("font-weight: 650;")
        layout.addWidget(mark)
        layout.addWidget(title)
        layout.addStretch(1)

        self.minimize_button = self._window_button("minus", "Minimizza")
        self.maximize_button = self._window_button("maximize-2", "Massimizza")
        self.close_button = self._window_button("x", "Chiudi", close=True)
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(window.toggle_maximize)
        self.close_button.clicked.connect(window.close)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

    def _window_button(self, icon: str, tooltip: str, close: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName("closeButton" if close else "windowButton")
        button.setIcon(lucide_icon(icon))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(46, 41)
        button.setToolTip(tooltip)
        return button

    def update_maximize_icon(self, maximized: bool) -> None:
        self.maximize_button.setIcon(lucide_icon("minimize-2" if maximized else "maximize-2"))
        self.maximize_button.setToolTip("Ripristina" if maximized else "Massimizza")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ResizeHandle(QWidget):
    def __init__(self, window: "KerberusWindow", edges: Qt.Edge):
        super().__init__(window)
        self.window = window
        self.edges = edges
        if edges in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemResize(self.edges)
            event.accept()
            return
        super().mousePressEvent(event)


class KerberusWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.service = MessengerService(AppConfig())
        self.signals = AppSignals()
        self.selected_contact = ""
        self._connecting = False
        self._router_connected = False
        self._router_detail = "Verifica non ancora completata"
        self._workers: list[threading.Thread] = []
        self._download_dialog: KerberusProgressDialog | None = None
        # Il bordo resta ridimensionabile, ma non copre la scrollbar della chat.
        self._resize_margin = 2
        self._allow_close = False
        self._ui_events: list[str] = []
        self._open_dialogs: set[QDialog] = set()
        self._message_bubbles: dict[str, MessageBubble] = {}
        self._rendered_contact = ""
        self._scroll_pin_generation = 0
        self._tray: QSystemTrayIcon | None = None
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Kerberus")
        self.setMinimumSize(900, 620)
        self.resize(1180, 760)
        self.signals.message_received.connect(self.refresh_messages)
        self.signals.contacts_changed.connect(self._contact_arrived)
        self.signals.protocol_event.connect(self._protocol_event)
        self.signals.router_changed.connect(self._set_router_status)
        self.signals.download_progress.connect(self._update_download)
        self.service.on_message = self.signals.message_received.emit
        self.service.on_contacts_changed = self.signals.contacts_changed.emit
        self.service.on_protocol_event = self.signals.protocol_event.emit

    def initialize(self) -> bool:
        create = not self.service.vault.exists
        password = PasswordDialog(create, self)
        if password.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            if create:
                self.service.vault.create(password.password.text())
            else:
                self.service.vault.unlock(password.password.text())
        except Exception as exc:
            KerberusMessageDialog.show_message(self, "Vault", str(exc))
            return self.initialize()
        if not pq_available():
            KerberusMessageDialog.show_message(
                self,
                "Post-quantum",
                "Il backend ML-KEM-768 non può essere caricato. Reinstalla Kerberus con l'installer più recente.\n\n"
                f"Dettaglio tecnico: {pq_unavailable_reason()}",
            )
            return False
        if not self.service.identity():
            name, ok = self._ask_name()
            if not ok:
                return False
            self.service.create_identity(name)
        self._build_ui()
        self._setup_tray()
        self.refresh_contacts()
        QTimer.singleShot(150, self.connect_router)
        if self.service.settings().get("clearnet_enabled", False):
            QTimer.singleShot(5000, self.check_updates)
        return True

    def _ask_name(self) -> tuple[str, bool]:
        dialog = KerberusDialog("Nuovo profilo", self, 430)
        layout = dialog.body_layout
        layout.setContentsMargins(28, 26, 28, 26)
        title = QLabel("Crea il tuo profilo")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        field = QLineEdit()
        field.setPlaceholderText("Nome visibile")
        layout.addWidget(field)
        submit = QPushButton("Continua")
        submit.setObjectName("primary")
        submit.clicked.connect(dialog.accept)
        layout.addWidget(submit, alignment=Qt.AlignmentFlag.AlignRight)
        field.returnPressed.connect(dialog.accept)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted and bool(field.text().strip())
        return field.text().strip(), accepted

    def _build_ui(self) -> None:
        root = QFrame()
        root.setObjectName("appShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_sidebar())
        body_layout.addWidget(self._build_content(), 1)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self._create_resize_handles()
        self._log_action("UI pronta")

    def _create_resize_handles(self) -> None:
        edge_sets = (
            Qt.Edge.TopEdge,
            Qt.Edge.BottomEdge,
            Qt.Edge.LeftEdge,
            Qt.Edge.RightEdge,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        )
        self._resize_handles = [ResizeHandle(self, edges) for edges in edge_sets]
        self._position_resize_handles()

    def _position_resize_handles(self) -> None:
        if not hasattr(self, "_resize_handles"):
            return
        margin = self._resize_margin
        width, height = self.width(), self.height()
        geometries = (
            QRect(margin, 0, max(0, width - 2 * margin), margin),
            QRect(margin, height - margin, max(0, width - 2 * margin), margin),
            QRect(0, margin, margin, max(0, height - 2 * margin)),
            QRect(width - margin, margin, margin, max(0, height - 2 * margin)),
            QRect(0, 0, margin, margin),
            QRect(width - margin, 0, margin, margin),
            QRect(0, height - margin, margin, margin),
            QRect(width - margin, height - margin, margin, margin),
        )
        for handle, geometry in zip(self._resize_handles, geometries):
            handle.setGeometry(geometry)
            handle.setVisible(not self.isMaximized())
            handle.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._position_resize_handles()
        if self.isMaximized():
            self.clearMask()
        else:
            path = QPainterPath()
            path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        QTimer.singleShot(0, lambda: self.title_bar.update_maximize_icon(self.isMaximized()))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.update_maximize_icon(self.isMaximized())
            self._position_resize_handles()
        super().changeEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.isMaximized():
            self.setCursor(self._edge_cursor(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edges = self._resize_edges(event.position().toPoint())
            if edges and self.windowHandle():
                self.windowHandle().startSystemResize(edges)
                event.accept()
                return
        super().mousePressEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if not self.isMaximized():
            self.unsetCursor()
        super().leaveEvent(event)

    def _resize_edges(self, point: QPoint) -> Qt.Edge:
        edges = Qt.Edge(0)
        if point.x() <= self._resize_margin:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= self.width() - self._resize_margin:
            edges |= Qt.Edge.RightEdge
        if point.y() <= self._resize_margin:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= self.height() - self._resize_margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _edge_cursor(self, point: QPoint) -> Qt.CursorShape:
        edges = self._resize_edges(point)
        if edges in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(310)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 14)
        layout.setSpacing(12)
        brand_row = QHBoxLayout()
        brand = QLabel("KERBERUS")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        add = QToolButton()
        add.setIcon(lucide_icon("user-plus", COLORS["accent"]))
        add.setIconSize(QSize(18, 18))
        add.setToolTip("Aggiungi contatto")
        add.clicked.connect(self.add_contact)
        brand_row.addWidget(add)
        layout.addLayout(brand_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca conversazioni")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(lucide_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.refresh_contacts)
        layout.addWidget(self.search)

        label = QLabel("CONVERSAZIONI")
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        self.contacts_list = QListWidget()
        self.contacts_list.setSpacing(3)
        self.contacts_list.itemClicked.connect(self._select_contact_item)
        layout.addWidget(self.contacts_list, 1)

        status_row = ClickableFrame()
        status_row.setStyleSheet(f"background: {COLORS['surface']}; border-radius: 7px;")
        status_row.setCursor(Qt.CursorShape.PointingHandCursor)
        status_row.setToolTip("Apri informazioni I2P")
        status_row.clicked.connect(self.show_i2p_info)
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(11, 9, 9, 9)
        self.router_dot = QLabel()
        self.router_dot.setFixedSize(9, 9)
        self.router_text = QLabel("I2P: verifica...")
        self.router_text.setObjectName("muted")
        status_text = QVBoxLayout()
        status_text.setSpacing(1)
        self.router_meta = QLabel("Controllo bridge SAM")
        self.router_meta.setObjectName("muted")
        self.router_meta.setStyleSheet("font-size: 11px;")
        status_text.addWidget(self.router_text)
        status_text.addWidget(self.router_meta)
        configure = QToolButton()
        configure.setIcon(lucide_icon("network"))
        configure.setToolTip("Configura I2P")
        configure.clicked.connect(self.router_setup)
        status_layout.addWidget(self.router_dot)
        status_layout.addLayout(status_text, 1)
        status_layout.addWidget(configure)
        layout.addWidget(status_row)

        utility = QHBoxLayout()
        profile = QPushButton("Profilo")
        profile.setObjectName("ghost")
        profile.setIcon(lucide_icon("user-round"))
        profile.clicked.connect(self.show_profile)
        import_button = QPushButton("Importa")
        import_button.setObjectName("ghost")
        import_button.setIcon(lucide_icon("upload"))
        import_button.clicked.connect(self.import_contact)
        settings = QToolButton()
        settings.setIcon(lucide_icon("settings-2"))
        settings.setIconSize(QSize(20, 20))
        settings.setFixedSize(42, 42)
        settings.setToolTip("Impostazioni")
        settings.clicked.connect(self.show_settings)
        utility.addWidget(profile)
        utility.addWidget(import_button)
        utility.addWidget(settings)
        layout.addLayout(utility)
        return sidebar

    def _build_content(self) -> QWidget:
        content = QStackedWidget()
        self.content_stack = content
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark = QLabel()
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(68, 68)
        mark.setPixmap(lucide_icon("message-circle", COLORS["accent"], 32).pixmap(32, 32))
        mark.setStyleSheet(f"background: {COLORS['accent_dark']}; border-radius: 8px;")
        title = QLabel("Le tue conversazioni")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Messaggistica privata attraverso I2P")
        subtitle.setObjectName("muted")
        empty_layout.addWidget(mark, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addSpacing(10)
        empty_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(subtitle, alignment=Qt.AlignmentFlag.AlignCenter)
        content.addWidget(empty)

        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(76)
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(22, 12, 22, 12)
        name_box = QVBoxLayout()
        name_box.setSpacing(2)
        self.chat_avatar = QLabel()
        topbar_layout.addWidget(self.chat_avatar)
        self.chat_name = QLabel()
        self.chat_name.setObjectName("pageTitle")
        self.chat_security = QLabel("Canale ibrido X25519 + ML-KEM-768")
        self.chat_security.setObjectName("muted")
        name_box.addWidget(self.chat_name)
        name_box.addWidget(self.chat_security)
        topbar_layout.addLayout(name_box)
        topbar_layout.addStretch()
        chat_settings = QToolButton()
        chat_settings.setIcon(lucide_icon("settings-2"))
        chat_settings.setToolTip("Privacy di questa chat")
        chat_settings.clicked.connect(self.show_chat_settings)
        topbar_layout.addWidget(chat_settings)
        chat_layout.addWidget(topbar)

        self.message_scroll = QScrollArea()
        self.message_scroll.setWidgetResizable(True)
        self.message_container = QWidget()
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(0, 14, 0, 14)
        self.message_layout.setSpacing(2)
        self.message_layout.addStretch(1)
        self.message_scroll.setWidget(self.message_container)
        chat_layout.addWidget(self.message_scroll, 1)

        composer_frame = QFrame()
        composer_frame.setObjectName("composer")
        composer_layout = QHBoxLayout(composer_frame)
        composer_layout.setContentsMargins(20, 14, 20, 16)
        composer_layout.setSpacing(10)
        self.composer = ComposerEdit()
        self.composer.setPlaceholderText("Scrivi un messaggio")
        self.composer.setFixedHeight(58)
        self.composer.send_requested.connect(self.send_message)
        composer_layout.addWidget(self.composer, 1)
        emoji = QToolButton()
        emoji.setText("☺")
        emoji.setFixedSize(40, 40)
        emoji.setToolTip("Emoji")
        emoji.clicked.connect(lambda: self.show_emoji_menu(emoji))
        composer_layout.addWidget(emoji, alignment=Qt.AlignmentFlag.AlignBottom)
        send = QToolButton()
        send.setObjectName("sendButton")
        send.setIcon(lucide_icon("send", "#07120e"))
        send.setIconSize(QSize(21, 21))
        send.setFixedSize(48, 48)
        send.setToolTip("Invia")
        send.clicked.connect(self.send_message)
        composer_layout.addWidget(send, alignment=Qt.AlignmentFlag.AlignBottom)
        chat_layout.addWidget(composer_frame)
        content.addWidget(chat_page)
        return content

    def refresh_contacts(self, *_args) -> None:
        if not hasattr(self, "contacts_list"):
            return
        query = self.search.text().strip().lower()
        selected = self.selected_contact
        self.contacts_list.clear()
        for contact in self.service.contacts():
            if query and query not in contact.name.lower() and query not in contact.profile_code.lower():
                continue
            messages = self.service.messages_for(contact.identity_id)
            preview = messages[-1]["text"] if messages else "Nuovo contatto"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, contact.identity_id)
            item.setSizeHint(QSize(270, 62))
            self.contacts_list.addItem(item)
            self.contacts_list.setItemWidget(item, ContactRow(contact, preview))
            if contact.identity_id == selected:
                self.contacts_list.setCurrentItem(item)
        for pending in self.service.pending_contacts():
            if query and query not in "richiesta in attesa":
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, "")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setSizeHint(QSize(270, 62))
            self.contacts_list.addItem(item)
            self.contacts_list.setItemWidget(item, PendingContactRow(pending, self.cancel_pending_contact))

    def cancel_pending_contact(self, destination: str) -> None:
        if not destination:
            return
        if not KerberusMessageDialog.ask(
            self,
            "Annulla richiesta",
            "Annullare questa richiesta di contatto e interrompere i tentativi automatici?",
        ):
            return
        if self.service.cancel_pending_contact(destination):
            self.refresh_contacts()
            self.statusBar().showMessage("Richiesta contatto annullata", 4000)

    def _select_contact_item(self, item: QListWidgetItem) -> None:
        self.select_contact(item.data(Qt.ItemDataRole.UserRole))

    def select_contact(self, contact_id: str) -> None:
        contacts = {contact.identity_id: contact for contact in self.service.contacts()}
        contact = contacts.get(contact_id)
        if not contact:
            return
        self.selected_contact = contact_id
        self.service.warm_contact(contact_id)
        set_avatar(self.chat_avatar, contact, 44)
        self.chat_name.setText(contact.name)
        self.content_stack.setCurrentIndex(1)
        self.refresh_messages("select", contact_id)
        self.service.mark_chat_read(contact_id)
        self.composer.setFocus()

    def refresh_messages(self, reason: str = "new", contact_id: str = "") -> None:
        if reason == "new" and contact_id and self._tray is not None and not self.isActiveWindow():
            contact_messages = self.service.messages_for(contact_id)
            if (
                contact_messages
                and contact_messages[-1].get("direction") == "in"
                and self.service.chat_settings(contact_id).get("notifications", True)
            ):
                self._tray.showMessage(
                    "Nuovo messaggio cifrato",
                    "Kerberus ha ricevuto un nuovo messaggio.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
        if not self.selected_contact or not hasattr(self, "message_layout"):
            if contact_id:
                self.refresh_contacts()
            return
        if contact_id and contact_id != self.selected_contact:
            self.refresh_contacts()
            return
        messages = self.service.messages_for(self.selected_contact)
        message_ids = [str(message.get("message_id", "")) for message in messages]
        rendered_ids = list(self._message_bubbles)
        if reason == "status" and self._message_bubbles and message_ids == rendered_ids:
            for message in messages:
                bubble = self._message_bubbles.get(str(message.get("message_id", "")))
                if bubble is not None:
                    bubble.update_message(message)
            self.refresh_contacts()
            return
        scrollbar = self.message_scroll.verticalScrollBar()
        distance_from_bottom = max(0, scrollbar.maximum() - scrollbar.value())
        was_at_bottom = distance_from_bottom <= 24
        can_append = (
            self._rendered_contact == self.selected_contact
            and len(message_ids) >= len(rendered_ids)
            and message_ids[:len(rendered_ids)] == rendered_ids
        )
        if can_append:
            added = messages[len(rendered_ids):]
            for message in added:
                self._append_message_bubble(message)
            for message in messages[:len(rendered_ids)]:
                bubble = self._message_bubbles.get(str(message.get("message_id", "")))
                if bubble is not None:
                    bubble.update_message(message)
            self.refresh_contacts()
            self.message_layout.invalidate()
            if added and (was_at_bottom or any(message.get("direction") == "out" for message in added)):
                self._pin_scroll_to_bottom()
            return
        changed_contact = self._rendered_contact != self.selected_contact
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._message_bubbles.clear()
        for message in messages:
            self._append_message_bubble(message)
        self._rendered_contact = self.selected_contact
        self.refresh_contacts()
        self.message_layout.invalidate()
        self.message_container.adjustSize()
        if changed_contact or reason in {"new", "select"}:
            self._pin_scroll_to_bottom()
        else:
            QTimer.singleShot(
                0,
                lambda: scrollbar.setValue(
                    max(scrollbar.minimum(), scrollbar.maximum() - distance_from_bottom)
                ),
            )

    def _append_message_bubble(self, message: dict) -> None:
        bubble = MessageBubble(
            message["text"],
            int(message.get("sent_at", message["time"])),
            message["direction"] == "out",
            message.get("status", ""),
            timing=message,
            on_timing=self.show_message_timing,
            on_action=self.message_action,
            link_preview=self.service.effective_chat_setting(self.selected_contact, "link_previews"),
        )
        self.message_layout.insertWidget(self.message_layout.count() - 1, bubble)
        self._message_bubbles[str(message.get("message_id", ""))] = bubble

    def _pin_scroll_to_bottom(self) -> None:
        scrollbar = self.message_scroll.verticalScrollBar()
        self._scroll_pin_generation += 1
        generation = self._scroll_pin_generation

        def pin_bottom(_minimum: int = 0, maximum: int | None = None) -> None:
            if generation == self._scroll_pin_generation:
                try:
                    scrollbar.setValue(scrollbar.maximum() if maximum is None else maximum)
                except RuntimeError:
                    pass

        scrollbar.rangeChanged.connect(pin_bottom)
        pin_bottom()

        def release_pin() -> None:
            try:
                scrollbar.rangeChanged.disconnect(pin_bottom)
            except (TypeError, RuntimeError):
                pass
            pin_bottom()

        QTimer.singleShot(350, release_pin)

    def message_action(self, action: str, message: dict) -> None:
        if action.startswith("react:"):
            emoji = action.split(":", 1)[1]
            self._run_task(
                lambda: self.service.react_to_message(self.selected_contact, str(message.get("message_id", "")), emoji),
                lambda _value: self.refresh_messages("status", self.selected_contact),
                lambda error: self._error("Reazione", error),
            )
            return
        if action == "copy":
            QApplication.clipboard().setText(str(message.get("text", "")))
            self.statusBar().showMessage("Messaggio copiato", 2500)
            return
        if action == "delete":
            if KerberusMessageDialog.ask(
                self,
                "Elimina messaggio",
                "Eliminare questo messaggio soltanto dal vault locale? Non verrà cancellato dal dispositivo del contatto.",
            ):
                self.service.delete_message(str(message.get("message_id", "")))
                self.refresh_messages("delete", self.selected_contact)
            return
        if action == "forward":
            self.forward_message(message)

    def show_emoji_menu(self, anchor: QToolButton) -> None:
        menu = QMenu(self)
        for emoji in ("😀", "😂", "😊", "😍", "🥰", "😎", "😢", "😡", "👍", "👎", "❤️", "🔥", "🎉", "🙏", "🤝", "✅"):
            action = menu.addAction(emoji)
            action.triggered.connect(lambda _checked=False, value=emoji: self.composer.insertPlainText(value))
        menu.exec(anchor.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def show_chat_settings(self) -> None:
        if not self.selected_contact:
            return
        current = self.service.chat_settings(self.selected_contact)
        global_settings = self.service.settings()
        dialog = KerberusDialog("Privacy chat", self, 500)
        layout = dialog.body_layout
        title = QLabel("Impostazioni per questa conversazione")
        title.setObjectName("dialogTitle")
        detail = QLabel("Le opzioni in automatico ereditano la policy generale. Le ricevute sono cifrate end-to-end.")
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)

        def tri_state(label: str, key: str) -> QComboBox:
            box = QComboBox()
            box.addItem(f"Automatico ({'attivo' if global_settings.get(key) else 'disattivo'})", None)
            box.addItem("Attivo", True)
            box.addItem("Disattivo", False)
            value = current.get(key)
            box.setCurrentIndex(0 if value is None else (1 if value else 2))
            layout.addWidget(QLabel(label))
            layout.addWidget(box)
            return box

        delivery = tri_state("Conferme di consegna", "send_delivery_receipts")
        reads = tri_state("Conferme di lettura (spunte blu)", "send_read_receipts")
        previews = tri_state("Anteprime link locali", "link_previews")
        notifications = QCheckBox("Notifiche desktop")
        notifications.setChecked(current["notifications"])
        layout.addWidget(notifications)
        actions = QHBoxLayout()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("Salva")
        save.setObjectName("primary")
        save.clicked.connect(dialog.accept)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

        def persist() -> None:
            self.service.update_chat_settings(
                self.selected_contact,
                send_delivery_receipts=delivery.currentData(),
                send_read_receipts=reads.currentData(),
                link_previews=previews.currentData(),
                notifications=notifications.isChecked(),
            )
            self.statusBar().showMessage("Privacy della chat aggiornata", 4000)

        dialog.accepted.connect(persist)
        self._show_modeless(dialog)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(lucide_icon("shield-check", COLORS["accent"], 32), self)
        tray.setToolTip("Kerberus · I2P messenger")
        menu = QMenu(self)
        show_action = menu.addAction("Apri Kerberus")
        show_action.triggered.connect(lambda: (self.showNormal(), self.raise_(), self.activateWindow()))
        quit_action = menu.addAction("Esci")

        def quit_app() -> None:
            self._allow_close = True
            self.close()

        quit_action.triggered.connect(quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: show_action.trigger()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        tray.show()
        self._tray = tray

    def forward_message(self, message: dict) -> None:
        contacts = self.service.contacts()
        if not contacts:
            return
        dialog = KerberusDialog("Inoltra messaggio", self, 500)
        layout = dialog.body_layout
        title = QLabel("Scegli la chat")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        picker = QListWidget()
        for contact in contacts:
            item = QListWidgetItem(contact.name)
            item.setData(Qt.ItemDataRole.UserRole, contact.identity_id)
            picker.addItem(item)
        layout.addWidget(picker)
        actions = QHBoxLayout()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(dialog.reject)
        send = QPushButton("Inoltra")
        send.setObjectName("primary")
        send.clicked.connect(dialog.accept)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(send)
        layout.addLayout(actions)

        def submit() -> None:
            item = picker.currentItem()
            if item is None:
                return
            contact_id = str(item.data(Qt.ItemDataRole.UserRole))
            text = str(message.get("text", ""))
            self._run_task(
                lambda: self.service.forward_message(contact_id, text),
                lambda _value: self.statusBar().showMessage("Messaggio inoltrato con nuova cifratura", 4000),
                lambda error: self._error("Inoltro", error),
            )

        dialog.accepted.connect(submit)
        self._show_modeless(dialog)

    def show_message_timing(self, message: dict) -> None:
        dialog = KerberusDialog("Tempi del messaggio", self, 570)
        layout = dialog.body_layout
        eyebrow = QLabel("DIAGNOSTICA DI CONSEGNA")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Invio e ricezione")
        title.setObjectName("dialogTitle")
        layout.addWidget(eyebrow)
        layout.addWidget(title)

        def format_time(value: object) -> str:
            if not isinstance(value, int):
                return "Non ancora disponibile"
            return datetime.fromtimestamp(value).strftime("%d/%m/%Y · %H:%M:%S")

        def format_delay(seconds: int) -> str:
            if seconds < 0:
                return "Non calcolabile: gli orologi dei dispositivi non sono sincronizzati"
            if seconds < 60:
                return f"{seconds} secondi"
            minutes, remainder = divmod(seconds, 60)
            return f"{minutes} min {remainder} s"

        sent_at = message.get("sent_at", message.get("time"))
        outgoing = message.get("direction") == "out"
        received_at = message.get("recipient_received_at") if outgoing else message.get("received_at")
        delivered_at = message.get("delivered_at")
        rows = [
            ("Inviato dal mittente", format_time(sent_at)),
            ("Ricevuto dal destinatario", format_time(received_at)),
        ]
        if isinstance(sent_at, int) and isinstance(received_at, int):
            rows.append(("Ritardo indicato", format_delay(received_at - sent_at)))
        else:
            rows.append(("Ritardo indicato", "In attesa della conferma"))
        if outgoing:
            rows.append(("ACK ricevuto sul mittente", format_time(delivered_at)))
            if isinstance(sent_at, int) and isinstance(delivered_at, int):
                rows.append(("Tempo totale andata/ritorno", format_delay(delivered_at - sent_at)))

        for label, value in rows:
            row = QFrame()
            row.setStyleSheet(
                f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 7px;"
            )
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(12, 9, 12, 9)
            key = QLabel(label.upper())
            key.setObjectName("eyebrow")
            data = QLabel(value)
            data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(key)
            row_layout.addWidget(data)
            layout.addWidget(row)

        note = QLabel(
            "L’orario di invio è autenticato nel messaggio cifrato. Il ritardo a senso unico dipende anche dalla "
            "sincronizzazione degli orologi; il tempo andata/ritorno usa invece l’orologio del mittente."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self._show_modeless(dialog)

    def send_message(self) -> None:
        text = self.composer.toPlainText().strip()
        if not text or not self.selected_contact:
            return
        self._log_action("Invio messaggio richiesto")
        self.composer.clear()
        self._run_task(
            lambda: self.service.send_message(self.selected_contact, text),
            self._message_send_result,
            lambda error: self._error("Invio", error),
        )

    def _message_send_result(self, value: object) -> None:
        self.refresh_messages("status", self.selected_contact)
        if value == "queued":
            self.statusBar().showMessage(
                "Destinatario temporaneamente non raggiungibile: messaggio cifrato in coda con retry automatico",
                8000,
            )

    def add_contact(self) -> None:
        self._log_action("Apertura Nuovo contatto")
        dialog = ContactDialog(self)

        def submit() -> None:
            if not dialog.code.text().strip():
                return
            code = dialog.code.text()
            first_message = dialog.first_message.toPlainText()
            self._run_task(
                lambda: self.service.request_contact(code, first_message),
                self._contact_request_result,
                lambda error: self._error("Nuovo contatto", error),
            )

        dialog.accepted.connect(submit)
        self._show_modeless(dialog)

    def _contact_request_result(self, value: object) -> None:
        self.refresh_contacts()
        message = "Richiesta affidata a I2P: la chat si aprirà dopo la conferma firmata"
        if value == "queued":
            message = "Contatto non ancora raggiungibile: richiesta salvata e ritentata automaticamente"
        self.statusBar().showMessage(message, 8000)

    def _protocol_event(self, kind: str, detail: str) -> None:
        self._log_action(f"Evento protocollo: {kind} · {detail}")
        if kind in {
            "contact_request_received", "contact_accept_inline", "contact_accept_received",
            "contact_request_cancelled",
        }:
            self.refresh_contacts()
        if kind == "contact_reject_received":
            KerberusMessageDialog.show_message(self, "Richiesta contatto rifiutata", detail)
            return
        self.statusBar().showMessage(detail, 8000)

    def _log_action(self, action: str) -> None:
        safe = action.replace("\r", " ").replace("\n", " ")[:180]
        self._ui_events.append(f"{datetime.now().strftime('%H:%M:%S')}  {safe}")
        self._ui_events = self._ui_events[-1000:]

    def _show_modeless(self, dialog: QDialog) -> None:
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._open_dialogs.add(dialog)
        dialog.destroyed.connect(lambda: self._open_dialogs.discard(dialog))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_ui_console(self) -> None:
        self._log_action("Apertura Console UI")
        dialog = KerberusDialog("Console UI", self, 760)
        dialog.setMinimumHeight(500)
        layout = dialog.body_layout
        eyebrow = QLabel("EVENTI LOCALI · NESSUN CONTENUTO DEI MESSAGGI")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("Attività dell’app")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        console = QPlainTextEdit()
        console.setReadOnly(True)
        console.setStyleSheet("font-family: Consolas; font-size: 12px;")
        console.setPlainText("\n".join(self._ui_events))
        layout.addWidget(console, 1)
        buttons = QHBoxLayout()
        clear = QPushButton("Pulisci")
        clear.clicked.connect(lambda: (self._ui_events.clear(), console.clear()))
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(dialog.accept)
        buttons.addWidget(clear)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._show_modeless(dialog)

    def show_settings(self) -> None:
        self._log_action("Apertura Impostazioni")
        current = self.service.settings()
        dialog = KerberusDialog("Impostazioni", self, 590)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(520)
        scroll.setMaximumHeight(720)
        settings_page = QWidget()
        layout = QVBoxLayout(settings_page)
        layout.setContentsMargins(4, 4, 10, 4)
        layout.setSpacing(10)
        scroll.setWidget(settings_page)
        dialog.body_layout.addWidget(scroll)
        eyebrow = QLabel("PRIVACY E INVITI")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Codice contatto")
        title.setObjectName("dialogTitle")
        description = QLabel(
            "Scegli per quanto tempo resta stabile il codice. La destination I2P non cambia; "
            "cambia soltanto il token di invito autenticato."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(description)
        interval_label = QLabel("INTERVALLO DI ROTAZIONE")
        interval_label.setObjectName("eyebrow")
        interval = QComboBox()
        for minutes, label in ((1, "Ogni minuto"), (5, "Ogni 5 minuti"), (15, "Ogni 15 minuti"), (60, "Ogni ora")):
            interval.addItem(label, minutes)
            if minutes == current["contact_code_period_minutes"]:
                interval.setCurrentIndex(interval.count() - 1)
        single_use = QCheckBox("Ruota immediatamente dopo il primo utilizzo")
        single_use.setChecked(current["contact_code_single_use"])
        hint = QLabel("Consigliato: limita il riutilizzo accidentale di un invito condiviso.")
        hint.setObjectName("muted")
        layout.addSpacing(8)
        layout.addWidget(interval_label)
        layout.addWidget(interval)
        layout.addWidget(single_use)
        layout.addWidget(hint)
        layout.addSpacing(10)
        receipts_label = QLabel("RICEVUTE E RETE")
        receipts_label.setObjectName("eyebrow")
        delivery_receipts = QCheckBox("Invia conferme di consegna")
        delivery_receipts.setChecked(current["send_delivery_receipts"])
        read_receipts = QCheckBox("Invia conferme di lettura (spunte blu)")
        read_receipts.setChecked(current["send_read_receipts"])
        link_previews = QCheckBox("Anteprime link locali (nessuna richiesta automatica)")
        link_previews.setChecked(current["link_previews"])
        minimize_to_tray = QCheckBox("Chiudi nella tray invece di terminare")
        minimize_to_tray.setChecked(current["minimize_to_tray"])
        clearnet = QCheckBox("Consenti funzioni clearnet esplicite (es. aggiornamenti)")
        clearnet.setChecked(current["clearnet_enabled"])
        layout.addWidget(receipts_label)
        layout.addWidget(delivery_receipts)
        layout.addWidget(read_receipts)
        layout.addWidget(link_previews)
        layout.addWidget(minimize_to_tray)
        layout.addWidget(clearnet)
        layout.addSpacing(10)
        diagnostics_label = QLabel("DIAGNOSTICA LOCALE")
        diagnostics_label.setObjectName("eyebrow")
        console_button = QPushButton("Apri Console UI")
        console_button.setIcon(lucide_icon("terminal"))
        console_button.clicked.connect(self.show_ui_console)
        update_button = QPushButton("Controlla aggiornamenti")
        update_button.setIcon(lucide_icon("refresh-cw"))
        update_button.clicked.connect(lambda: self.check_updates(manual=True))
        layout.addWidget(diagnostics_label)
        layout.addWidget(console_button)
        layout.addWidget(update_button)
        actions = QHBoxLayout()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("Salva impostazioni")
        save.setObjectName("primary")
        save.clicked.connect(dialog.accept)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)
        def save_settings() -> None:
            self.service.update_settings(int(interval.currentData()), single_use.isChecked())
            self.service.update_privacy_settings(
                send_delivery_receipts=delivery_receipts.isChecked(),
                send_read_receipts=read_receipts.isChecked(),
                link_previews=link_previews.isChecked(),
                minimize_to_tray=minimize_to_tray.isChecked(),
                clearnet_enabled=clearnet.isChecked(),
            )
            self._log_action("Impostazioni privacy salvate")
            self.statusBar().showMessage("Impostazioni salvate · codice contatto aggiornato", 5000)

        dialog.accepted.connect(save_settings)
        self._show_modeless(dialog)

    def check_updates(self, manual: bool = False) -> None:
        if not self.service.settings().get("clearnet_enabled", False):
            if manual:
                KerberusMessageDialog.show_message(
                    self, "Clearnet disabilitata",
                    "Abilita le funzioni clearnet nelle impostazioni prima di controllare gli aggiornamenti.",
                )
            return
        self._log_action("Controllo aggiornamenti GitHub")

        def found(value: object) -> None:
            info = value if isinstance(value, UpdateInfo) else None
            if info is None:
                if manual:
                    KerberusMessageDialog.show_message(
                        self, "Aggiornamenti", f"Kerberus {__version__} è la versione più recente."
                    )
                return
            if KerberusMessageDialog.ask(
                self,
                "Aggiornamento disponibile",
                f"È disponibile Kerberus {info.version}. Scaricare ora l'aggiornamento dalla release GitHub?",
            ):
                self._download_update(info)

        def failed(error: str) -> None:
            if manual:
                self._error("Aggiornamenti", error)

        self._run_task(lambda: check_for_update(__version__), found, failed)

    def _download_update(self, info: UpdateInfo) -> None:
        self.statusBar().showMessage(f"Download Kerberus {info.version}…", 10000)

        def ready(value: object) -> None:
            path = Path(str(value))
            if os.name != "nt":
                KerberusMessageDialog.show_message(
                    self,
                    "Aggiornamento verificato",
                    f"SHA-256 valida. Il nuovo eseguibile è stato salvato in:\n{path}",
                )
                return
            if not KerberusMessageDialog.ask(
                self,
                "Aggiornamento verificato",
                "La checksum pubblicata nella release è valida. Chiudere Kerberus e avviare l'installer?",
            ):
                return
            subprocess.Popen([str(path)], cwd=path.parent, close_fds=True)
            self._allow_close = True
            self.close()

        self._run_task(
            lambda: download_update(info, self.service.config.downloads_path / "updates"),
            ready,
            lambda error: self._error("Aggiornamenti", error),
        )

    def show_profile(self) -> None:
        self._log_action("Apertura Profilo")
        identity = self.service.identity()
        if not identity:
            return
        dialog = KerberusDialog("Il mio profilo", self, 720)
        layout = dialog.body_layout
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(12)
        eyebrow = QLabel("PROFILO KERBERUS")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        profile_row = QHBoxLayout()
        profile_row.setSpacing(18)
        avatar = QLabel()
        set_avatar(avatar, identity, 88)
        profile_row.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignTop)
        profile_fields = QVBoxLayout()
        username_label = QLabel("USERNAME")
        username_label.setObjectName("eyebrow")
        username = QLineEdit(identity.name)
        username.setMaxLength(40)
        username.addAction(lucide_icon("pencil"), QLineEdit.ActionPosition.LeadingPosition)
        profile_fields.addWidget(username_label)
        profile_fields.addWidget(username)
        photo_actions = QHBoxLayout()
        choose_photo = QPushButton("Cambia foto")
        choose_photo.setIcon(lucide_icon("image-plus"))
        remove_photo = QPushButton("Rimuovi")
        remove_photo.setObjectName("ghost")
        photo_actions.addWidget(choose_photo)
        photo_actions.addWidget(remove_photo)
        photo_actions.addStretch()
        profile_fields.addLayout(photo_actions)
        profile_row.addLayout(profile_fields, 1)
        layout.addLayout(profile_row)
        avatar_data = identity.avatar_data

        def choose_avatar() -> None:
            nonlocal avatar_data
            path, _ = QFileDialog.getOpenFileName(
                dialog,
                "Scegli foto profilo",
                "",
                "Immagini (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if not path:
                return
            try:
                avatar_data = self._normalize_avatar(Path(path))
                preview = IdentityBundle.from_dict(identity.to_dict())
                preview.avatar_data = avatar_data
                set_avatar(avatar, preview, 88)
            except Exception as exc:
                self._error("Foto profilo", str(exc))

        def remove_avatar() -> None:
            nonlocal avatar_data
            avatar_data = ""
            preview = IdentityBundle.from_dict(identity.to_dict())
            preview.avatar_data = ""
            set_avatar(avatar, preview, 88)

        choose_photo.clicked.connect(choose_avatar)
        remove_photo.clicked.connect(remove_avatar)
        crypto_row = QHBoxLayout()
        crypto_id = QLabel()
        crypto_id.setObjectName("muted")
        crypto_id.setWordWrap(True)
        reveal_id = QToolButton()
        reveal_id.setIcon(lucide_icon("eye"))
        reveal_id.setIconSize(QSize(17, 17))
        reveal_id.setFixedSize(34, 34)
        identity_visible = True

        def toggle_identity() -> None:
            nonlocal identity_visible
            identity_visible = not identity_visible
            if identity_visible:
                crypto_id.setText(f"ID crittografico  {identity.identity_id}")
                crypto_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                reveal_id.setIcon(lucide_icon("eye-off"))
                reveal_id.setToolTip("Nascondi ID crittografico")
            else:
                crypto_id.setText("ID crittografico  " + "*" * 32)
                crypto_id.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                reveal_id.setIcon(lucide_icon("eye"))
                reveal_id.setToolTip("Mostra ID crittografico")

        reveal_id.clicked.connect(toggle_identity)
        toggle_identity()
        crypto_row.addWidget(crypto_id, 1)
        crypto_row.addWidget(reveal_id, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(crypto_row)
        layout.addSpacing(14)
        code_label = QLabel("CODICE CONTATTO")
        code_label.setObjectName("eyebrow")
        layout.addWidget(code_label)
        code = QPlainTextEdit()
        code.setReadOnly(True)
        code.setFixedHeight(104)
        code.setStyleSheet("font-family: Consolas; font-size: 13px;")
        layout.addWidget(code)
        expiry = QLabel()
        expiry.setObjectName("muted")
        layout.addWidget(expiry)
        actions = QHBoxLayout()
        export = QPushButton("Esporta profilo")
        export.setIcon(lucide_icon("upload"))
        export.clicked.connect(lambda: self.export_identity(dialog))
        copy = QPushButton("Copia codice")
        copy.setIcon(lucide_icon("copy"))
        save = QPushButton("Salva profilo")
        save.setObjectName("primary")
        save.setIcon(lucide_icon("shield-check", "#07120e"))
        save.clicked.connect(dialog.accept)

        def copy_code() -> None:
            current = code.toPlainText().strip()
            if current and not current.startswith("In attesa"):
                QApplication.clipboard().setText(current)
                copy.setText("Copiato")

        copy.clicked.connect(copy_code)
        actions.addWidget(export)
        actions.addWidget(copy)
        actions.addStretch()
        actions.addWidget(save)
        layout.addLayout(actions)
        timer = QTimer(dialog)

        def refresh_code() -> None:
            try:
                current = self.service.contact_code()
                if code.toPlainText() != current:
                    code.setPlainText(current)
                    copy.setText("Copia codice")
                settings = self.service.settings()
                period_seconds = settings["contact_code_period_minutes"] * 60
                elapsed = max(0, int(time.time()) - settings["contact_code_anchor_time"])
                seconds = period_seconds - (elapsed % period_seconds)
                policy = "Monouso" if settings["contact_code_single_use"] else "Riutilizzabile nel periodo"
                expiry.setText(f"{policy} · nuovo codice tra {seconds} secondi")
            except Exception:
                code.setPlainText("In attesa della connessione I2P")
                expiry.setText("Codice non disponibile")

        timer.timeout.connect(refresh_code)
        timer.start(1000)
        refresh_code()
        def save_profile() -> None:
            self._run_task(
                lambda: self.service.update_profile(username.text(), avatar_data),
                self._profile_saved,
                lambda error: self._error("Profilo", error),
            )

        dialog.accepted.connect(save_profile)
        self._show_modeless(dialog)

    @staticmethod
    def _normalize_avatar(path: Path) -> str:
        image = QImage(str(path))
        if image.isNull():
            raise ValueError("Immagine non leggibile")
        for size in (256, 224, 192, 160, 128):
            scaled = image.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = max(0, (scaled.width() - size) // 2)
            y = max(0, (scaled.height() - size) // 2)
            square = scaled.copy(x, y, size, size).convertToFormat(QImage.Format.Format_ARGB32)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            square.save(buffer, "PNG")
            raw = bytes(buffer.data())
            buffer.close()
            if len(raw) <= 120_000:
                return b64(raw)
        raise ValueError("Immagine troppo complessa da comprimere in modo sicuro")

    def _profile_saved(self, value: object) -> None:
        self.refresh_contacts()
        if self.selected_contact:
            self.select_contact(self.selected_contact)
        self.statusBar().showMessage("Profilo firmato e aggiornato", 5000)

    def import_contact(self) -> None:
        self._log_action("Importazione profilo richiesta")
        path, _ = QFileDialog.getOpenFileName(self, "Importa profilo", "", "Profilo Kerberus (*.kbid *.json);;Tutti i file (*.*)")
        if not path:
            return
        try:
            contact = self.service.import_contact(Path(path).read_text("utf-8"))
            self.refresh_contacts()
            self.select_contact(contact.identity_id)
        except Exception as exc:
            self._error("Profilo non valido", str(exc))

    def export_identity(self, parent: QWidget | None = None) -> None:
        self._log_action("Esportazione profilo richiesta")
        identity = self.service.identity()
        if not identity:
            return
        path, _ = QFileDialog.getSaveFileName(parent or self, "Esporta profilo", f"{identity.name}.kbid", "Profilo Kerberus (*.kbid)")
        if path:
            Path(path).write_text(self.service.export_identity(), encoding="utf-8")

    def connect_router(self) -> None:
        if self._connecting:
            return
        self._connecting = True
        self._log_action("Connessione I2P avviata")
        if hasattr(self, "router_dot"):
            self.router_dot.setStyleSheet(f"background: {COLORS['warning']}; border-radius: 4px;")
            self.router_text.setText("I2P: connessione...")
            self.router_meta.setText("Avvio router e tunnel")

        def work() -> None:
            try:
                if not self.service.sam.available():
                    RouterInstaller.ensure_sam_enabled()
                    RouterInstaller.start_installed()
                    for _ in range(45):
                        if self.service.sam.available():
                            break
                        time.sleep(1)
                self.service.connect_router()
                self.signals.router_changed.emit(True, "I2P: connesso")
            except Exception as exc:
                self.signals.router_changed.emit(False, str(exc))

        thread = threading.Thread(target=work, daemon=True)
        self._workers.append(thread)
        thread.start()

    def _set_router_status(self, connected: bool, detail: str) -> None:
        self._connecting = False
        self._router_connected = connected
        self._router_detail = detail
        color = COLORS["accent"] if connected else COLORS["danger"]
        self.router_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.router_text.setText("I2P: connesso" if connected else "I2P: non connesso")
        self.router_meta.setText("Tunnel pronto · SAM locale" if connected else "Nuovo tentativo tra 10 s")
        self.router_text.setToolTip(detail)
        self._log_action("I2P connesso" if connected else f"Connessione I2P non riuscita · {detail}")
        if connected:
            self.statusBar().showMessage("Canale I2P pronto", 3500)
        else:
            QTimer.singleShot(10000, self.connect_router)

    def show_i2p_info(self) -> None:
        self._log_action("Apertura Stato I2P")
        identity = self.service.identity()
        dialog = KerberusDialog("Stato I2P", self, 620)
        layout = dialog.body_layout
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(12)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(lucide_icon("network", COLORS["accent"] if self._router_connected else COLORS["danger"], 30).pixmap(30, 30))
        title_box = QVBoxLayout()
        title = QLabel("I2P connesso" if self._router_connected else "I2P non connesso")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(self._router_detail)
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        header.addLayout(title_box, 1)
        state_badge = QLabel("ONLINE" if self._router_connected else "OFFLINE")
        state_badge.setStyleSheet(
            f"background: {COLORS['accent_dark'] if self._router_connected else '#552a30'}; "
            f"color: {COLORS['accent'] if self._router_connected else COLORS['danger']}; "
            "border-radius: 7px; padding: 5px 9px; font-size: 11px; font-weight: 800;"
        )
        header.addWidget(state_badge, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(8)

        destination = "Non disponibile"
        queues = self.service.queue_status()
        if identity and identity.destination:
            try:
                destination = destination_b32(identity.destination)
            except ValueError:
                pass
        details = (
            ("Versione", f"Kerberus {__version__}"),
            ("Bridge SAM", f"{self.service.config.sam_host}:{self.service.config.sam_port}"),
            ("Destination", destination),
            ("Trasporto", "I2P streaming · sessione persistente"),
            ("Messaggi", "X25519 + ML-KEM-768 · XChaCha20-Poly1305"),
            ("Identità", "Ed25519 · profili firmati"),
            ("Metadati", "Padding a bucket · anti-replay · timestamp cifrati"),
            (
                "Code locali",
                f"{queues['messages']} messaggi · {queues['contacts']} contatti · {queues['control']} conferme",
            ),
            ("Ultimo evento", self.service.last_protocol_event),
        )
        for label, value in details:
            row = QFrame()
            row.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 7px;")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            key = QLabel(label)
            key.setObjectName("muted")
            data = QLabel(value)
            data.setWordWrap(True)
            data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(key)
            row_layout.addStretch()
            row_layout.addWidget(data, 1)
            layout.addWidget(row)
        actions = QHBoxLayout()
        reconnect = QPushButton("Riconnetti")
        reconnect.setIcon(lucide_icon("refresh-cw"))
        reconnect.clicked.connect(lambda: (dialog.accept(), self.connect_router()))
        retry = QPushButton("Riprova code")
        retry.clicked.connect(lambda: (dialog.accept(), self._retry_queues()))
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(dialog.accept)
        actions.addWidget(reconnect)
        actions.addWidget(retry)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)
        self._show_modeless(dialog)

    def _retry_queues(self) -> None:
        status = self.service.retry_all_now()
        self._log_action("Retry manuale delle code I2P")
        self.statusBar().showMessage(
            f"Retry avviato: {status['messages']} messaggi, {status['contacts']} contatti, {status['control']} conferme",
            8000,
        )

    def router_setup(self) -> None:
        if self.service.sam.available():
            self.connect_router()
            return
        if os.name != "nt":
            RouterInstaller.ensure_sam_enabled()
            if RouterInstaller.start_installed():
                self.statusBar().showMessage("Router I2P avviato · attendo il bridge SAM", 8000)
                QTimer.singleShot(1500, self.connect_router)
                return
            KerberusMessageDialog.show_message(
                self,
                "Configura I2P su Linux",
                "Installa I2P dal repository ufficiale della distribuzione, avvialo con “i2prouter start” "
                "e verifica che SAM ascolti soltanto su 127.0.0.1:7656. Kerberus ha già preparato la "
                "configurazione utente in ~/.i2p/clients.config.d/.",
            )
            return
        if not KerberusMessageDialog.ask(
            self, "Installa I2P", f"Scaricare l'installer ufficiale I2P {I2P_VERSION} e verificarne la checksum SHA-256?"
        ):
            return
        self._download_dialog = KerberusProgressDialog("Configurazione I2P", "Download e verifica I2P...", self)
        self._download_dialog.show()

        def download() -> Path:
            return RouterInstaller(self.service.config.downloads_path).download_windows(
                lambda done, total: self.signals.download_progress.emit(done, total)
            )

        self._run_task(download, self._download_ready, lambda error: self._download_failed(error))

    def _update_download(self, done: int, total: int) -> None:
        if self._download_dialog:
            self._download_dialog.setMaximum(max(total, 1))
            self._download_dialog.setValue(done)

    def _download_ready(self, value: object) -> None:
        if self._download_dialog:
            self._download_dialog.close()
            self._download_dialog = None
        path = Path(value)
        if KerberusMessageDialog.ask(self, "I2P verificato", "Checksum valida. Avviare l'installer?"):
            RouterInstaller.launch_installer(path)

    def _download_failed(self, error: str) -> None:
        if self._download_dialog:
            self._download_dialog.close()
            self._download_dialog = None
        self._error("I2P", error)

    def _contact_arrived(self, contact_id: str) -> None:
        self.refresh_contacts()
        QTimer.singleShot(100, self.refresh_contacts)
        if not self.selected_contact or self.selected_contact == contact_id:
            self.select_contact(contact_id)
        self.statusBar().showMessage("Nuovo contatto verificato", 5000)

    def _run_task(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
        failure: Callable[[str], None],
    ) -> None:
        signals = AppSignals()
        signals.task_done.connect(success)
        signals.task_error.connect(failure)
        self._task_signals = getattr(self, "_task_signals", [])
        self._task_signals.append(signals)

        def work() -> None:
            try:
                signals.task_done.emit(function())
            except Exception as exc:
                signals.task_error.emit(str(exc))

        thread = threading.Thread(target=work, daemon=True)
        self._workers.append(thread)
        thread.start()

    def _error(self, title: str, message: str) -> None:
        self._log_action(f"Errore UI: {title}")
        KerberusMessageDialog.show_message(self, title, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._allow_close and self._tray is not None and self.service.settings().get("minimize_to_tray", True):
            self.hide()
            self._tray.showMessage("Kerberus", "Kerberus continua a funzionare nella tray.", QSystemTrayIcon.MessageIcon.Information, 2500)
            event.ignore()
            return
        if not self._allow_close:
            if not KerberusMessageDialog.ask(
                self,
                "Chiudi Kerberus",
                "Chiudere Kerberus e arrestare anche il router I2P? Tutte le comunicazioni I2P verranno interrotte.",
            ):
                event.ignore()
                return
            self._allow_close = True
        self.service.close()
        RouterInstaller.stop_running()
        event.accept()


def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Kerberus")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)
    window = KerberusWindow()
    if not window.initialize():
        return
    window.show()
    sys.exit(app.exec())
