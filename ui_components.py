"""
ui_components.py - Custom widgets, vector icon generators, and delegates for Action Shark Desktop Pro UI.
"""

import os
import urllib.request
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QFileDialog,
    QStyledItemDelegate,
    QDialog,
    QProgressBar,
    QTextEdit,
    QListWidget,
    QMessageBox,
    QFrame,
    QStyleOptionButton,
    QStyle,
    QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QRectF, QSize, QTimer, QPointF
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
    QPixmap,
    QIcon,
    QLinearGradient,
    QPainterPath,
)

import styles
import wemod_manager as wm
import error_logger
import i18n
from i18n import t


CACHE_DIR = os.path.expanduser('~/.cache/action_shark')
BANNER_CACHE_DIR = os.path.join(CACHE_DIR, 'banners')
CHEVRON_ICON_PATH = os.path.join(CACHE_DIR, 'chevron_down.png')


# ── Vector Icon Generators (Clean, crisp, no emojis) ──────────────────

def get_shark_icon(size: int = 24) -> QIcon:
    """Shared scalable shark artwork for the header, window and launcher.

    The size argument remains accepted for existing callers; QIcon renders
    the SVG at the requested pixmap size and device pixel ratio.
    """
    return QIcon(str(Path(__file__).resolve().parent / "images" / "action-shark.svg"))


def get_cheatengine_icon(size: int = 18) -> QIcon:
    """Scalable classic Cheat Engine icon (blue magnifying emblem + CE monogram)."""
    return QIcon(str(Path(__file__).resolve().parent / "images" / "cheat-engine.svg"))


def get_wemod_icon(size: int = 18) -> QIcon:
    """Draws stylized WeMod 'W' logo with gradient glow."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(0, 0, size, 0)
    gradient.setColorAt(0, QColor('#a34de8'))
    gradient.setColorAt(.5, QColor('#32c9eb'))
    gradient.setColorAt(1, QColor('#33e0c2'))
    pen = QPen(QBrush(gradient), 3.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    path = QPainterPath()
    path.moveTo(size * 0.15, size * 0.3)
    path.lineTo(size * 0.32, size * 0.75)
    path.lineTo(size * 0.5, size * 0.42)
    path.lineTo(size * 0.68, size * 0.75)
    path.lineTo(size * 0.85, size * 0.3)
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def get_folder_icon(size: int = 18) -> QIcon:
    """Draws clean modern folder icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    path = QPainterPath()
    path.moveTo(2, 4)
    path.lineTo(7, 4)
    path.lineTo(9, 6)
    path.lineTo(size - 2, 6)
    path.lineTo(size - 2, size - 3)
    path.lineTo(2, size - 3)
    path.closeSubpath()

    p.setPen(QPen(QColor('#c5c7cf'), 1.1))
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def get_log_icon(size: int = 18) -> QIcon:
    """Draws clean document/log icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    w = size * 0.70
    h = size * 0.85
    x = (size - w) / 2.0
    y = (size - h) / 2.0

    pen = QPen(QColor('#c5c7cf'), 1.2)
    p.setPen(pen)
    p.drawRoundedRect(QRectF(x, y, w, h), 2.0, 2.0)

    line_pen = QPen(QColor('#9ca3af'), 1.1)
    p.setPen(line_pen)
    p.drawLine(QPointF(x + 3, y + h * 0.32), QPointF(x + w - 3, y + h * 0.32))
    p.drawLine(QPointF(x + 3, y + h * 0.52), QPointF(x + w - 3, y + h * 0.52))
    p.drawLine(QPointF(x + 3, y + h * 0.72), QPointF(x + w * 0.65, y + h * 0.72))
    p.end()
    return QIcon(pix)


def get_gear_icon(size: int = 18) -> QIcon:
    """Draws clean settings gear icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor("#9ca3af"), 1.8)
    p.setPen(pen)
    center = size / 2.0
    p.drawEllipse(QPointF(center, center), size * 0.32, size * 0.32)

    import math
    for i in range(6):
        angle = i * (math.pi / 3)
        x1 = center + math.cos(angle) * (size * 0.32)
        y1 = center + math.sin(angle) * (size * 0.32)
        x2 = center + math.cos(angle) * (size * 0.48)
        y2 = center + math.sin(angle) * (size * 0.48)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    p.end()
    return QIcon(pix)


