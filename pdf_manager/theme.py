"""
theme.py
========
Feuille de style (QSS) globale — Precision Tools design system.

Palette :
  surface-base    #ECEEF2  fond principal (gris bleuté froid)
  surface-card    #FFFFFF  cartes / surfaces élevées
  surface-thumb   #F4F5F8  fond des vignettes PDF
  ink-100         #0D1526  texte principal
  ink-60          #4B5675  texte secondaire
  ink-30          #8F99AD  métadonnées / inactif
  accent-navy     #1B3461  action primaire / survol spine
  accent-gold     #B8892C  sélection / badges
  accent-gold-bg  #FEF8EE  fond état sélectionné
  border          #D5D9E2  trait neutre
  status-bg       #0D1526  fond barre de statut (inversé)
"""

APP_QSS = """

* {
    font-family: "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
    color: #0D1526;
}

QMainWindow, QWidget {
    background: #ECEEF2;
    color: #0D1526;
}

/* ═══ TOOLBAR ════════════════════════════════════════════════════ */

QToolBar {
    background: #FFFFFF;
    border: none;
    border-bottom: 1px solid #D5D9E2;
    padding: 5px 12px;
    spacing: 2px;
}

QToolBar QToolButton {
    background: transparent;
    border: none;
    border-radius: 2px;
    padding: 7px 11px;
    margin: 0 1px;
    font-size: 12px;
    font-weight: 600;
    color: #1B3461;
}

QToolBar QToolButton:hover {
    background: #EEF0F5;
    color: #0D1526;
}

QToolBar QToolButton:pressed {
    background: #DDE1EB;
}

QToolBar QToolButton::menu-indicator {
    subcontrol-position: right center;
    right: 4px;
}

#ModeSwitch {
    background: #EEF0F5;
    border: 1px solid #D5D9E2;
    border-radius: 2px;
}

#ModeSwitch QToolButton {
    background: transparent;
    border: none;
    border-radius: 1px;
    padding: 5px 9px;
    margin: 0;
}

#ModeSwitch QToolButton:hover {
    background: #DDE1EB;
}

#ModeSwitch QToolButton:checked {
    background: #1B3461;
    color: #FFFFFF;
}

QToolBar QLabel {
    color: #4B5675;
    font-weight: 600;
    font-size: 11px;
    padding: 0 4px;
}

QToolBar::separator {
    background: #D5D9E2;
    width: 1px;
    margin: 5px 6px;
}

/* ═══ INPUTS ══════════════════════════════════════════════════════ */

QComboBox {
    background: #FFFFFF;
    border: 1px solid #D5D9E2;
    border-radius: 2px;
    padding: 6px 10px;
    min-height: 20px;
    color: #0D1526;
}

QComboBox:hover { border-color: #1B3461; }
QComboBox::drop-down { border: none; width: 20px; }

QLineEdit {
    background: #FFFFFF;
    border: 1px solid #D5D9E2;
    border-radius: 2px;
    padding: 6px 10px;
    color: #0D1526;
    selection-background-color: #1B3461;
}

QLineEdit:focus {
    border-color: #1B3461;
}

/* ═══ BUTTONS ══════════════════════════════════════════════════════ */

QPushButton {
    background: #1B3461;
    color: #FFFFFF;
    border: none;
    border-radius: 2px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton:hover { background: #243E76; }
QPushButton:pressed { background: #0D1526; }

/* ═══ SCROLL BARS ══════════════════════════════════════════════════ */

QScrollArea { border: none; background: transparent; }

QScrollBar:vertical {
    background: transparent;
    width: 7px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #C0C8D5;
    border-radius: 3px;
    min-height: 28px;
}

QScrollBar::handle:vertical:hover { background: #8F99AD; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: transparent;
    height: 7px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #C0C8D5;
    border-radius: 3px;
    min-width: 28px;
}

QScrollBar::handle:horizontal:hover { background: #8F99AD; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ═══ LIST (vignettes viewer) ══════════════════════════════════════ */

QListWidget {
    background: #ECEEF2;
    border: none;
    outline: 0;
}

QListWidget::item {
    color: #0D1526;
    border: 1px solid transparent;
    border-radius: 1px;
    padding: 6px;
    margin: 4px;
}

QListWidget::item:selected {
    background: #FEF8EE;
    border: 1px solid #B8892C;
    color: #0D1526;
}

/* ═══ STATUS BAR (inversé) ═════════════════════════════════════════ */

QStatusBar {
    background: #0D1526;
    border-top: none;
    color: #8F99AD;
    font-size: 11px;
    padding: 2px 8px;
}

/* ═══ TABS ═════════════════════════════════════════════════════════ */

QTabWidget::pane {
    border: none;
    background: #FFFFFF;
}

QTabBar {
    background: #ECEEF2;
}

QTabBar::tab {
    background: #E0E3EA;
    color: #4B5675;
    border: none;
    border-top: 2px solid transparent;
    border-radius: 0;
    padding: 7px 16px;
    margin-right: 1px;
    font-size: 12px;
    font-weight: 500;
    min-width: 80px;
}

QTabBar::tab:selected {
    background: #FFFFFF;
    color: #0D1526;
    border-top: 2px solid #1B3461;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background: #D5D9E2;
    color: #0D1526;
}

/* ═══ DIALOGS ══════════════════════════════════════════════════════ */

QMessageBox, QProgressDialog, QDialog { background: #FFFFFF; }

/* ═══ MENUS ════════════════════════════════════════════════════════ */

QMenu {
    background: #FFFFFF;
    border: 1px solid #D5D9E2;
    border-radius: 0;
    padding: 4px 0;
}

QMenu::item { padding: 7px 20px; border-radius: 0; }
QMenu::item:selected { background: #EEF0F5; color: #0D1526; }

QMenu::separator {
    height: 1px;
    background: #E0E3EA;
    margin: 3px 8px;
}

/* ═══ SPLITTER ══════════════════════════════════════════════════════ */

QSplitter::handle {
    background: #D5D9E2;
    width: 1px;
}
"""
