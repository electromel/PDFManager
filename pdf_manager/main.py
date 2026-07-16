"""
main.py
=======
Point d'entrée de l'application PDF Manager.
"""

from __future__ import annotations

import os
import sys


def _app_icon_path() -> str:
    """Chemin de l'icône de l'application (source ou exécutable PyInstaller)."""
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "assets", "app_icon.ico")


def _light_palette():
    """Palette claire explicite : l'application a un thème clair (QSS), il ne
    faut donc pas hériter de la palette sombre de Windows (mode sombre), qui
    rendait notamment les infobulles et textes de repli illisibles."""
    from PySide6.QtGui import QPalette, QColor

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#ECEEF2"))
    pal.setColor(QPalette.WindowText, QColor("#0D1526"))
    pal.setColor(QPalette.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.AlternateBase, QColor("#F4F5F8"))
    pal.setColor(QPalette.Text, QColor("#0D1526"))
    pal.setColor(QPalette.PlaceholderText, QColor("#8F99AD"))
    pal.setColor(QPalette.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ButtonText, QColor("#0D1526"))
    pal.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipText, QColor("#0D1526"))
    pal.setColor(QPalette.Highlight, QColor("#1B3461"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Link, QColor("#1B3461"))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#8F99AD"))
    return pal


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from .library import LibraryWindow
    from .theme import APP_QSS

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Manager")
    icon_path = _app_icon_path()
    if os.path.isfile(icon_path):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))
    # Style neutre + palette claire : rendu identique quel que soit le mode
    # (clair/sombre) de Windows.
    app.setStyle("Fusion")
    app.setPalette(_light_palette())
    app.setStyleSheet(APP_QSS)
    win = LibraryWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
