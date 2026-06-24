"""
main.py
=======
Point d'entrée de l'application PDF Manager.
"""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from .library import LibraryWindow
    from .theme import APP_QSS

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Manager")
    app.setStyleSheet(APP_QSS)
    win = LibraryWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
