"""
run.py
======
Lanceur de l'application (utilisé aussi comme point d'entrée PyInstaller).

    python run.py
"""

from pdf_manager.main import main

if __name__ == "__main__":
    raise SystemExit(main())
