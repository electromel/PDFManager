"""
theme.py
========
Feuille de style (QSS) globale pour un rendu moderne et lisible.
"""

APP_QSS = """
* {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 14px;
}

QMainWindow, QWidget {
    background: #f4f6f9;
    color: #1f2733;
}

/* ---- Barre d'outils ---- */
QToolBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #e2e6ee;
    padding: 8px 10px;
    spacing: 8px;
}
QToolBar QToolButton {
    background: #f0f3f9;
    border: 1px solid #dce1ea;
    border-radius: 8px;
    padding: 9px 14px;
    margin: 0 2px;
    font-size: 14px;
    font-weight: 600;
    color: #243044;
}
QToolBar QToolButton:hover {
    background: #e6efff;
    border-color: #2d7ef7;
    color: #1763d6;
}
QToolBar QToolButton:pressed {
    background: #d6e6ff;
}
QToolBar QToolButton::menu-indicator {
    subcontrol-position: right center;
    right: 6px;
}
/* Sélecteur d'affichage (boutons radio reliés) */
#ModeSwitch {
    background: #f0f3f9;
    border: 1px solid #c3ccd9;
    border-radius: 10px;
}
#ModeSwitch QToolButton {
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 6px 12px;
    margin: 0;
}
#ModeSwitch QToolButton:hover { background: #e6efff; }
#ModeSwitch QToolButton:checked {
    background: #2d7ef7;
    color: #ffffff;
}
QToolBar QLabel {
    color: #5b6675;
    font-weight: 600;
    padding: 0 4px;
}
QToolBar::separator {
    background: #e2e6ee;
    width: 1px;
    margin: 4px 8px;
}

/* ---- Combobox ---- */
QComboBox {
    background: #ffffff;
    border: 1px solid #dce1ea;
    border-radius: 8px;
    padding: 7px 12px;
    min-height: 20px;
}
QComboBox:hover { border-color: #2d7ef7; }
QComboBox::drop-down { border: none; width: 22px; }

/* ---- Champ de recherche ---- */
QLineEdit {
    background: #ffffff;
    border: 1px solid #dce1ea;
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: #2d7ef7;
}
QLineEdit:focus { border: 1px solid #2d7ef7; }

/* ---- Boutons ---- */
QPushButton {
    background: #2d7ef7;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 600;
}
QPushButton:hover { background: #1763d6; }
QPushButton:pressed { background: #1455bd; }

/* ---- Zones de défilement ---- */
QScrollArea { border: none; }
QScrollBar:vertical {
    background: transparent; width: 12px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: #c3ccd9; border-radius: 6px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #9aa7ba; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }

/* ---- Listes (vignettes de pages) ---- */
QListWidget {
    background: #f4f6f9;
    border: none;
    outline: 0;
}
QListWidget::item {
    color: #3a4658;
    border: 2px solid transparent;
    border-radius: 10px;
    padding: 6px;
    margin: 4px;
}
QListWidget::item:selected {
    background: #e6efff;
    border: 2px solid #2d7ef7;
    color: #1763d6;
}

/* ---- Barre de statut ---- */
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #e2e6ee;
    color: #5b6675;
}

/* ---- Boîtes de dialogue ---- */
QMessageBox, QProgressDialog, QDialog { background: #ffffff; }

QMenu {
    background: #ffffff;
    border: 1px solid #e2e6ee;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item { padding: 8px 22px; border-radius: 6px; }
QMenu::item:selected { background: #e6efff; color: #1763d6; }
"""