def get_refresh_icon(size: int = 18) -> QIcon:
    """Draws clean circular sync arrows icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor("#9ca3af"), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)

    center = size / 2.0
    radius = size * 0.35
    p.drawArc(QRectF(center - radius, center - radius, radius * 2, radius * 2), 45 * 16, 260 * 16)

    path = QPainterPath()
    path.moveTo(center + radius - 3, center - radius - 2)
    path.lineTo(center + radius + 3, center - radius + 2)
    path.lineTo(center + radius - 1, center - radius + 6)
    p.setBrush(QBrush(QColor("#9ca3af")))
    p.fillPath(path, QBrush(QColor("#9ca3af")))
    p.end()
    return QIcon(pix)


def _simple_line_icon(size: int, lines: list[tuple[QPointF, QPointF]], color: str = "#a5a7b7") -> QIcon:
    """Small monochrome icon helper used by the frameless window chrome."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    for start, end in lines:
        p.drawLine(start, end)
    p.end()
    return QIcon(pix)


def get_filter_icon(size: int = 18) -> QIcon:
    """Three-line descending filter glyph from the reference UI."""
    return _simple_line_icon(size, [
        (QPointF(2, 4), QPointF(size - 2, 4)),
        (QPointF(5, size / 2), QPointF(size - 5, size / 2)),
        (QPointF(8, size - 4), QPointF(size - 8, size - 4)),
    ])


def get_search_icon(size: int = 16) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#9ca0b0"), 1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawEllipse(QPointF(size * 0.42, size * 0.42), size * 0.27, size * 0.27)
    p.drawLine(QPointF(size * 0.62, size * 0.62), QPointF(size * 0.86, size * 0.86))
    p.end()
    return QIcon(pix)


def get_back_icon(size: int = 18) -> QIcon:
    return _simple_line_icon(size, [
        (QPointF(size - 3, size / 2), QPointF(3, size / 2)),
        (QPointF(3, size / 2), QPointF(8, size / 2 - 5)),
        (QPointF(3, size / 2), QPointF(8, size / 2 + 5)),
    ])


def get_minimize_icon(size: int = 16) -> QIcon:
    return _simple_line_icon(size, [(QPointF(3, size - 4), QPointF(size - 3, size - 4))])


def get_maximize_icon(size: int = 16) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#a5a7b7"), 1.25))
    p.drawRect(QRectF(3, 3, size - 6, size - 6))
    p.end()
    return QIcon(pix)


def get_close_icon(size: int = 16) -> QIcon:
    return _simple_line_icon(size, [
        (QPointF(3, 3), QPointF(size - 3, size - 3)),
        (QPointF(size - 3, 3), QPointF(3, size - 3)),
    ])


