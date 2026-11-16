"""
styles.py - Exact modern dark stylesheet reproducing Mockup 2 ('Desktop Pro').
"""

import os

CHEVRON_PATH = os.path.expanduser('~/.cache/action_shark/chevron_down.png')

# Exact Mockup 2 Palette
BG_DARK = "#141418"
PANEL_BG = "#16171d"
CARD_BG = "#1e1f29"
BORDER_COLOR = "#2b2d3c"
BORDER_SUBTLE = "rgba(255, 255, 255, 0.07)"

TEXT_PRIMARY = "#f3f4f6"
TEXT_SECONDARY = "#8e90a0"
TEXT_MUTED = "#6b6e80"

ACCENT_COLOR = "#5850ec"
ACCENT_HOVER = "#6860f5"
ACCENT_ACTIVE = "#4942cb"

ROW_BG_1 = "#141418"
ROW_BG_2 = "#181920"
ROW_SELECTED = "#252738"
ROW_SELECTED_BORDER = "rgba(88, 80, 236, 0.45)"

STATUS_ACTIVE_TEXT = "#34d399"
STATUS_ACTIVE_BG = "rgba(34, 197, 94, 0.16)"
STATUS_IDLE_TEXT = "#8e90a0"
STATUS_IDLE_BG = "rgba(255, 255, 255, 0.05)"


