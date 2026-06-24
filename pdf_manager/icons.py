"""
icons.py
========
Jeu d'icônes vectorielles (style Feather) générées à la volée depuis du SVG
intégré : aucun fichier externe, fonctionne tel quel dans l'exécutable.

Usage : icons.icon("save")  -> QIcon
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter

try:
    from PySide6.QtSvg import QSvgRenderer
    _HAS_SVG = True
except Exception:  # pragma: no cover
    _HAS_SVG = False

# Corps SVG (24x24) de chaque icône.
_ICONS = {
    "add":        '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "file-plus":  '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
                  '<polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/>'
                  '<line x1="9" y1="15" x2="15" y2="15"/>',
    "merge":      '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
                  '<polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "eye":        '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>'
                  '<circle cx="12" cy="12" r="3"/>',
    "check":      '<polyline points="9 11 12 14 22 4"/>'
                  '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "trash":      '<polyline points="3 6 5 6 21 6"/>'
                  '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
                  '<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
    "search":     '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "ocr":        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
                  '<polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/>'
                  '<line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>',
    "minus":      '<line x1="5" y1="12" x2="19" y2="12"/>',
    "plus":       '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "fit":        '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/>'
                  '<path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "rotate-cw":  '<polyline points="23 4 23 10 17 10"/>'
                  '<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    "rotate-ccw": '<polyline points="1 4 1 10 7 10"/>'
                  '<path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    "save":       '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
                  '<polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
    "rows":       '<rect x="6" y="3" width="12" height="7" rx="1"/>'
                  '<rect x="6" y="14" width="12" height="7" rx="1"/>',
    "grid":       '<rect x="3" y="3" width="7" height="7" rx="1"/>'
                  '<rect x="14" y="3" width="7" height="7" rx="1"/>'
                  '<rect x="3" y="14" width="7" height="7" rx="1"/>'
                  '<rect x="14" y="14" width="7" height="7" rx="1"/>',
    "edit":       '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
                  '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
}

_DEFAULT_COLOR = "#243044"


def _svg_bytes(name: str, color: str) -> QByteArray:
    body = _ICONS.get(name, "")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    return QByteArray(svg.encode("utf-8"))


def icon(name: str, color: str = _DEFAULT_COLOR, size: int = 22) -> QIcon:
    """Retourne un QIcon pour l'icône demandée (vide si SVG indisponible)."""
    if not _HAS_SVG or name not in _ICONS:
        return QIcon()
    renderer = QSvgRenderer(_svg_bytes(name, color))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)
