from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

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
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig
from . import __version__
from .crypto import IdentityBundle, b64, destination_b32, pq_available, unb64
from .router import I2P_VERSION, RouterInstaller
from .service import MessengerService


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
QMainWindow, QDialog {{ background: {COLORS['window']}; }}
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
QToolButton#windowButton {{ border-radius: 0; padding: 0; }}
QToolButton#windowButton:hover {{ background: {COLORS['surface_3']}; }}
QToolButton#closeButton {{ border-radius: 0; padding: 0; }}
QToolButton#closeButton:hover {{ background: {COLORS['danger']}; }}
QListWidget {{ background: transparent; border: 0; outline: 0; padding: 0; }}
QListWidget::item {{ border: 0; padding: 0; }}
QListWidget::item:selected {{ background: {COLORS['surface_2']}; border-radius: 6px; }}
QListWidget::item:hover:!selected {{ background: #181e24; border-radius: 6px; }}
QScrollArea {{ background: transparent; border: 0; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a434e; border-radius: 4px; min-height: 32px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QProgressDialog {{ min-width: 430px; }}
"""


class AppSignals(QObject):
    message_received = pyqtSignal()
    contacts_changed = pyqtSignal(str)
    protocol_event = pyqtSignal(str, str)
    router_changed = pyqtSignal(bool, str)
    task_done = pyqtSignal(object)
    task_error = pyqtSignal(str)
    download_progress = pyqtSignal(int, int)


class PasswordDialog(QDialog):
    def __init__(self, create: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Crea vault" if create else "Sblocca Kerberus")
        self.setFixedWidth(440)
        layout = QVBoxLayout(self)
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
            QMessageBox.warning(self, "Vault", "Le password non coincidono.")
            return
        self.accept()


class ContactDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Nuovo contatto")
        self.setFixedWidth(600)
        layout = QVBoxLayout(self)
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


class MessageBubble(QWidget):
    def __init__(self, text: str, timestamp: int, outgoing: bool, status: str = ""):
        super().__init__()
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
        status_labels = {
            "pending": "In attesa",
            "sent": "Inviato",
            "delivered": "Consegnato",
        }
        time_text = datetime.fromtimestamp(timestamp).strftime("%H:%M")
        if outgoing:
            time_text += f"  ·  {status_labels.get(status, 'Salvato')}"
        time_label = QLabel(time_text)
        time_label.setObjectName("timestamp")
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_label.setStyleSheet("border: 0; background: transparent; font-size: 11px;")
        content.addWidget(time_label)
        outer.addWidget(bubble)
        if not outgoing:
            outer.addStretch(1)


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
        self._download_dialog: QProgressDialog | None = None
        self._resize_margin = 7
        self._allow_close = False
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
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
            QMessageBox.critical(self, "Vault", str(exc))
            return self.initialize()
        if not self.service.identity():
            if not pq_available():
                QMessageBox.critical(self, "Post-quantum", "Il backend ML-KEM-768 non è disponibile.")
                return False
            name, ok = self._ask_name()
            if not ok:
                return False
            self.service.create_identity(name)
        self._build_ui()
        self.refresh_contacts()
        QTimer.singleShot(150, self.connect_router)
        return True

    def _ask_name(self) -> tuple[str, bool]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Nuovo profilo")
        dialog.setFixedWidth(430)
        layout = QVBoxLayout(dialog)
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
        root = QWidget()
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
        configure = QToolButton()
        configure.setIcon(lucide_icon("network"))
        configure.setToolTip("Configura I2P")
        configure.clicked.connect(self.router_setup)
        status_layout.addWidget(self.router_dot)
        status_layout.addWidget(self.router_text, 1)
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
        utility.addWidget(profile)
        utility.addWidget(import_button)
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

    def _select_contact_item(self, item: QListWidgetItem) -> None:
        self.select_contact(item.data(Qt.ItemDataRole.UserRole))

    def select_contact(self, contact_id: str) -> None:
        contacts = {contact.identity_id: contact for contact in self.service.contacts()}
        contact = contacts.get(contact_id)
        if not contact:
            return
        self.selected_contact = contact_id
        set_avatar(self.chat_avatar, contact, 44)
        self.chat_name.setText(contact.name)
        self.content_stack.setCurrentIndex(1)
        self.refresh_messages()
        self.composer.setFocus()

    def refresh_messages(self) -> None:
        if not self.selected_contact or not hasattr(self, "message_layout"):
            return
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for message in self.service.messages_for(self.selected_contact):
            self.message_layout.insertWidget(
                self.message_layout.count() - 1,
                MessageBubble(
                    message["text"],
                    message["time"],
                    message["direction"] == "out",
                    message.get("status", ""),
                ),
            )
        self.refresh_contacts()
        QTimer.singleShot(20, lambda: self.message_scroll.verticalScrollBar().setValue(self.message_scroll.verticalScrollBar().maximum()))

    def send_message(self) -> None:
        text = self.composer.toPlainText().strip()
        if not text or not self.selected_contact:
            return
        self.composer.clear()
        self._run_task(
            lambda: self.service.send_message(self.selected_contact, text),
            self._message_send_result,
            lambda error: self._error("Invio", error),
        )

    def _message_send_result(self, value: object) -> None:
        self.refresh_messages()
        if value == "queued":
            self.statusBar().showMessage(
                "Destinatario temporaneamente non raggiungibile: messaggio cifrato in coda con retry automatico",
                8000,
            )

    def add_contact(self) -> None:
        dialog = ContactDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.code.text().strip():
            return
        self._run_task(
            lambda: self.service.request_contact(dialog.code.text(), dialog.first_message.toPlainText()),
            self._contact_request_result,
            lambda error: self._error("Nuovo contatto", error),
        )

    def _contact_request_result(self, value: object) -> None:
        message = "Richiesta inviata: attendo la conferma firmata"
        if value == "queued":
            message = "Contatto non ancora raggiungibile: richiesta salvata e ritentata automaticamente"
        self.statusBar().showMessage(message, 8000)

    def _protocol_event(self, kind: str, detail: str) -> None:
        if kind == "contact_reject_received":
            QMessageBox.warning(self, "Richiesta contatto rifiutata", detail)
            return
        self.statusBar().showMessage(detail, 8000)

    def show_profile(self) -> None:
        identity = self.service.identity()
        if not identity:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Il mio profilo")
        dialog.setFixedWidth(720)
        layout = QVBoxLayout(dialog)
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
        crypto_id = QLabel(f"ID crittografico  {identity.identity_id}")
        crypto_id.setObjectName("muted")
        crypto_id.setWordWrap(True)
        crypto_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(crypto_id)
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
                seconds = 60 - int(time.time() % 60)
                expiry.setText(f"Monouso · nuovo codice tra {seconds} secondi")
            except Exception:
                code.setPlainText("In attesa della connessione I2P")
                expiry.setText("Codice non disponibile")

        timer.timeout.connect(refresh_code)
        timer.start(1000)
        refresh_code()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._run_task(
                lambda: self.service.update_profile(username.text(), avatar_data),
                self._profile_saved,
                lambda error: self._error("Profilo", error),
            )

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
        self.router_text.setToolTip(detail)
        if connected:
            self.statusBar().showMessage("Canale I2P pronto", 3500)
        else:
            QTimer.singleShot(10000, self.connect_router)

    def show_i2p_info(self) -> None:
        identity = self.service.identity()
        dialog = QDialog(self)
        dialog.setWindowTitle("Stato I2P")
        dialog.setFixedWidth(620)
        layout = QVBoxLayout(dialog)
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
        layout.addLayout(header)
        layout.addSpacing(8)

        destination = "Non disponibile"
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
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(dialog.accept)
        actions.addWidget(reconnect)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)
        dialog.exec()

    def router_setup(self) -> None:
        if self.service.sam.available():
            self.connect_router()
            return
        answer = QMessageBox.question(
            self,
            "Installa I2P",
            f"Scaricare l'installer ufficiale I2P {I2P_VERSION} e verificarne la checksum SHA-256?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._download_dialog = QProgressDialog("Download e verifica I2P...", "Annulla", 0, 100, self)
        self._download_dialog.setWindowTitle("Configurazione I2P")
        self._download_dialog.setAutoClose(False)
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
        if QMessageBox.question(self, "I2P verificato", "Checksum valida. Avviare l'installer?") == QMessageBox.StandardButton.Yes:
            RouterInstaller.launch_installer(path)

    def _download_failed(self, error: str) -> None:
        if self._download_dialog:
            self._download_dialog.close()
            self._download_dialog = None
        self._error("I2P", error)

    def _contact_arrived(self, contact_id: str) -> None:
        self.refresh_contacts()
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
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._allow_close:
            answer = QMessageBox.question(
                self,
                "Chiudi Kerberus",
                "Chiudere Kerberus e arrestare anche il router I2P? Tutte le comunicazioni I2P verranno interrotte.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
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