GLOBAL_STYLESHEET = f"""
/* ── Global App Window & Typography ── */
QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    font-family: 'Segoe UI', 'Inter', 'Cantarell', 'Ubuntu', sans-serif;
    font-size: 13px;
    selection-background-color: {ACCENT_COLOR};
    selection-color: #ffffff;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background-color: {BORDER_SUBTLE};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

QFrame#surface {{
    background-color: {PANEL_BG};
    border: 1px solid #0d0e13;
    border-radius: 12px;
}}

/* ── Panels & Containers ── */
QFrame#inspectorPanel {{
    background-color: #191a21;
    border-left: 1px solid {BORDER_SUBTLE};
}}

QFrame#tableContainer {{
    background-color: {BG_DARK};
    border: none;
}}

QFrame#topBar {{
    background-color: {BG_DARK};
    border-bottom: 1px solid {BORDER_SUBTLE};
    padding: 6px 14px;
}}

QFrame#leftHeader {{
    background-color: transparent;
    border: none;
}}

/* ── Tree / Table Widget ── */
QTreeWidget {{
    background-color: {ROW_BG_1};
    alternate-background-color: {ROW_BG_2};
    border: none;
    outline: none;
    padding: 0px;
}}

QTreeWidget::item {{
    height: 40px;
    padding: 0px 12px;
    color: {TEXT_PRIMARY};
    border: none;
}}

QTreeWidget::item:hover {{
    background-color: rgba(255, 255, 255, 0.03);
}}

QTreeWidget::item:selected {{
    background-color: #3a3d62;
    color: #ffffff;
    border-top: 1px solid {ROW_SELECTED_BORDER};
    border-bottom: 1px solid {ROW_SELECTED_BORDER};
}}

QHeaderView::section {{
    background-color: {BG_DARK};
    color: {TEXT_SECONDARY};
    font-size: 14px;
    font-weight: 500;
    border: none;
    border-bottom: 1px solid {BORDER_SUBTLE};
    padding: 8px 12px;
}}

/* ── Inputs ── */
QLineEdit {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}}

QLineEdit:focus {{
    border: 1px solid {ACCENT_COLOR};
    background-color: #222430;
}}

QLineEdit:disabled {{
    color: {TEXT_MUTED};
    background-color: #171821;
}}

/* ── Search Input (Pill Shaped) ── */
QLineEdit#searchBar {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 14px;
    /* Qt applies this width to the text box before its 14px paddings. */
    min-width: 486px;
    max-width: 486px;
    /* Qt adds the vertical padding to this content height. */
    max-height: 21px;
}}

QLineEdit#searchBar:focus {{
    border: 1px solid {ACCENT_COLOR};
    border-radius: 8px;
    background-color: #222430;
}}

/* ── Combo Box ── */
QComboBox {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 14px;
    min-height: 22px;
}}

QComboBox:focus {{
    border: 1px solid {ACCENT_COLOR};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 32px;
    border-left: none;
}}

QComboBox::down-arrow {{
    image: url("{CHEVRON_PATH}");
    width: 12px;
    height: 12px;
    margin-right: 10px;
}}

QComboBox QAbstractItemView {{
    background-color: {PANEL_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 8px;
    selection-background-color: {ROW_SELECTED};
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: #262835;
    border-color: rgba(255, 255, 255, 0.15);
}}

QPushButton:pressed {{
    background-color: #1a1b23;
}}

/* Primary Launch Trainer Button (Exact Mockup Vibrant Blue) */
QPushButton#launchTrainerBtn {{
    background-color: {ACCENT_COLOR};
    color: #ffffff;
    border: none;
    border-radius: 20px;
    padding: 8px 24px;
    font-size: 14px;
    font-weight: 600;
    min-height: 22px;
}}

QPushButton#launchTrainerBtn:hover {{
    background-color: {ACCENT_HOVER};
}}

QPushButton#launchTrainerBtn:pressed {{
    background-color: {ACCENT_ACTIVE};
}}

/* Browse Button */
QPushButton#browseBtn {{
    background-color: {ACCENT_COLOR};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
}}

QPushButton#browseBtn:hover {{
    background-color: {ACCENT_HOVER};
}}

QPushButton#browseBtn:pressed {{
    background-color: {ACCENT_ACTIVE};
}}

/* Quick Action Buttons (Grid) */
QPushButton#quickActionBtn {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 13px;
    font-weight: 500;
    text-align: left;
    min-height: 24px;
}}

QPushButton#headerIconBtn, QPushButton#windowIconBtn {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px;
}}

QPushButton#headerIconBtn:hover, QPushButton#windowIconBtn:hover {{
    background-color: rgba(255, 255, 255, 0.08);
}}

QPushButton#windowIconBtn:last-child:hover {{
    background-color: rgba(239, 68, 68, 0.18);
}}

QPushButton#quickActionBtn:hover {{
    background-color: #262835;
    border-color: rgba(255, 255, 255, 0.18);
}}

QPushButton#quickActionBtn:pressed {{
    background-color: #1a1b23;
}}

/* Filter Chips */
QPushButton#chipBtn {{
    background-color: {CARD_BG};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 14px;
    padding: 4px 14px;
    font-size: 12px;
    font-weight: 600;
}}

QPushButton#chipBtn:hover {{
    background-color: #262835;
    color: {TEXT_PRIMARY};
    border-color: #3f4258;
}}

QPushButton#chipBtn[selected="true"] {{
    background-color: #37384e;
    color: #ffffff;
    border: 1px solid {ACCENT_COLOR};
}}

/* Navigation Segmented Tab Buttons (Active Processes vs Installed Prefixes) */
QPushButton#navTabBtn {{
    background-color: transparent;
    color: #9ca3af;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton#navTabBtn:hover {{
    color: #f3f4f6;
    background-color: rgba(255, 255, 255, 0.05);
}}

QPushButton#navTabBtn[selected="true"] {{
    background-color: #272836;
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.12);
}}

/* Top Bar Icon Buttons (Settings, Refresh, Filter) */
QPushButton.iconBtn {{
    background-color: {CARD_BG};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
}}

QPushButton.iconBtn:hover {{
    background-color: #262835;
    color: {TEXT_PRIMARY};
    border-color: rgba(255, 255, 255, 0.15);
}}

/* ── Scrollbars ── */
QScrollBar:vertical {{
    background-color: transparent;
    width: 6px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background-color: rgba(255, 255, 255, 0.12);
    min-height: 30px;
    border-radius: 3px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: rgba(255, 255, 255, 0.22);
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 6px;
    margin: 0px;
}}

QScrollBar::handle:horizontal {{
    background-color: rgba(255, 255, 255, 0.12);
    min-width: 30px;
    border-radius: 3px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: rgba(255, 255, 255, 0.22);
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Menus (Right-Click Context Menus) ── */
QMenu {{
    background-color: #202127;
    color: #eeeeef;
    border: 1px solid #3a3b46;
    border-radius: 8px;
    padding: 6px 4px;
}}

QMenu::item {{
    background-color: transparent;
    color: #eeeeef;
    padding: 7px 28px 7px 14px;
    border-radius: 6px;
    margin: 2px 4px;
}}

QMenu::item:selected {{
    background-color: #3b3d59;
    color: #ffffff;
}}

QMenu::item:disabled {{
    color: #6c6d7a;
    background-color: transparent;
}}

QMenu::separator {{
    height: 1px;
    background-color: #353640;
    margin: 6px 8px;
}}

/* ── Dialogs ── */
QDialog {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
}}

QTextEdit {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
    padding: 8px;
}}

QProgressBar {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    text-align: center;
    color: {TEXT_PRIMARY};
    font-weight: 600;
}}

QProgressBar::chunk {{
    background-color: {ACCENT_COLOR};
    border-radius: 5px;
}}
"""

