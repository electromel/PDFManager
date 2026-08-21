"""
main.py
=======
Point d'entrée de l'application PDF Manager.

Les chemins de PDF passés en ligne de commande sont ouverts au démarrage :
c'est ce qui permet le « Ouvrir avec » de l'explorateur Windows (ainsi que
le glisser-déposer d'un PDF sur PDFManager.exe).
"""

from __future__ import annotations

import os
import sys
from typing import List


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


def _pdf_args(argv: List[str]) -> List[str]:
    """Chemins de PDF existants passés en argument (« Ouvrir avec » Windows).

    Les options éventuelles (commençant par « - ») et les fichiers non PDF ou
    introuvables sont ignorés ; les chemins relatifs sont rendus absolus car
    l'explorateur ne lance pas forcément l'application depuis leur dossier."""
    paths: List[str] = []
    for arg in argv:
        if arg.startswith("-"):
            continue
        path = os.path.abspath(arg)
        if path.lower().endswith(".pdf") and os.path.isfile(path):
            paths.append(path)
    return paths


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
    startup = _pdf_args(sys.argv[1:])
    if startup:
        win.open_files(startup)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