class RoundedButton(QPushButton):
    """Paint the few reference buttons explicitly for consistent corner radii."""

    def paintEvent(self, event):
        kind = self.objectName()
        if kind not in {"chipBtn", "quickActionBtn", "launchTrainerBtn", "browseBtn"}:
            return super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        enabled = self.isEnabled()
        hovered = self.underMouse()

        if kind == "launchTrainerBtn":
            bg, border, radius = "#696cde", "#777ae7", 20
            if hovered:
                bg = "#6860f5"
        elif kind == "browseBtn":
            bg, border, radius = "#696cde", "#777ae7", 6
            if hovered:
                bg = "#6860f5"
        elif kind == "chipBtn":
            selected = self.property("selected") == "true"
            bg = "#4a4d78" if selected else "#272830"
            border = bg
            radius = 14
            if hovered and not selected:
                bg, border = "#262835", "#3f4258"
        else:
            bg, border, radius = "#25262d", "#3a3b46", 9
            if hovered:
                bg, border = "#262835", "#3f4258"

        if not enabled:
            bg, border = "#171821", "#252633"
        painter.setBrush(QBrush(QColor(bg)))
        painter.setPen(QPen(QColor(border), 1))
        painter.drawRoundedRect(rect, radius, radius)

        text_color = QColor("#ffffff" if kind in {"launchTrainerBtn", "browseBtn"} else "#f3f4f6")
        if not enabled:
            text_color = QColor("#6b6e80")
        painter.setPen(text_color)
        font = self.font()
        font.setPixelSize(13 if kind == "chipBtn" else 15)
        font.setBold(False)
        painter.setFont(font)

        text = self.text().strip()
        if kind == "quickActionBtn":
            icon_size = 18
            icon_rect = QRect(12, (self.height() - icon_size) // 2, icon_size, icon_size)
            if not self.icon().isNull():
                self.icon().paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter,
                                  QIcon.Mode.Disabled if not enabled else QIcon.Mode.Normal)
            text_rect = QRect(37, 0, max(0, self.width() - 45), self.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        else:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class SurfaceFrame(QFrame):
    """Rounded outer shell that remains clipped on both X11 and Wayland."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QBrush(QColor("#16171d")))
        painter.setPen(QPen(QColor("#0d0e13"), 1))
        painter.drawRoundedRect(rect, 12, 12)
        painter.end()


# ── Status Badge Item Delegate ────────────────────────────────────────

class StatusBadgeDelegate(QStyledItemDelegate):
    """Custom delegate that renders pill badges matching Mockup 2 exactly."""

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = QRectF(option.rect)
        tree = self.parent()
        full.setLeft(0)
        full.setWidth(tree.viewport().width())
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setClipRect(option.rect)
        color = '#3b3d59' if selected else ('#25262e' if index.row() % 2 == 0 else '#18191e')
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(full.adjusted(0, 0, 0, -1), 6, 6)
        painter.restore()
        if index.column() == 3:  # Status column
            status_text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            if not status_text:
                return
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            rect = option.rect

            font = painter.font()
            font.setPixelSize(12)
            font.setBold(False)
            painter.setFont(font)
            fm = painter.fontMetrics()

            badge_w = max(fm.horizontalAdvance(status_text) + 18, 48)
            badge_h = 22
            badge_x = rect.x() + 10
            badge_y = rect.y() + (rect.height() - badge_h) // 2
            badge_rect = QRectF(badge_x, badge_y, badge_w, badge_h)

            st_lower = status_text.lower()
            is_positive = (
                st_lower in ("active", "rodando", "running", "en ejecución", "en ejecucion")
                or (
                    ("instalado" in st_lower or "installed" in st_lower)
                    and "não" not in st_lower
                    and "nao" not in st_lower
                    and "not" not in st_lower
                    and "no " not in st_lower
                )
            )

            if is_positive:
                bg_color = QColor(34, 197, 94, 35)
                border_color = QColor(34, 197, 94, 75)
                text_color = QColor(52, 211, 153)
            else:
                bg_color = QColor(255, 255, 255, 10)
                border_color = QColor(255, 255, 255, 18)
                text_color = QColor('#9ca3af')

            path = QPainterPath()
            path.addRoundedRect(badge_rect, 11, 11)
            painter.fillPath(path, QBrush(bg_color))
            painter.setPen(QPen(border_color, 1))
            painter.drawPath(path)

            painter.setPen(text_color)
            painter.drawText(badge_rect.toRect(), Qt.AlignmentFlag.AlignCenter, status_text)
            painter.restore()
        else:
            painter.save()
            painter.setFont(option.font)
            painter.setPen(QColor('#eeeeef'))
            rect = option.rect.adjusted(12, 0, -10, 0)
            text = painter.fontMetrics().elidedText(str(index.data() or ''), Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, text)
            painter.restore()


# ── Filter Chip Bar ───────────────────────────────────────────────────

class FilterChipBar(QWidget):
    """Row of pill filter chips matching Mockup 2: [All], Steam, Lutris, Bottles, Active]."""

    filter_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_filter = "ALL"
        self._buttons = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(6)

        chips = [
            ("ALL", t("chip_all")),
            ("STEAM", t("chip_steam")),
            ("HYDRA", t("chip_hydra")),
            ("HEROIC", t("chip_heroic")),
            ("LUTRIS", t("chip_lutris")),
            ("BOTTLES", t("chip_bottles")),
            ("NON_STEAM", t("chip_non_steam")),
            ("DEFAULT_WINE", t("chip_default_wine")),
            ("CUSTOM", t("chip_custom")),
        ]

        for code, label in chips:
            btn = RoundedButton(label)
            btn.setObjectName("chipBtn")
            btn.setFixedHeight(28)
            btn.setProperty("filterCode", code)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(t("tooltip_chip_all") if code == "ALL" else t("tooltip_chip_source", source=label))
            btn.clicked.connect(lambda checked, c=code: self.set_active_filter(c))
            layout.addWidget(btn)
            self._buttons[code] = btn

        layout.addStretch()
        self._update_button_states()

    def retranslate(self):
        mapping = {
            "ALL": "chip_all",
            "STEAM": "chip_steam",
            "HYDRA": "chip_hydra",
            "HEROIC": "chip_heroic",
            "LUTRIS": "chip_lutris",
            "BOTTLES": "chip_bottles",
            "NON_STEAM": "chip_non_steam",
            "DEFAULT_WINE": "chip_default_wine",
            "CUSTOM": "chip_custom",
        }
        for code, key in mapping.items():
            if code in self._buttons:
                label = t(key)
                self._buttons[code].setText(label)
                self._buttons[code].setToolTip(
                    t("tooltip_chip_all") if code == "ALL" else t("tooltip_chip_source", source=label)
                )

    def set_active_filter(self, code: str):
        if self._active_filter != code:
            self._active_filter = code
            self._update_button_states()
            self.filter_changed.emit(code)

    def get_active_filter(self) -> str:
        return self._active_filter

    def _update_button_states(self):
        for code, btn in self._buttons.items():
            is_sel = (code == self._active_filter)
            btn.setProperty("selected", "true" if is_sel else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)


# ── Game Banner Widget ────────────────────────────────────────────────

class GameBannerWidget(QWidget):
    """Displays widescreen game banner matching Mockup 2."""

    banner_loaded = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(84)
        self._game_title = t("banner_select_game")
        self._source = ""
        self._appid = ""
        self._pid = None
        self._pixmap = None
        self._loading_appid = None

        self.banner_loaded.connect(self._on_banner_downloaded)
        Path(BANNER_CACHE_DIR).mkdir(parents=True, exist_ok=True)

    def set_game(self, title: str, source: str = "", appid: str = "", pid=None):
        self._game_title = title or t("banner_unknown_game")
        self._source = source or ""
        self._appid = str(appid).strip() if appid else ""
        self._pid = str(pid).strip() if pid else None
        self._pixmap = None

        if self._appid and self._appid.isdigit():
            cache_file = os.path.join(BANNER_CACHE_DIR, f"{self._appid}.jpg")
            if os.path.isfile(cache_file):
                self._pixmap = QPixmap(cache_file)
            else:
                self._load_steam_banner_async(self._appid)

        self.update()

    def _load_steam_banner_async(self, appid: str):
        if self._loading_appid == appid:
            return
        self._loading_appid = appid

        def fetch():
            try:
                url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
                dest = os.path.join(BANNER_CACHE_DIR, f"{appid}.jpg")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = response.read()
                    with open(dest, 'wb') as f:
                        f.write(data)
                self.banner_loaded.emit(appid, dest)
            except Exception:
                pass

        threading.Thread(target=fetch, daemon=True).start()

    def _on_banner_downloaded(self, appid: str, local_path: str):
        if self._appid == appid and os.path.isfile(local_path):
            self._pixmap = QPixmap(local_path)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, 10, 10)
        painter.setClipPath(clip_path)

        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            crop_x = (scaled.width() - self.width()) // 2
            crop_y = (scaled.height() - self.height()) // 2
            painter.drawPixmap(0, 0, scaled, crop_x, crop_y, self.width(), self.height())

            # Dark gradient overlay from bottom
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, QColor(0, 0, 0, 40))
            grad.setColorAt(0.5, QColor(0, 0, 0, 100))
            grad.setColorAt(1.0, QColor(16, 17, 23, 230))
            painter.fillRect(self.rect(), QBrush(grad))
        else:
            grad = QLinearGradient(0, 0, self.width(), self.height())
            grad.setColorAt(0.0, QColor(28, 30, 42))
            grad.setColorAt(0.5, QColor(22, 23, 31))
            grad.setColorAt(1.0, QColor(16, 17, 22))
            painter.fillRect(self.rect(), QBrush(grad))

            painter.setPen(QPen(QColor(99, 102, 241, 40), 1))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        # Top pills: Source (left) & live PID (right)
        if self._source or self._pid:
            pill_font = painter.font()
            pill_font.setPointSize(9)
            pill_font.setBold(True)
            painter.setFont(pill_font)
            pfm = painter.fontMetrics()

            if self._source:
                src_text = self._source
                sw = min(pfm.horizontalAdvance(src_text) + 16, self.width() - 120)
                srect = QRectF(12, 10, max(sw, 44), 20)
                painter.setBrush(QBrush(QColor(22, 23, 33, 195)))
                painter.setPen(QPen(QColor(129, 140, 248, 120), 1))
                painter.drawRoundedRect(srect, 10, 10)
                painter.setPen(QColor("#c7d2fe"))
                el_src = pfm.elidedText(src_text, Qt.TextElideMode.ElideRight, int(srect.width() - 12))
                painter.drawText(srect.toRect(), Qt.AlignmentFlag.AlignCenter, el_src)

            if self._pid:
                pid_text = f"PID {self._pid}"
                pw = pfm.horizontalAdvance(pid_text) + 16
                prect = QRectF(self.width() - pw - 12, 10, pw, 20)
                painter.setBrush(QBrush(QColor(16, 42, 34, 210)))
                painter.setPen(QPen(QColor(52, 211, 153, 140), 1))
                painter.drawRoundedRect(prect, 10, 10)
                painter.setPen(QColor("#6ee7b7"))
                painter.drawText(prect.toRect(), Qt.AlignmentFlag.AlignCenter, pid_text)

        # Title text positioned at bottom left
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPointSize(13)
        font.setBold(False)
        painter.setFont(font)

        title_rect = QRect(14, self.height() - 34, self.width() - 28, 24)
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(self._game_title, Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)


# ── WeMod Dialog ──────────────────────────────────────────────────────

class WeModDialog(QDialog):
    """Dedicated modern modal dialog for managing WeMod in a Wine prefix."""

    # Workers must communicate with Qt widgets through queued signals. Direct
    # widget access from Python threads is undefined and can crash the app.
    log_message = pyqtSignal(str)
    progress_changed = pyqtSignal(str, int)
    operation_finished = pyqtSignal()

    def __init__(self, prefix: str, game_name: str, parent=None):
        super().__init__(parent)
        self.prefix = prefix
        self.game_name = game_name
        self._operation_running = False

        self.setWindowTitle(t("wemod_dialog_title", name=game_name))
        self.setObjectName("wemodDialog")
        self.setMinimumSize(680, 520)
        self.setStyleSheet(styles.GLOBAL_STYLESHEET)

        self.log_message.connect(self.log)
        self.progress_changed.connect(self._update_progress)
        self.operation_finished.connect(self._finish_operation)

        self._init_ui()
        self._refresh_status()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QFrame()
        header.setStyleSheet(f"background-color: {styles.CARD_BG}; border-radius: 10px; padding: 12px;")
        h_layout = QVBoxLayout(header)
        h_layout.setSpacing(4)

        title_lbl = QLabel(t("wemod_title"))
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        h_layout.addWidget(title_lbl)

        pfx_lbl = QLabel(t("wemod_prefix_label", prefix=self.prefix))
        pfx_lbl.setStyleSheet(f"color: {styles.TEXT_SECONDARY}; font-size: 11px;")
        pfx_lbl.setWordWrap(True)
        h_layout.addWidget(pfx_lbl)

        self.status_lbl = QLabel(t("wemod_status_checking"))
        self.status_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #34d399;")
        h_layout.addWidget(self.status_lbl)

        layout.addWidget(header)

        dl_row = QHBoxLayout()
        self.dl_btn = QPushButton(t("wemod_btn_download"))
        self.dl_btn.setToolTip(t("tooltip_wemod_download"))
        self.dl_btn.clicked.connect(self._download_wemod)
        dl_row.addWidget(self.dl_btn)

        self.clear_cache_btn = QPushButton(t("wemod_btn_clear_cache"))
        self.clear_cache_btn.setToolTip(t("tooltip_wemod_clear_cache"))
        self.clear_cache_btn.clicked.connect(self._clear_cache)
        dl_row.addWidget(self.clear_cache_btn)

        dl_row.addStretch()
        layout.addLayout(dl_row)

        action_row = QHBoxLayout()
        self.install_btn = QPushButton(t("wemod_btn_install"))
        self.install_btn.setStyleSheet(f"background-color: {styles.ACCENT_COLOR}; color: #ffffff; font-weight: bold;")
        self.install_btn.setToolTip(t("tooltip_wemod_install"))
        self.install_btn.clicked.connect(self._install_built)
        action_row.addWidget(self.install_btn)

        self.uninstall_btn = QPushButton(t("wemod_btn_uninstall"))
        self.uninstall_btn.setToolTip(t("tooltip_wemod_uninstall"))
        self.uninstall_btn.clicked.connect(self._uninstall_wemod)
        action_row.addWidget(self.uninstall_btn)
        action_row.addStretch()

        layout.addLayout(action_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel(t("wemod_logs_header")))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            f"background-color: #14151c; color: #d4d4d8; "
            f"border: 1px solid {styles.BORDER_SUBTLE}; font-family: monospace; font-size: 11px;"
        )
        layout.addWidget(self.log_view, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        self.close_btn = QPushButton(t("btn_close"))
        self.close_btn.clicked.connect(self.accept)
        close_row.addWidget(self.close_btn)
        layout.addLayout(close_row)

    def log(self, msg: str):
        self.log_view.append(msg)

    def _update_progress(self, stage: str, percent: int):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(percent)

    def _set_operation_running(self, running: bool):
        self._operation_running = running
        for button in (
            self.dl_btn,
            self.clear_cache_btn,
            self.install_btn,
            self.uninstall_btn,
        ):
            button.setEnabled(not running)
        self.close_btn.setEnabled(not running)

    def _start_operation(self):
        if self._operation_running:
            return False
        self._set_operation_running(True)
        return True

    def _finish_operation(self):
        self._set_operation_running(False)
        self.progress_bar.setVisible(False)
        self._refresh_status()

    def closeEvent(self, event):
        if self._operation_running:
            event.ignore()
            return
        super().closeEvent(event)

    def _refresh_status(self):
        if self._operation_running:
            return

        downloaded = wm.is_wemod_downloaded()
        has_cache = os.path.isdir(wm.WEMOD_BIN_DIR)

        self.dl_btn.setEnabled(not downloaded)
        self.clear_cache_btn.setEnabled(has_cache)

        if not self.prefix or not os.path.isdir(self.prefix):
            st = t("wemod_status_prefix_missing")
            color = "#ef4444"
            self.install_btn.setEnabled(False)
            self.uninstall_btn.setEnabled(False)
        else:
            s = wm.get_status(self.prefix)
            self.install_btn.setEnabled(downloaded and s != "Rodando")
            self.uninstall_btn.setEnabled(s in ("Instalado", "Rodando"))
            self.clear_cache_btn.setEnabled(has_cache and s != "Rodando")

            if s == "Rodando":
                st = t("wemod_status_running")
                color = "#34d399"
            elif s == "Instalado":
                st = t("wemod_status_installed")
                color = "#60a5fa"
            else:
                st = t("wemod_status_not_installed")
                color = "#8e90a0"

        self.status_lbl.setText(f"Status: {st}")
        self.status_lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {color};")

    def _download_wemod(self):
        if not self._start_operation():
            return
        self.log(t("wemod_log_downloading"))

        def fetch():
            try:
                wm.download_wemod()
                self.log_message.emit(t("wemod_log_download_success"))
            except Exception as e:
                self.log_message.emit(t("wemod_log_download_error", error=e))
            finally:
                self.operation_finished.emit()

        threading.Thread(target=fetch, daemon=True).start()

    def _clear_cache(self):
        ans = QMessageBox.question(
            self,
            t("wemod_clear_cache_title"),
            t("wemod_clear_cache_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes or not self._start_operation():
            return

        self.log(t("wemod_log_clearing_cache"))

        def task():
            try:
                wm.clear_cache()
                self.log_message.emit(t("wemod_log_cache_cleared"))
            except Exception as e:
                self.log_message.emit(t("wemod_log_clear_cache_error", error=e))
            finally:
                self.operation_finished.emit()

        threading.Thread(target=task, daemon=True).start()

    def _install_built(self):
        if not self.prefix:
            return
        if not self._start_operation():
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log(t("wemod_log_installing_built", prefix=self.prefix))

        def task():
            try:
                ok = wm.install_built_prefix(
                    self.prefix,
                    log_callback=lambda m: self.log_message.emit(m),
                    progress_callback=lambda s, p: self.progress_changed.emit(s, p),
                )
                if ok:
                    self.log_message.emit(t("wemod_log_configuring_symlinks"))
                    wm.install_wemod_prefix(
                        self.prefix,
                        log_callback=lambda m: self.log_message.emit(m),
                        progress_callback=lambda s, p: self.progress_changed.emit(s, p),
                    )
                    self.log_message.emit(t("wemod_log_install_success"))
                else:
                    self.log_message.emit(t("wemod_log_install_failed"))
            except Exception as e:
                self.log_message.emit(t("wemod_log_unexpected_error", error=e))
            finally:
                self.operation_finished.emit()

        threading.Thread(target=task, daemon=True).start()

    def _uninstall_wemod(self):
        ans = QMessageBox.question(
            self,
            t("wemod_uninstall_title"),
            t("wemod_uninstall_msg", name=self.game_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            if not self._start_operation():
                return
            self.log(t("wemod_log_uninstalling"))

            def task():
                try:
                    wm.remove_wemod_prefix(self.prefix)
                    self.log_message.emit(t("wemod_log_uninstalled"))
                except Exception as e:
                    self.log_message.emit(t("wemod_log_uninstall_error", error=e))
                finally:
                    self.operation_finished.emit()

            threading.Thread(target=task, daemon=True).start()


# ── Settings Dialog ───────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """Settings dialog for Language, Trainers Folder, Cheat Engine Path, and Hidden Prefixes."""

    def __init__(self, config: dict, save_callback, parent=None, delete_prefix_callback=None):
        super().__init__(parent)
        self.config = config
        self.save_callback = save_callback
        self.delete_prefix_callback = delete_prefix_callback
        self._original_lang = i18n.get_language()

        self.setWindowTitle(t("settings_window_title"))
        self.setObjectName('settingsDialog')
        self.setMinimumSize(640, 580)
        self.setStyleSheet(styles.GLOBAL_STYLESHEET)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.title_lbl = QLabel(t("settings_header"))
        self.title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        layout.addWidget(self.title_lbl)

        # Language Selection Row
        self.lang_label = QLabel(t("settings_language_label"))
        layout.addWidget(self.lang_label)
        lang_row = QHBoxLayout()
        self.lang_combo = QComboBox()
        self.lang_combo.setObjectName('languageCombo')
        self.lang_combo.setMinimumSize(170, 34)
        self.lang_combo.setToolTip(t("tooltip_settings_lang"))
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("Português", "pt")
        self.lang_combo.addItem("Español", "es")

        curr_lang = self.config.get("language", i18n.get_language())
        idx = self.lang_combo.findData(curr_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        self.trainers_label = QLabel(t("settings_trainers_folder"))
        layout.addWidget(self.trainers_label)
        tr_row = QHBoxLayout()
        self.trainers_input = QLineEdit()
        self.trainers_input.setText(self.config.get("trainers_folder", ""))
        self.trainers_input.setPlaceholderText(t("settings_trainers_placeholder"))
        self.trainers_input.setToolTip(t("tooltip_settings_trainers_input"))
        tr_row.addWidget(self.trainers_input)

        self.browse_tr = QPushButton(t("settings_browse"))
        self.browse_tr.setObjectName('browseTrainers')
        self.browse_tr.setToolTip(t("settings_browse_trainers_tooltip"))
        self.browse_tr.clicked.connect(self._browse_trainers)
        tr_row.addWidget(self.browse_tr)
        layout.addLayout(tr_row)

        self.ce_label = QLabel(t("settings_ce_path"))
        layout.addWidget(self.ce_label)
        ce_row = QHBoxLayout()
        self.ce_input = QLineEdit()
        self.ce_input.setText(self.config.get("ce_path", ""))
        self.ce_input.setPlaceholderText(t("settings_ce_placeholder"))
        self.ce_input.setToolTip(t("tooltip_settings_ce_input"))
        ce_row.addWidget(self.ce_input)

        self.browse_ce = QPushButton(t("settings_browse"))
        self.browse_ce.setObjectName('browseCheatEngine')
        self.browse_ce.setToolTip(t("settings_browse_ce_tooltip"))
        self.browse_ce.clicked.connect(self._browse_ce)
        ce_row.addWidget(self.browse_ce)
        layout.addLayout(ce_row)

        self.hidden_label = QLabel(t("settings_hidden_prefixes"))
        layout.addWidget(self.hidden_label)
        self.hidden_list = QListWidget()
        self.hidden_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.hidden_list.setToolTip(t("tooltip_settings_hidden_list"))
        for pfx in self.config.get("hidden_prefixes", []):
            self.hidden_list.addItem(pfx)
        layout.addWidget(self.hidden_list, stretch=1)

        hidden_actions_row = QHBoxLayout()
        self.unhide_btn = QPushButton(t("settings_unhide_btn"))
        self.unhide_btn.setToolTip(t("tooltip_settings_unhide"))
        self.unhide_btn.clicked.connect(self._unhide_selected)
        hidden_actions_row.addWidget(self.unhide_btn)

        self.delete_hidden_btn = QPushButton(t("settings_delete_hidden_btn"))
        self.delete_hidden_btn.setObjectName("deleteHiddenBtn")
        self.delete_hidden_btn.setToolTip(t("settings_delete_hidden_tooltip"))
        self.delete_hidden_btn.clicked.connect(self._delete_hidden_selected)
        hidden_actions_row.addWidget(self.delete_hidden_btn)
        layout.addLayout(hidden_actions_row)

        self.logs_label = QLabel(t("settings_logs_folder"))
        layout.addWidget(self.logs_label)
        logs_box = QHBoxLayout()
        self.logs_path_lbl = QLabel(error_logger.get_logs_dir())
        self.logs_path_lbl.setStyleSheet("color: #9ca3af; font-family: monospace; font-size: 11px;")
        self.logs_path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        logs_box.addWidget(self.logs_path_lbl, stretch=1)
        self.open_logs_btn = QPushButton(t("settings_open_logs_btn"))
        self.open_logs_btn.setObjectName("openLogsBtn")
        self.open_logs_btn.setToolTip(t("settings_open_logs_tooltip"))
        self.open_logs_btn.clicked.connect(error_logger.open_logs_folder)
        logs_box.addWidget(self.open_logs_btn)
        layout.addLayout(logs_box)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.save_btn = QPushButton(t("settings_save_btn"))
        self.save_btn.setObjectName('saveSettings')
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)

        self.cancel_btn = QPushButton(t("settings_cancel_btn"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        layout.addLayout(btn_row)

    def _on_lang_changed(self, index):
        new_lang = self.lang_combo.currentData()
        if new_lang:
            i18n.set_language(new_lang)
            self.retranslate_ui()

    def retranslate_ui(self):
        self.setWindowTitle(t("settings_window_title"))
        self.title_lbl.setText(t("settings_header"))
        self.lang_label.setText(t("settings_language_label"))
        self.lang_combo.setToolTip(t("tooltip_settings_lang"))
        self.trainers_label.setText(t("settings_trainers_folder"))
        self.trainers_input.setPlaceholderText(t("settings_trainers_placeholder"))
        self.trainers_input.setToolTip(t("tooltip_settings_trainers_input"))
        self.browse_tr.setText(t("settings_browse"))
        self.browse_tr.setToolTip(t("settings_browse_trainers_tooltip"))
        self.ce_label.setText(t("settings_ce_path"))
        self.ce_input.setPlaceholderText(t("settings_ce_placeholder"))
        self.ce_input.setToolTip(t("tooltip_settings_ce_input"))
        self.browse_ce.setText(t("settings_browse"))
        self.browse_ce.setToolTip(t("settings_browse_ce_tooltip"))
        self.hidden_label.setText(t("settings_hidden_prefixes"))
        self.hidden_list.setToolTip(t("tooltip_settings_hidden_list"))
        self.unhide_btn.setText(t("settings_unhide_btn"))
        self.unhide_btn.setToolTip(t("tooltip_settings_unhide"))
        self.delete_hidden_btn.setText(t("settings_delete_hidden_btn"))
        self.delete_hidden_btn.setToolTip(t("settings_delete_hidden_tooltip"))
        self.logs_label.setText(t("settings_logs_folder"))
        self.open_logs_btn.setText(t("settings_open_logs_btn"))
        self.open_logs_btn.setToolTip(t("settings_open_logs_tooltip"))
        self.save_btn.setText(t("settings_save_btn"))
        self.cancel_btn.setText(t("settings_cancel_btn"))

    def _browse_trainers(self):
        d = QFileDialog.getExistingDirectory(self, t("settings_browse_trainers_title"), self.trainers_input.text() or os.path.expanduser('~'))
        if d:
            self.trainers_input.setText(d)

    def _browse_ce(self):
        f, _ = QFileDialog.getOpenFileName(
            self, t("settings_browse_ce_title"),
            os.path.expanduser('~'),
            t("dialog_filter_exe")
        )
        if f:
            self.ce_input.setText(f)

    def _unhide_selected(self):
        sel = self.hidden_list.selectedItems()
        if not sel:
            return
        for item in sel:
            row = self.hidden_list.row(item)
            self.hidden_list.takeItem(row)

    def _delete_hidden_selected(self):
        sel = self.hidden_list.selectedItems()
        if not sel:
            return
        for item in list(sel):
            pfx = item.text()
            deleted = False
            if self.delete_prefix_callback:
                deleted = bool(self.delete_prefix_callback(pfx))
                if deleted and self.parent() is not None and hasattr(self.parent(), "config"):
                    self.config.update(self.parent().config)
            else:
                ans = QMessageBox.question(
                    self, t("msg_confirm_title"),
                    t("msg_confirm_delete_pfx", target=pfx),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ans == QMessageBox.StandardButton.Yes:
                    import shutil
                    if os.path.isdir(pfx):
                        shutil.rmtree(pfx, ignore_errors=True)
                    deleted = True
                    if "hidden_prefixes" in self.config:
                        self.config["hidden_prefixes"] = [
                            h for h in self.config["hidden_prefixes"] if h != pfx
                        ]
                        self.save_callback(self.config)
            if deleted:
                row = self.hidden_list.row(item)
                self.hidden_list.takeItem(row)

    def _save(self):
        selected_lang = self.lang_combo.currentData() or i18n.DEFAULT_LANGUAGE
        self.config["language"] = selected_lang
        i18n.set_language(selected_lang)
        self.config["trainers_folder"] = self.trainers_input.text().strip()
        self.config["ce_path"] = self.ce_input.text().strip()

        hidden = []
        for i in range(self.hidden_list.count()):
            hidden.append(self.hidden_list.item(i).text())
        self.config["hidden_prefixes"] = hidden

        self.save_callback(self.config)
        self.accept()

    def reject(self):
        i18n.set_language(self._original_lang)
        super().reject()