# Final reference rules, deliberately using one installed font family so Qt
# does not substitute a condensed/bold desktop font for the CSS fallback list.
GLOBAL_STYLESHEET += """
QWidget { background: transparent; color: #eeeeef; font-family: 'Noto Sans'; font-size: 15px; font-weight: 400; }
QFrame#tableContainer { background: #18191e; border-top-left-radius: 11px; border-bottom-left-radius: 11px; }
QFrame#inspectorPanel { background: #25262d; border: none; border-top-right-radius: 11px; border-bottom-right-radius: 11px; }
QSplitter::handle { background: #34353f; width: 1px; }
QTreeWidget { background: #18191e; border: none; outline: none; }
QTreeWidget::item { height: 40px; padding: 0; border: none; }
QHeaderView::section { background: #18191e; color: #bcbcc3; border: none; border-right: 1px solid #34353f; padding: 7px 12px; font-size: 15px; font-weight: 400; }
QLineEdit, QComboBox { background: #202127; border: 1px solid #3a3b46; border-radius: 8px; padding: 5px 11px; font-size: 15px; }
QLineEdit#searchBar { background: #24252d; border-color: #393a46; padding: 5px 8px; min-width: 0; max-width: 16777215; min-height: 0; max-height: 16777215; font-size: 15px; }
QComboBox { border-color: #8181c9; min-height: 0; }
QPushButton#chipBtn { padding: 0 12px; font-size: 15px; font-weight: 400; }
QPushButton#quickActionBtn { padding: 4px 8px; font-size: 12px; font-weight: 500; min-height: 0; }
QFrame#trainerField { background: #202127; border: 1px solid #3a3b46; border-radius: 9px; }
QFrame#wineVersionFrame { background: #202127; border: 1px solid #3a3b46; border-radius: 8px; }
QLineEdit#trainerInput { background: transparent; border: none; padding: 0 7px; }
QFrame#divider { background: #353640; }
QDialog#settingsDialog { background: #25262d; }
QDialog#settingsDialog QPushButton { background: #25262d; border: 1px solid #3a3b46; }
QDialog#settingsDialog QPushButton:hover { background: #32333e; }
QDialog#settingsDialog QListWidget { background: #202127; border: 1px solid #3a3b46; border-radius: 8px; padding: 4px; }
QDialog#settingsDialog QListWidget::item:selected { background: #3b3d59; }
QDialog#settingsDialog QPushButton#saveSettings { background: #696cde; border-color: #777ae7; color: white; }
QDialog#settingsDialog QPushButton#saveSettings:hover { background: #777ae7; }
"""

# Context Menu specific rules - placed after generic QWidget rules to prevent transparent override
MENU_STYLESHEET = """
QMenu {
    background-color: #202127;
    color: #eeeeef;
    border: 1px solid #3a3b46;
    border-radius: 8px;
    padding: 6px 4px;
}
QMenu::item {
    background-color: transparent;
    color: #eeeeef;
    padding: 7px 28px 7px 14px;
    border-radius: 6px;
    margin: 2px 4px;
}
QMenu::item:selected {
    background-color: #3b3d59;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #6c6d7a;
    background-color: transparent;
}
QMenu::separator {
    height: 1px;
    background-color: #353640;
    margin: 6px 8px;
}
"""

GLOBAL_STYLESHEET += MENU_STYLESHEET
