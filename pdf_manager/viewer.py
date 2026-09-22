"""
viewer.py  (variante Tesseract)
===============================
Visionneuse et éditeur d'un document PDF.

Ouverture (double-clic) :
- 1 page  -> contenu en grand, avec zoom ;
- plusieurs pages -> pages en continu (par défaut) ou vignettes, avec zoom.

Édition (mode vignettes) :
- sélection multiple de pages (Ctrl/Maj + clic) ;
- rotation : pages sélectionnées, ou tout le document si rien n'est sélectionné ;
- suppression des pages sélectionnées (bouton corbeille ou touche Suppr) ;
- réorganisation par glisser-déposer : pendant le glisser, une barre bleue
  entre deux vignettes montre précisément où les pages seront insérées ;
- copier / couper / coller de pages (Ctrl+C/X/V), y compris vers un autre
  document ouvert dans un autre onglet ; un clic entre deux vignettes fixe
  le point d'insertion du collage (barre dorée) ;
- clic droit : pivoter / copier / coller / supprimer / découper.

Édition (mode continu) :
- réorganisation par glisser-déposer (glisser une page — ou la sélection —
  et la déposer sur la ligne entre deux pages) ;
- point d'insertion pour le collage : cliquer sur la ligne entre deux pages
  la sélectionne (ligne dorée) ; Ctrl+V colle alors à cet endroit précis.

Annotation (mode continu) — six outils réunis dans un bloc de la barre
d'outils ; ils s'excluent mutuellement et se quittent par Échap :
- reprise : clic sur une annotation pour la sélectionner, glisser pour la
  déplacer, double-clic pour changer ses attributs, Suppr pour l'effacer
  (une seule annotation, sans toucher aux autres) ;
- sélection de texte : glisser sur le texte du document, puis Ctrl+C pour le
  copier ou clic droit pour le surligner (PDF texte uniquement) ;
- surligneur : « Sélection » (glisser sur du texte : chaque mot est surligné
  comme dans Acrobat ; sur une image ou une page scannée : aplat teinté) ou
  « Marqueur » (trait libre, qui fonctionne aussi sur un PDF image) ;
- texte : clic pour poser un texte, double-clic sur un texte existant pour le
  modifier (contenu, police, corps, couleur, fond), glisser pour le déplacer ;
- dessin : main levée, ligne droite, flèche, rectangle ou ellipse, avec
  couleur, épaisseur et remplissage au choix ;
- cases à cocher : clic sur une case de formulaire pour la (dé)cocher, ou
  pose d'une coche dessinée sur une case imprimée (PDF image).
Clic droit sur une page : modifier / déplacer / supprimer l'annotation sous le
curseur, agir sur la sélection de texte, ou effacer une famille d'annotations.
Toutes sont de vraies annotations PDF, conservées à l'enregistrement et
modifiables d'une session à l'autre.

Le document est édité en mémoire ; « Enregistrer sous… » écrit un nouveau PDF
compressé (proposition de nom, option de suppression de la source). OCR possible.
"""

from __future__ import annotations

import math
import os
import tempfile
import time
from typing import List, Optional

import fitz
from PySide6.QtCore import Qt, QMimeData, QPointF, QRect, QSize, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QDrag, QKeySequence, QMouseEvent, QPainter,
    QPainterPath, QPen, QPixmap, QPolygonF, QIcon,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QListWidgetItem, QListView,
    QToolBar, QFileDialog, QMessageBox, QStackedWidget, QScrollArea, QWidget,
    QVBoxLayout, QLabel, QMenu, QProgressDialog, QComboBox, QToolButton,
    QButtonGroup, QFrame, QHBoxLayout, QDialog, QDialogButtonBox, QFormLayout,
    QPlainTextEdit, QCheckBox,
)

from . import pdf_ops, ocr, icons, printing

# Presse-papiers de pages, partagé par toutes les visionneuses : permet de
# copier/couper des pages d'un document et de les coller dans le même
# document ou dans un autre (onglet différent). Les pages sont stockées en
# octets PDF autonomes : la source peut être modifiée ou fermée ensuite.
_PAGE_CLIPBOARD = {"data": None, "count": 0, "source": ""}

PAGE_THUMB = 230
CONT_BASE = 780
ZOOM_MIN = 0.25
ZOOM_MAX = 5.0

# Type MIME interne pour le glisser-déposer de pages en mode continu.
_MIME_PAGES = "application/x-pdfmanager-pages"

# Outils d'annotation. Un seul est actif à la fois (None = pas d'outil : les
# clics servent alors à sélectionner et à réordonner les pages).
TOOL_PICK = "pick"               # reprendre une annotation : déplacer, modifier
TOOL_TEXT_SELECT = "text_select" # sélectionner le texte du document
TOOL_HL_SELECT = "hl_select"     # surligneur : glisser sur du texte ou une zone
TOOL_HL_PEN = "hl_pen"           # surligneur : trait de marqueur à main levée
TOOL_TEXT = "text"               # poser / modifier / déplacer un texte
TOOL_CHECK = "check"             # cocher une case (formulaire ou imprimée)
TOOL_INK = "ink"                 # dessin à main levée
TOOL_LINE = "line"
TOOL_ARROW = "arrow"
TOOL_RECT = "rect"
TOOL_ELLIPSE = "ellipse"

DRAW_TOOLS = (TOOL_INK, TOOL_LINE, TOOL_ARROW, TOOL_RECT, TOOL_ELLIPSE)
FREEHAND_TOOLS = (TOOL_INK, TOOL_HL_PEN)

# Couleur de la sélection de texte et des poignées de l'annotation reprise.
SELECT_COLOR = QColor(27, 52, 97)

# Nom donné à chaque famille d'annotation dans les messages et les menus.
FAMILY_LABELS = {"text": "Texte", "draw": "Tracé", "highlight": "Surlignage"}

# Libellé et icône de chaque forme du menu « Dessiner ».
DRAW_SHAPES = (
    (TOOL_INK, "Main levée", "pen"),
    (TOOL_LINE, "Ligne droite", "line"),
    (TOOL_ARROW, "Flèche", "arrow"),
    (TOOL_RECT, "Rectangle", "square"),
    (TOOL_ELLIPSE, "Ellipse", "circle"),
)

# Message de la barre d'état une fois la forme tracée.
DRAW_DONE = {
    TOOL_INK: "Tracé ajouté",
    TOOL_LINE: "Ligne ajoutée",
    TOOL_ARROW: "Flèche ajoutée",
    TOOL_RECT: "Rectangle ajouté",
    TOOL_ELLIPSE: "Ellipse ajoutée",
}

# Mode d'emploi de chaque outil, affiché dans la barre d'état à l'activation.
TOOL_HINTS = {
    TOOL_PICK: "Reprise : cliquez une annotation pour la sélectionner, "
               "glissez-la pour la déplacer, double-cliquez pour changer ses "
               "attributs, Suppr pour l'effacer.",
    TOOL_TEXT_SELECT: "Sélection de texte : glissez sur le texte du document, "
                      "puis Ctrl+C pour le copier ou clic droit pour le "
                      "surligner.",
    TOOL_CHECK: "Cases à cocher : cliquez une case de formulaire pour la "
                "(dé)cocher ; sur une case imprimée (PDF image), le clic ou le "
                "glisser pose une coche.",
    TOOL_HL_SELECT: "Surligneur : glissez sur du texte (chaque mot est "
                    "surligné) ou sur une image/zone (aplat teinté).",
    TOOL_HL_PEN: "Marqueur : glissez pour passer un trait de surlignage, "
                 "même sur un PDF image (page scannée).",
    TOOL_TEXT: "Texte : cliquez pour en poser un, double-cliquez sur un texte "
               "existant pour le modifier, glissez-le pour le déplacer.",
    TOOL_INK: "Dessin à main levée : glissez pour tracer.",
    TOOL_LINE: "Ligne droite : glissez du début à la fin du trait.",
    TOOL_ARROW: "Flèche : glissez de la base vers la pointe.",
    TOOL_RECT: "Rectangle : glissez d'un coin à l'autre.",
    TOOL_ELLIPSE: "Ellipse : glissez d'un coin à l'autre du cadre.",
}


def select_combo(box: QComboBox, value, missing_label: str = "",
                 missing_icon: Optional[QIcon] = None):
    """Sélectionne l'entrée portant `value`.

    Si la valeur ne fait pas partie de la liste (annotation venue d'un autre
    logiciel, épaisseur inhabituelle…), elle y est ajoutée : rouvrir le
    dialogue ne doit pas changer silencieusement la mise en forme.
    """
    for i in range(box.count()):
        if box.itemData(i) == value:
            box.setCurrentIndex(i)
            return
    if missing_label:
        if missing_icon is not None:
            box.insertItem(0, missing_icon, missing_label, value)
        else:
            box.insertItem(0, missing_label, value)
    box.setCurrentIndex(0)


def color_swatch(rgb, size: int = 18) -> QIcon:
    """Pastille de couleur pour les menus (couleur au format PDF 0..1)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#FFFFFF") if rgb is None else QColor.fromRgbF(*rgb))
    p.setPen(QColor("#8F99AD"))
    p.drawRoundedRect(1, 1, size - 3, size - 3, 3, 3)
    if rgb is None:                      # « aucun » : barre oblique
        p.setPen(QPen(QColor("#C0392B"), 2))
        p.drawLine(3, size - 4, size - 4, 3)
    p.end()
    return QIcon(pm)


class OcrWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, in_path: str, out_path: str):
        super().__init__()
        self.in_path = in_path
        self.out_path = out_path

    def run(self):
        try:
            lang = ocr.ocr_document(
                self.in_path, self.out_path,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
            )
            self.done.emit(lang)
        except Exception as e:
            self.failed.emit(str(e))


class _InsertGap(QWidget):
    """Fine ligne cliquable entre deux pages (mode continu) :
    - clic : fixe le point d'insertion pour « Coller » (ligne dorée) ;
    - cible visuelle (ligne bleue) pendant le glisser-déposer de pages."""
    clicked = Signal(int)

    def __init__(self, position: int, width: int):
        super().__init__()
        self.position = position            # insertion AVANT la page `position`
        self._selected = False
        self._drop = False
        self._hover = False
        self._drag_hint = False             # un glisser de pages est en cours
        self.setFixedSize(max(60, width), 18)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Cliquer : définir le point d'insertion du collage (Ctrl+V). "
            "Déposer une page ici pour la déplacer."
        )

    def set_insert_selected(self, on: bool):
        if self._selected != on:
            self._selected = on
            self.update()

    def set_drop_target(self, on: bool):
        if self._drop != on:
            self._drop = on
            self.update()

    def set_drag_hint(self, on: bool):
        """Pendant un glisser de pages : montre (finement) toutes les lignes
        d'insertion possibles, la plus proche étant marquée en gras."""
        if self._drag_hint != on:
            self._drag_hint = on
            self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.position)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        if not (self._selected or self._drop or self._hover or self._drag_hint):
            return
        if self._drop:
            color, w, r = QColor("#1B3461"), 5, 5      # cible du dépôt : bien visible
        elif self._selected:
            color, w, r = QColor("#B8892C"), 3, 3
        elif self._hover and not self._drag_hint:
            color, w, r = QColor("#8F99AD"), 1, 3
        else:
            color, w, r = QColor("#AEB6C6"), 1, 2      # simple repère pendant le drag
        p = QPainter(self)
        y = self.height() // 2
        p.setPen(QPen(color, w))
        p.drawLine(r + 3, y, self.width() - r - 4, y)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, y - r, 2 * r + 1, 2 * r + 1)
        p.drawEllipse(self.width() - 2 * r - 3, y - r, 2 * r + 1, 2 * r + 1)
        p.end()


class _ContColumn(QWidget):
    """Colonne des pages en mode continu : accepte le dépôt de pages pour la
    réorganisation par glisser-déposer."""
    pagesDropped = Signal(list, int)        # (indices source, position de dépôt)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self._gaps: List[_InsertGap] = []

    def set_gaps(self, gaps):
        self._gaps = list(gaps)

    def _nearest_gap(self, y: float) -> Optional[_InsertGap]:
        best, best_d = None, None
        for g in self._gaps:
            d = abs(g.geometry().center().y() - y)
            if best_d is None or d < best_d:
                best, best_d = g, d
        return best

    def _clear_drop_marks(self):
        for g in self._gaps:
            g.set_drop_target(False)
            g.set_drag_hint(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_MIME_PAGES):
            for g in self._gaps:
                g.set_drag_hint(True)
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat(_MIME_PAGES):
            return
        target = self._nearest_gap(event.position().y())
        for g in self._gaps:
            g.set_drop_target(g is target)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._clear_drop_marks()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(_MIME_PAGES):
            return
        target = self._nearest_gap(event.position().y())
        self._clear_drop_marks()
        if target is None:
            return
        try:
            raw = bytes(event.mimeData().data(_MIME_PAGES)).decode("ascii")
            indices = [int(x) for x in raw.split(",")]
        except ValueError:
            return
        event.acceptProposedAction()
        self.pagesDropped.emit(indices, target.position)


class _ContPage(QLabel):
    """Page affichée en mode continu : cliquable (sélection), déplaçable par
    glisser-déposer (réorganisation) et, quand un outil d'annotation est actif,
    surface de tracé (l'aperçu du tracé en cours est dessiné par-dessus la page).
    """
    clicked = Signal(int)
    toolUsed = Signal(int, str, object)     # (page, outil, points en coords label)
    contextRequested = Signal(int, object)  # (page, position en coords label)
    doubleClicked = Signal(int, object)     # (page, position en coords label)

    def __init__(self, index: int, tool=lambda: None, drag_set=None,
                 selector=None, picker=None):
        super().__init__()
        self._index = index
        self._sel = False
        self._tool = tool                  # callable -> outil actif (ou None)
        self._drag_set = drag_set or (lambda i: [i])   # callable -> indices à déplacer
        self._selector = selector          # callable(page, départ, courant) -> [QRect]
        self._picker = picker              # callable(page, position) -> QRect | None
        self._drag_origin = None
        self._active_tool: Optional[str] = None
        self._pts: List = []               # tracé en cours (coords label)
        self._pen_color = QColor("#1B3461")
        self._pen_width = 2.0              # épaisseur d'aperçu, en pixels écran
        self._pen_fill: Optional[QColor] = None
        self._text_rects: List[QRect] = []       # sélection de texte affichée
        self._pick_rect: Optional[QRect] = None  # annotation reprise
        self.setAlignment(Qt.AlignCenter)
        self._restyle()

    def set_pen(self, color: QColor, width: float, fill: Optional[QColor]):
        """Style de l'aperçu du tracé (couleur et épaisseur de l'outil actif)."""
        self._pen_color = color
        self._pen_width = max(1.0, width)
        self._pen_fill = fill

    def set_text_rects(self, rects):
        """Rectangles de la sélection de texte à afficher sur cette page."""
        rects = list(rects or [])
        if rects != self._text_rects:
            self._text_rects = rects
            self.update()

    def set_pick_rect(self, rect: Optional[QRect]):
        """Cadre de l'annotation reprise (poignées), ou None."""
        if rect != self._pick_rect:
            self._pick_rect = rect
            self.update()

    def _restyle(self):
        if self._sel:
            self.setStyleSheet(
                "margin:6px;"
                "border-top:1px solid #D5D9E2;"
                "border-right:1px solid #D5D9E2;"
                "border-bottom:1px solid #D5D9E2;"
                "border-left:4px solid #B8892C;"
                "background:#FEF8EE;"
            )
        else:
            self.setStyleSheet(
                "margin:6px;border:1px solid #D5D9E2;background:#FFFFFF;"
            )

    def set_selected(self, value: bool):
        if self._sel != value:
            self._sel = value
            self._restyle()

    def mousePressEvent(self, event):
        tool = self._tool()
        if event.button() == Qt.LeftButton and tool:
            self._active_tool = tool
            self._pts = [event.pos()]
            if tool == TOOL_PICK and self._picker is not None:
                # La reprise sélectionne dès l'appui : le cadre suit ensuite la
                # souris, ce qui montre où l'annotation va atterrir.
                self._pick_rect = self._picker(self._index, event.pos())
            elif tool == TOOL_TEXT_SELECT:
                self._text_rects = []
            self.update()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            # Le clic n'est validé qu'au relâchement : un déplacement au-delà
            # du seuil déclenche un glisser-déposer (réorganisation).
            self._drag_origin = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._active_tool is not None:
            pos = event.pos()
            if self._active_tool in FREEHAND_TOOLS:
                # Tracé libre : on ne garde que les points réellement distincts.
                if (pos - self._pts[-1]).manhattanLength() >= 2:
                    self._pts.append(pos)
            else:
                self._pts = [self._pts[0], pos]
                if (self._active_tool == TOOL_TEXT_SELECT
                        and self._selector is not None):
                    # Sélection montrée au fil du glisser, comme dans Acrobat.
                    self._text_rects = self._selector(self._index,
                                                      self._pts[0], pos)
            self.update()
            event.accept()
            return
        if (self._drag_origin is not None
                and (event.pos() - self._drag_origin).manhattanLength()
                >= QApplication.startDragDistance()):
            self._drag_origin = None
            self._start_drag()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._active_tool is not None and event.button() == Qt.LeftButton:
            tool, pts = self._active_tool, list(self._pts)
            self._active_tool, self._pts = None, []
            self.update()
            if len(pts) == 1:
                pts.append(pts[0])           # simple clic : début = fin
            self.toolUsed.emit(self._index, tool, pts)
            event.accept()
            return
        if self._drag_origin is not None and event.button() == Qt.LeftButton:
            self._drag_origin = None
            self.clicked.emit(self._index)       # simple clic : (dé)sélection
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self._index, event.pos())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        self.contextRequested.emit(self._index, event.pos())
        event.accept()

    def paintEvent(self, event):
        """Page, puis les repères qui ne sont pas dans le PDF : sélection de
        texte, annotation reprise, et aperçu du tracé en cours (celui-ci n'est
        écrit dans le PDF qu'au relâchement du bouton)."""
        super().paintEvent(event)
        self._paint_overlays()
        if self._active_tool is None or len(self._pts) < 2:
            return
        tool = self._active_tool
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRect(self._pts[0], self._pts[-1]).normalized()
        if tool == TOOL_PICK:
            if self._pick_rect is not None:
                # Le cadre suit la souris : aperçu du déplacement.
                delta = self._pts[-1] - self._pts[0]
                p.setPen(QPen(SELECT_COLOR, 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(self._pick_rect.translated(delta))
        elif tool == TOOL_TEXT_SELECT:
            pass                       # la sélection est peinte par _paint_overlays
        elif tool == TOOL_CHECK:
            p.setPen(QPen(self._pen_color, max(1.5, self._pen_width), Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            self._draw_check(p, rect)
        elif tool == TOOL_HL_SELECT:
            wash = QColor(self._pen_color)
            wash.setAlpha(80)
            p.fillRect(rect, wash)
            p.setPen(QPen(self._pen_color.darker(140), 1, Qt.DashLine))
            p.drawRect(rect)
        elif tool == TOOL_TEXT:
            p.setPen(QPen(QColor("#1B3461"), 1, Qt.DashLine))
            p.drawRect(rect)
        elif tool in FREEHAND_TOOLS:
            color = QColor(self._pen_color)
            if tool == TOOL_HL_PEN:
                color.setAlpha(110)
            p.setPen(QPen(color, self._pen_width, Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath(QPointF(self._pts[0]))
            for pt in self._pts[1:]:
                path.lineTo(QPointF(pt))
            p.drawPath(path)
        else:
            p.setPen(QPen(self._pen_color, self._pen_width, Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(self._pen_fill or Qt.NoBrush)
            if tool == TOOL_RECT:
                p.drawRect(rect)
            elif tool == TOOL_ELLIPSE:
                p.drawEllipse(rect)
            else:
                p.drawLine(self._pts[0], self._pts[-1])
                if tool == TOOL_ARROW:
                    self._draw_arrow_head(p)
        p.end()

    def _paint_overlays(self):
        """Sélection de texte et annotation reprise : repères d'écran, jamais
        écrits dans le PDF."""
        if not self._text_rects and self._pick_rect is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._text_rects:
            wash = QColor(SELECT_COLOR)
            wash.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(wash)
            for r in self._text_rects:
                p.drawRect(r)
        if self._pick_rect is not None and self._active_tool != TOOL_PICK:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(SELECT_COLOR, 1, Qt.DashLine))
            p.drawRect(self._pick_rect)
            p.setPen(Qt.NoPen)
            p.setBrush(SELECT_COLOR)
            r = self._pick_rect
            for x, y in ((r.left(), r.top()), (r.right(), r.top()),
                         (r.left(), r.bottom()), (r.right(), r.bottom())):
                p.drawRect(QRect(x - 3, y - 3, 7, 7))
        p.end()

    @staticmethod
    def _draw_check(painter: QPainter, rect: QRect):
        """Aperçu de la coche, aux mêmes proportions que celle écrite au PDF."""
        if rect.width() < 4 or rect.height() < 4:
            rect = QRect(rect.left(), rect.top(), 18, 18)
        w, h = rect.width(), rect.height()
        path = QPainterPath(QPointF(rect.left() + w * 0.12, rect.top() + h * 0.55))
        path.lineTo(QPointF(rect.left() + w * 0.40, rect.top() + h * 0.86))
        path.lineTo(QPointF(rect.left() + w * 0.90, rect.top() + h * 0.14))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _draw_arrow_head(self, painter: QPainter):
        """Pointe de la flèche dans l'aperçu (le PDF, lui, la dessine seul)."""
        start, end = QPointF(self._pts[0]), QPointF(self._pts[-1])
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return
        size = max(8.0, self._pen_width * 4)
        angle = math.atan2(dy, dx)
        p1 = QPointF(end.x() - size * math.cos(angle - 0.4),
                     end.y() - size * math.sin(angle - 0.4))
        p2 = QPointF(end.x() - size * math.cos(angle + 0.4),
                     end.y() - size * math.sin(angle + 0.4))
        painter.setBrush(self._pen_color)
        painter.drawPolygon(QPolygonF([end, p1, p2]))

    def _start_drag(self):
        indices = self._drag_set(self._index)
        if not indices:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_PAGES,
                     ",".join(str(i) for i in indices).encode("ascii"))
        drag.setMimeData(mime)
        pm = self.pixmap()
        if pm is not None and not pm.isNull():
            drag.setPixmap(pm.scaledToWidth(
                min(160, pm.width()), Qt.SmoothTransformation))
        drag.exec(Qt.MoveAction)


class _ThumbList(QListWidget):
    """Liste des vignettes : glisser-déposer des pages sélectionnées avec un
    indicateur d'insertion bien visible (barre bleue entre deux vignettes),
    et clic entre deux vignettes pour fixer le point d'insertion du collage
    (barre dorée, comme la ligne dorée du mode continu)."""
    pagesDropped = Signal(list, int)        # (indices source, position de dépôt)
    gapClicked = Signal(int)                # clic entre deux vignettes

    def __init__(self):
        super().__init__()
        self._drop_pos: Optional[int] = None       # insertion pendant le drag
        self._insert_pos: Optional[int] = None     # point d'insertion du collage
        self._empty_press = None                   # clic démarré hors vignette
        self._synth_ctrl = False                   # clic simple traité en Ctrl+clic
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        # Surtout pas Movement.Static : Qt couperait alors les drops au niveau
        # du viewport (viewport().setAcceptDrops(False)) et plus aucun
        # événement de dépôt n'atteindrait cette liste.
        self.setMovement(QListView.Snap)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setSpacing(12)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)   # remplacé par notre barre d'insertion

    # ------------------------------------------------ position d'insertion --
    def _insertion_pos(self, pos) -> int:
        """Position d'insertion (0..count) dont la frontière entre vignettes
        est la plus proche du point `pos` (coordonnées du viewport)."""
        n = self.count()
        if n == 0:
            return 0
        it = self.itemAt(pos)
        if it is not None:
            r = self.visualItemRect(it)
            return self.row(it) + (1 if pos.x() >= r.center().x() else 0)
        best, best_d = n, None
        for row in range(n):
            r = self.visualItemRect(self.item(row))
            for p, x in ((row, r.left()), (row + 1, r.right())):
                dx = x - pos.x()
                dy = r.center().y() - pos.y()
                dist = dx * dx + dy * dy
                if best_d is None or dist < best_d:
                    best, best_d = p, dist
        return best

    def _marker_rect(self, position: int) -> Optional[QRect]:
        """Barre verticale matérialisant l'insertion AVANT `position`."""
        n = self.count()
        if n == 0:
            return None
        position = max(0, min(position, n))
        if position < n:
            r = self.visualItemRect(self.item(position))
            x = r.left() - 9
        else:
            r = self.visualItemRect(self.item(n - 1))
            x = r.right() + 4
        return QRect(x, r.top() + 4, 5, r.height() - 8)

    def _set_drop_pos(self, position: Optional[int]):
        if self._drop_pos != position:
            self._drop_pos = position
            self.viewport().update()

    def set_insert_marker(self, position: Optional[int]):
        if self._insert_pos != position:
            self._insert_pos = position
            self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        marks = []
        if self._insert_pos is not None:
            marks.append((self._insert_pos, QColor("#B8892C")))
        if self._drop_pos is not None:
            marks.append((self._drop_pos, QColor("#1B3461")))
        if not marks:
            return
        p = QPainter(self.viewport())
        p.setPen(Qt.NoPen)
        for position, color in marks:
            r = self._marker_rect(position)
            if r is None:
                continue
            p.setBrush(color)
            p.drawRoundedRect(r, 2, 2)
            cx = r.center().x()
            p.drawEllipse(cx - 4, r.top() - 6, 9, 9)
            p.drawEllipse(cx - 4, r.bottom() - 2, 9, 9)
        p.end()

    # ------------------------------------------------------ glisser-déposer --
    def startDrag(self, supported_actions):
        rows = sorted(self.row(i) for i in self.selectedItems())
        if not rows:
            return
        indices = [self.item(r).data(Qt.UserRole) for r in rows]
        drag = QDrag(self)
        mime = QMimeData()
        # Payload signé par l'identité de CETTE liste : le dépôt n'est accepté
        # que pour un glisser interne (plus fiable que event.source()).
        payload = f"{id(self)}:" + ",".join(str(i) for i in indices)
        mime.setData(_MIME_PAGES, payload.encode("ascii"))
        drag.setMimeData(mime)
        pm = self.item(rows[0]).icon().pixmap(110, 110)
        if not pm.isNull():
            drag.setPixmap(pm)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self._set_drop_pos(None)
            # Qt a mis la vue en DraggingState avant d'appeler startDrag ;
            # sans remise à zéro, les clics/glissers suivants sont perturbés.
            self.setState(QListWidget.State.NoState)

    def _drag_indices(self, event) -> Optional[List[int]]:
        """Indices transportés si le glisser vient bien de cette liste."""
        if not event.mimeData().hasFormat(_MIME_PAGES):
            return None
        try:
            raw = bytes(event.mimeData().data(_MIME_PAGES)).decode("ascii")
            token, _, data = raw.partition(":")
            if token != str(id(self)):
                return None
            return [int(x) for x in data.split(",")]
        except ValueError:
            return None

    def dragEnterEvent(self, event):
        if self._drag_indices(event) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self._drag_indices(event) is None:
            return
        self._set_drop_pos(self._insertion_pos(event.position().toPoint()))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._set_drop_pos(None)

    def dropEvent(self, event):
        indices = self._drag_indices(event)
        if indices is None:
            return
        position = self._insertion_pos(event.position().toPoint())
        self._set_drop_pos(None)
        event.acceptProposedAction()
        # Émission différée : la réorganisation reconstruit vignettes et vue
        # continue, ce qui ne doit pas s'exécuter au milieu de la boucle
        # native du glisser-déposer encore active pendant le drop.
        QTimer.singleShot(0, lambda: self.pagesDropped.emit(indices, position))

    # ------------------------- clics : sélection cumulative + point de collage --
    @staticmethod
    def _with_ctrl(event):
        """Copie de l'événement souris avec Ctrl ajouté : un clic simple sur
        une page se comporte comme Ctrl+clic (ajout/retrait de la sélection,
        comme en mode continu)."""
        return QMouseEvent(event.type(), event.position(),
                           event.globalPosition(), event.button(),
                           event.buttons(),
                           event.modifiers() | Qt.ControlModifier)

    def mousePressEvent(self, event):
        self._empty_press = None
        pos = event.position().toPoint()
        if event.button() == Qt.LeftButton and self.count() \
                and self.itemAt(pos) is None:
            self._empty_press = pos
        elif (event.button() == Qt.LeftButton
                and self.itemAt(pos) is not None
                and not (event.modifiers()
                         & (Qt.ControlModifier | Qt.ShiftModifier))):
            # Sélection multiple sans modificateur (contiguë ou non) :
            # chaque clic (dé)sélectionne la page, Maj+clic garde la plage.
            self._synth_ctrl = True
            event = self._with_ctrl(event)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        press = self._empty_press
        self._empty_press = None
        if getattr(self, "_synth_ctrl", False) and event.button() == Qt.LeftButton:
            self._synth_ctrl = False
            super().mouseReleaseEvent(self._with_ctrl(event))
        else:
            super().mouseReleaseEvent(event)
        # Simple clic dans un espace vide (pas un cadre de sélection) :
        # (dé)fixe le point d'insertion du collage.
        if (press is not None and event.button() == Qt.LeftButton
                and (event.position().toPoint() - press).manhattanLength()
                < QApplication.startDragDistance()
                and self.itemAt(event.position().toPoint()) is None):
            self.gapClicked.emit(self._insertion_pos(event.position().toPoint()))


class _TextDialog(QDialog):
    """Saisie ou modification d'un texte posé sur une page.

    La mise en forme est enregistrée dans l'annotation elle-même : rouvrir ce
    dialogue sur un texte existant restitue sa police, son corps, sa couleur
    et son fond, et permet donc de le ré-éditer autant de fois que voulu.
    """

    def __init__(self, parent, style: dict, text: str = "", editing: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Modifier le texte" if editing else "Ajouter un texte")
        self.setMinimumWidth(430)
        self.deleted = False

        self.edit = QPlainTextEdit(text)
        self.edit.setPlaceholderText("Texte à afficher sur la page…")
        self.edit.setMinimumHeight(90)

        self.font_box = QComboBox()
        for label, code in pdf_ops.TEXT_FONTS.items():
            self.font_box.addItem(label, code)
        select_combo(self.font_box, style.get("font") or "helv")

        self.size_box = QComboBox()
        for pt in pdf_ops.TEXT_SIZES:
            self.size_box.addItem(f"{pt} pt", float(pt))
        select_combo(self.size_box, float(style.get("size") or 12.0))

        self.color_box = QComboBox()
        for name, rgb in pdf_ops.DRAW_COLORS.items():
            self.color_box.addItem(color_swatch(rgb), name, rgb)
        current = tuple(style.get("color") or (0.0, 0.0, 0.0))
        select_combo(self.color_box, current, missing_label="Couleur actuelle",
                     missing_icon=color_swatch(current))

        self.fill_box = QCheckBox(
            "Fond blanc opaque (masque ce qu'il y a dessous)")
        self.fill_box.setChecked(bool(style.get("fill")))

        form = QFormLayout(self)
        form.addRow("Texte", self.edit)
        form.addRow("Police", self.font_box)
        form.addRow("Corps", self.size_box)
        form.addRow("Couleur", self.color_box)
        form.addRow("", self.fill_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Valider")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        if editing:
            remove = buttons.addButton("Supprimer",
                                       QDialogButtonBox.DestructiveRole)
            remove.clicked.connect(self._on_delete)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.edit.setFocus()

    def _on_delete(self):
        self.deleted = True
        self.accept()

    def values(self) -> dict:
        return {
            "text": self.edit.toPlainText(),
            "font": self.font_box.currentData(),
            "size": float(self.size_box.currentData()),
            "color": tuple(self.color_box.currentData()),
            "fill": (1.0, 1.0, 1.0) if self.fill_box.isChecked() else None,
        }


class _ShapeDialog(QDialog):
    """Attributs d'un tracé ou d'un surlignage déjà posé.

    Ouvert par un double-clic sur l'annotation (ou par le clic droit), il
    permet de reprendre sa couleur, son épaisseur et son remplissage sans
    avoir à l'effacer et à la refaire.
    """

    def __init__(self, parent, style: dict, family: str = "draw"):
        super().__init__(parent)
        self.family = family
        self.setWindowTitle("Modifier le surlignage" if family == "highlight"
                            else "Modifier le tracé")
        self.setMinimumWidth(380)
        self.deleted = False

        colors = (pdf_ops.HIGHLIGHT_COLORS if family == "highlight"
                  else pdf_ops.DRAW_COLORS)
        widths = (pdf_ops.HIGHLIGHT_WIDTHS if family == "highlight"
                  else pdf_ops.DRAW_WIDTHS)

        self.color_box = QComboBox()
        for name, rgb in colors.items():
            self.color_box.addItem(color_swatch(rgb), name, rgb)
        current = tuple(style.get("color") or (0.0, 0.0, 0.0))
        select_combo(self.color_box, current, missing_label="Couleur actuelle",
                     missing_icon=color_swatch(current))

        self.width_box = QComboBox()
        for name, value in widths.items():
            self.width_box.addItem(f"{name} ({value:g} pt)", float(value))
        width = float(style.get("width") or 0.0)
        select_combo(self.width_box, width,
                     missing_label=f"Actuelle ({width:g} pt)")

        form = QFormLayout(self)
        form.addRow("Couleur", self.color_box)
        form.addRow("Épaisseur", self.width_box)

        self.fill_box = None
        if family == "draw":
            self.fill_box = QComboBox()
            for name, rgb in [("Aucun", None)] + list(pdf_ops.DRAW_COLORS.items()):
                self.fill_box.addItem(color_swatch(rgb), name, rgb)
            fill = style.get("fill")
            select_combo(self.fill_box, tuple(fill) if fill else None,
                         missing_label="Remplissage actuel",
                         missing_icon=color_swatch(fill))
            form.addRow("Remplissage", self.fill_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Valider")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        remove = buttons.addButton("Supprimer", QDialogButtonBox.DestructiveRole)
        remove.clicked.connect(self._on_delete)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_delete(self):
        self.deleted = True
        self.accept()

    def values(self) -> dict:
        return {
            "color": tuple(self.color_box.currentData()),
            "width": float(self.width_box.currentData()),
            # False = remplissage inchangé (les surlignages n'en ont pas).
            "fill": self.fill_box.currentData() if self.fill_box else False,
        }


class ViewerWindow(QMainWindow):
    titleChanged = Signal()

    def __init__(self, path: str, library=None):
        super().__init__()
        self.path = path
        self.library = library
        self.doc = fitz.open(path)        # document de travail (édité en mémoire)
        self._zoom = 1.0
        self._dirty = False
        self._insert_pos: Optional[int] = None   # point d'insertion du collage

        # --- Outils d'annotation (un seul actif à la fois) ---
        self._tool: Optional[str] = None
        self._hl_kind = TOOL_HL_SELECT            # mode du surligneur
        self._hl_color = pdf_ops.HIGHLIGHT_COLORS["Jaune"]
        self._hl_width = pdf_ops.HIGHLIGHT_WIDTHS["Moyen"]
        self._draw_kind = TOOL_INK                # forme du dessin
        self._draw_color = pdf_ops.DRAW_COLORS["Rouge"]
        self._draw_width = pdf_ops.DRAW_WIDTHS["Moyen"]
        self._draw_fill = None
        # Mise en forme reprise d'un texte à l'autre.
        self._text_style = {"font": "helv", "size": 12.0,
                            "color": (0.0, 0.0, 0.0), "fill": None}
        # Annotation reprise (outil de reprise) et sélection de texte courante.
        self._picked: Optional[dict] = None
        self._text_sel: Optional[dict] = None
        self._ocr_worker: Optional[OcrWorker] = None
        self._progress: Optional[QProgressDialog] = None

        self._refresh_title()
        self.resize(960, 820)

        self._build_toolbar()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # --- Mode vignettes (sélection + réorganisation) ---
        self.page_list = _ThumbList()
        self.page_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.page_list.customContextMenuRequested.connect(self._page_context_menu)
        self.page_list.pagesDropped.connect(self._move_pages)
        self.page_list.gapClicked.connect(self._on_gap_clicked)
        self.page_list.itemSelectionChanged.connect(self._refresh_cont_highlight)
        self.stack.addWidget(self.page_list)

        # --- Mode continu / grand ---
        self.cont_area = QScrollArea()
        self.cont_area.setWidgetResizable(True)
        self.cont_area.setFocusPolicy(Qt.ClickFocus)   # raccourcis Ctrl+C/X/V
        self.cont_inner = _ContColumn()
        self.cont_inner.pagesDropped.connect(self._move_pages)
        self.cont_layout = QVBoxLayout(self.cont_inner)
        self.cont_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.cont_area.setWidget(self.cont_inner)
        self.stack.addWidget(self.cont_area)

        self._load_thumbnails()
        self._build_continuous()
        self.stack.setCurrentWidget(self.cont_area)
        self._update_status()

    # ----------------------------------------------------------------- UI --
    @property
    def single(self) -> bool:
        return self.doc.page_count <= 1

    def _refresh_title(self):
        star = "*" if self._dirty else ""
        self._title = f"{os.path.basename(self.path)}{star}"
        self.setWindowTitle(f"Visionneuse — {self._title}")
        self.titleChanged.emit()

    def tab_title(self) -> str:
        return getattr(self, "_title", os.path.basename(self.path))

    def _update_status(self):
        if self.single:
            self.statusBar().showMessage(
                "Zoom : molette + Ctrl • outils d'annotation dans la barre "
                "d'outils (reprise, sélection de texte, surligneur, texte, "
                "dessin, cases à cocher) • double-clic sur une annotation : "
                "la modifier • clic droit sur la page : menu des annotations"
            )
        else:
            self.statusBar().showMessage(
                "Clic : (dé)sélectionner des pages, même non contiguës "
                "(Maj+clic : plage) • glisser la sélection pour réordonner "
                "• clic entre 2 pages : point d'insertion du collage "
                "• clic droit sur une vignette : pivoter / copier / coller / "
                "supprimer / découper • clic droit sur une page : annotations "
                "• Ctrl+C/X/V : copier, couper, coller des pages "
                "• Suppr : supprimer les pages sélectionnées"
                " • outils d'annotation dans la barre d'outils"
            )

    def _build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        # Sélecteur d'affichage : 2 boutons-icônes radio dans un cadre commun.
        seg = QFrame()
        seg.setObjectName("ModeSwitch")
        seg_l = QHBoxLayout(seg)
        seg_l.setContentsMargins(3, 3, 3, 3)
        seg_l.setSpacing(2)
        self.btn_continuous = QToolButton()
        self.btn_continuous.setCheckable(True)
        self.btn_continuous.setIcon(icons.icon("rows"))
        self.btn_continuous.setIconSize(QSize(22, 22))
        self.btn_continuous.setToolTip("Pages en continu")
        self.btn_thumbs = QToolButton()
        self.btn_thumbs.setCheckable(True)
        self.btn_thumbs.setIcon(icons.icon("grid"))
        self.btn_thumbs.setIconSize(QSize(22, 22))
        self.btn_thumbs.setToolTip("Vignettes")
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.btn_continuous, 0)
        self._mode_group.addButton(self.btn_thumbs, 1)
        self.btn_continuous.setChecked(True)
        self._mode_group.idClicked.connect(self._change_mode)
        seg_l.addWidget(self.btn_continuous)
        seg_l.addWidget(self.btn_thumbs)
        tb.addWidget(seg)
        self._update_mode_icons()
        tb.addSeparator()

        for ic, label, tip, slot in (("minus", "", "Zoom arrière", self.zoom_out),
                                     ("plus", "", "Zoom avant", self.zoom_in),
                                     ("fit", "Ajuster", "Zoom 100 %", self.zoom_fit)):
            a = QAction(icons.icon(ic), label, self)
            a.setToolTip(tip)
            a.triggered.connect(slot)
            tb.addAction(a)
        tb.addSeparator()

        # Rotation (icône seule ; menu : sélection ou tout)
        rot_btn = QToolButton(self)
        rot_btn.setText("")
        rot_btn.setToolTip("Pivoter")
        rot_btn.setIcon(icons.icon("rotate-cw"))
        rot_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        rot_btn.setPopupMode(QToolButton.InstantPopup)
        rot_menu = QMenu(rot_btn)
        rot_menu.addAction(icons.icon("rotate-cw"), "90° horaire (sélection/tout)",
                           lambda: self.rotate(90))
        rot_menu.addAction(icons.icon("rotate-ccw"), "90° anti-horaire (sélection/tout)",
                           lambda: self.rotate(270))
        rot_menu.addAction(icons.icon("rotate-cw"), "180° (sélection/tout)",
                           lambda: self.rotate(180))
        rot_btn.setMenu(rot_menu)
        tb.addWidget(rot_btn)

        self.act_del = QAction(icons.icon("trash"), "", self)
        self.act_del.setToolTip(
            "Supprimer l'annotation reprise si elle existe, sinon la/les "
            "page(s) sélectionnée(s)  (Suppr)")
        self.act_del.setShortcut(QKeySequence.Delete)
        self.act_del.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.act_del.triggered.connect(self.delete_selected)
        self.addAction(self.act_del)   # raccourci actif quand le focus est ici
        tb.addAction(self.act_del)
        tb.addSeparator()

        # ------------------------------------------------------------------
        # Outils d'annotation, réunis dans un bloc unique (comme le sélecteur
        # d'affichage) : ils s'excluent mutuellement et le bloc reste compact.
        tools = QFrame()
        tools.setObjectName("ToolSwitch")
        tools_l = QHBoxLayout(tools)
        tools_l.setContentsMargins(3, 3, 3, 3)
        tools_l.setSpacing(2)

        def add_tool(button):
            button.setCheckable(True)
            button.setIconSize(QSize(22, 22))
            tools_l.addWidget(button)
            return button

        # Reprise d'une annotation : sélectionner, déplacer, modifier, effacer.
        self.pick_btn = add_tool(QToolButton(self))
        self.pick_btn.setIcon(icons.icon("pointer"))
        self.pick_btn.setToolTip(
            "Reprendre une annotation : cliquez-la pour la sélectionner, "
            "glissez-la pour la déplacer, double-cliquez pour changer ses "
            "attributs, Suppr pour l'effacer."
        )
        self.pick_btn.toggled.connect(
            lambda on: self._set_tool(TOOL_PICK if on else None))

        # Sélection du texte du document (copier / surligner).
        self.sel_btn = add_tool(QToolButton(self))
        self.sel_btn.setIcon(icons.icon("cursor-text"))
        self.sel_btn.setToolTip(
            "Sélectionner du texte : glissez sur le texte du document, puis "
            "Ctrl+C pour le copier ou clic droit pour le surligner "
            "(PDF texte ; un PDF image doit d'abord passer par l'OCR)."
        )
        self.sel_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.sel_btn.toggled.connect(
            lambda on: self._set_tool(TOOL_TEXT_SELECT if on else None))
        sel_menu = QMenu(self.sel_btn)
        sel_menu.addAction(icons.icon("copy"), "Copier le texte sélectionné",
                           self.copy_text_selection)
        sel_menu.addAction(icons.icon("highlight"),
                           "Surligner le texte sélectionné",
                           self.highlight_text_selection)
        self.sel_btn.setMenu(sel_menu)

        # Surligneur (comme Acrobat) : bouton bascule + menu (mode, couleur…).
        self.hl_btn = add_tool(QToolButton(self))
        self.hl_btn.setIcon(icons.icon("highlight"))
        self.hl_btn.setToolTip(
            "Surligner : glissez sur du texte (surlignage mot à mot) ou sur "
            "une image/zone (aplat de couleur). Flèche : mode marqueur, "
            "couleur, épaisseur."
        )
        self.hl_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.hl_btn.toggled.connect(
            lambda on: self._set_tool(self._hl_kind if on else None))
        hl_menu = QMenu(self.hl_btn)
        kind_group = QActionGroup(self)
        for kind, label, tip in (
            (TOOL_HL_SELECT, "Sélection (texte ou zone)",
             "Glisser sur du texte : chaque mot est surligné. "
             "Sur une image ou une page scannée : la zone est teintée."),
            (TOOL_HL_PEN, "Marqueur (trait libre)",
             "Passer le marqueur à main levée, comme sur du papier : "
             "fonctionne aussi sur un PDF image (page scannée)."),
        ):
            a = hl_menu.addAction(icons.icon(
                "highlight" if kind == TOOL_HL_SELECT else "marker"), label)
            a.setCheckable(True)
            a.setChecked(kind == self._hl_kind)
            a.setToolTip(tip)
            a.triggered.connect(lambda checked=False, k=kind: self._set_hl_kind(k))
            kind_group.addAction(a)
        hl_menu.addSeparator()
        self._hl_color_actions = []
        for name, rgb in pdf_ops.HIGHLIGHT_COLORS.items():
            a = hl_menu.addAction(color_swatch(rgb), name)
            a.setCheckable(True)
            a.setChecked(name == "Jaune")
            a.triggered.connect(
                lambda checked=False, n=name: self._set_highlight_color(n))
            self._hl_color_actions.append(a)
        hl_menu.addSeparator()
        width_menu = hl_menu.addMenu("Épaisseur du marqueur")
        self._hl_width_actions = []
        for name, value in pdf_ops.HIGHLIGHT_WIDTHS.items():
            a = width_menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(value == self._hl_width)
            a.triggered.connect(
                lambda checked=False, v=value: self._set_highlight_width(v))
            self._hl_width_actions.append((a, value))
        hl_menu.addSeparator()
        hl_menu.addAction(icons.icon("highlight"),
                          "Surligner le texte sélectionné",
                          self.highlight_text_selection)
        hl_menu.addAction(icons.icon("trash"),
                          "Effacer les surlignages (sélection/tout)",
                          self.clear_highlights)
        self.hl_btn.setMenu(hl_menu)

        # Texte : poser un texte, le modifier (double-clic) ou le déplacer.
        self.text_btn = add_tool(QToolButton(self))
        self.text_btn.setIcon(icons.icon("text"))
        self.text_btn.setToolTip(
            "Texte : cliquez sur la page pour ajouter un texte, double-cliquez "
            "sur un texte existant pour le modifier (police, corps, couleur, "
            "fond), glissez-le pour le déplacer."
        )
        self.text_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.text_btn.toggled.connect(
            lambda on: self._set_tool(TOOL_TEXT if on else None))
        text_menu = QMenu(self.text_btn)
        text_menu.addAction(icons.icon("trash"),
                            "Effacer les textes ajoutés (sélection/tout)",
                            self.clear_texts)
        self.text_btn.setMenu(text_menu)

        # Dessin : main levée, ligne, flèche, rectangle, ellipse.
        self.draw_btn = add_tool(QToolButton(self))
        self.draw_btn.setIcon(icons.icon("pen"))
        self.draw_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.draw_btn.toggled.connect(
            lambda on: self._set_tool(self._draw_kind if on else None))
        draw_menu = QMenu(self.draw_btn)
        shape_group = QActionGroup(self)
        self._draw_shape_actions = []
        for kind, label, icon_name in DRAW_SHAPES:
            a = draw_menu.addAction(icons.icon(icon_name), label)
            a.setCheckable(True)
            a.setChecked(kind == self._draw_kind)
            a.triggered.connect(
                lambda checked=False, k=kind: self._set_draw_kind(k))
            shape_group.addAction(a)
            self._draw_shape_actions.append((a, kind))
        draw_menu.addSeparator()
        color_menu = draw_menu.addMenu("Couleur du trait")
        self._draw_color_actions = []
        for name, rgb in pdf_ops.DRAW_COLORS.items():
            a = color_menu.addAction(color_swatch(rgb), name)
            a.setCheckable(True)
            a.setChecked(rgb == self._draw_color)
            a.triggered.connect(
                lambda checked=False, c=rgb: self._set_draw_color(c))
            self._draw_color_actions.append((a, rgb))
        fill_menu = draw_menu.addMenu("Remplissage des formes")
        self._draw_fill_actions = []
        for name, rgb in [("Aucun", None)] + list(pdf_ops.DRAW_COLORS.items()):
            a = fill_menu.addAction(color_swatch(rgb), name)
            a.setCheckable(True)
            a.setChecked(rgb == self._draw_fill)
            a.triggered.connect(
                lambda checked=False, c=rgb: self._set_draw_fill(c))
            self._draw_fill_actions.append((a, rgb))
        thick_menu = draw_menu.addMenu("Épaisseur du trait")
        self._draw_width_actions = []
        for name, value in pdf_ops.DRAW_WIDTHS.items():
            a = thick_menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(value == self._draw_width)
            a.triggered.connect(
                lambda checked=False, v=value: self._set_draw_width(v))
            self._draw_width_actions.append((a, value))
        draw_menu.addSeparator()
        draw_menu.addAction(icons.icon("trash"),
                            "Effacer les dessins (sélection/tout)",
                            self.clear_drawings)
        self.draw_btn.setMenu(draw_menu)
        self._refresh_draw_button()

        # Cases à cocher : formulaire (vraie case) ou case imprimée (coche).
        self.check_btn = add_tool(QToolButton(self))
        self.check_btn.setIcon(icons.icon("check"))
        self.check_btn.setToolTip(
            "Cocher : cliquez une case de formulaire pour la (dé)cocher. "
            "Sur une case imprimée (PDF image), le clic pose une coche ; "
            "glissez pour l'ajuster à la taille de la case."
        )
        self.check_btn.toggled.connect(
            lambda on: self._set_tool(TOOL_CHECK if on else None))

        tb.addWidget(tools)
        tb.addSeparator()

        # Copier / couper / coller des pages (dans ce document ou un autre).
        self.act_copy = QAction(icons.icon("copy"), "", self)
        self.act_copy.setToolTip("Copier la/les page(s) sélectionnée(s)  (Ctrl+C)")
        self.act_copy.setShortcut(QKeySequence.Copy)
        self.act_copy.triggered.connect(self.copy_pages)
        self.act_cut = QAction(icons.icon("scissors"), "", self)
        self.act_cut.setToolTip("Couper la/les page(s) sélectionnée(s)  (Ctrl+X)")
        self.act_cut.setShortcut(QKeySequence.Cut)
        self.act_cut.triggered.connect(self.cut_pages)
        self.act_paste = QAction(icons.icon("clipboard"), "", self)
        self.act_paste.setToolTip(
            "Coller les pages copiées au point d'insertion (clic entre deux "
            "pages), sinon après la sélection ou à la fin  (Ctrl+V)")
        self.act_paste.setShortcut(QKeySequence.Paste)
        # lambda sans argument : `triggered` émet un booléen `checked` qui,
        # passé tel quel, serait pris pour la position 0 (collage en tête !)
        self.act_paste.triggered.connect(lambda: self.paste_pages())
        for a in (self.act_copy, self.act_cut, self.act_paste):
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.addAction(a)      # raccourci actif quand le focus est ici
            tb.addAction(a)
        tb.addSeparator()

        act_ocr = QAction(icons.icon("ocr"), "OCR", self)
        act_ocr.setToolTip("OCR du document")
        act_ocr.triggered.connect(self.run_ocr)
        tb.addAction(act_ocr)
        tb.addSeparator()

        # Impression (icône seule ; menu : imprimer ou aperçu)
        print_btn = QToolButton(self)
        print_btn.setToolTip("Imprimer  (Ctrl+P)")
        print_btn.setIcon(icons.icon("printer"))
        print_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        print_btn.setPopupMode(QToolButton.InstantPopup)
        print_menu = QMenu(print_btn)
        print_menu.addAction(icons.icon("printer"),
                             "Imprimer… (sélection/tout)", self.print_document)
        print_menu.addAction(icons.icon("eye"), "Aperçu avant impression…",
                             self.print_preview)
        print_btn.setMenu(print_menu)
        tb.addWidget(print_btn)

        # Raccourci : actif quel que soit le widget qui a le focus ici.
        self.act_print = QAction("Imprimer", self)
        self.act_print.setShortcut(QKeySequence.Print)
        self.act_print.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.act_print.triggered.connect(self.print_document)
        self.addAction(self.act_print)

        act_save = QAction(icons.icon("save"), "Enregistrer", self)
        act_save.setToolTip("Enregistrer sous…")
        act_save.triggered.connect(self.save_as)
        tb.addAction(act_save)

    # -------------------------------------------------------- Zoom --
    def _apply_zoom(self):
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom))
        if self.stack.currentWidget() is self.page_list:
            self._load_thumbnails()
        else:
            self._build_continuous()
        self.statusBar().showMessage(f"Zoom : {int(self._zoom * 100)} %")

    def zoom_in(self):
        self._zoom *= 1.25
        self._apply_zoom()

    def zoom_out(self):
        self._zoom *= 0.8
        self._apply_zoom()

    def zoom_fit(self):
        self._zoom = 1.0
        self._apply_zoom()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_in() if event.angleDelta().y() > 0 else self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    # -------------------------------------------------------- Vues --
    def _load_thumbnails(self):
        size = int(PAGE_THUMB * self._zoom)
        self.page_list.setIconSize(QSize(size, size))
        self.page_list.clear()
        for idx in range(self.doc.page_count):
            png = pdf_ops.render_page_to_png(self.doc, idx, max_size=size)
            pix = QPixmap()
            pix.loadFromData(png)
            item = QListWidgetItem(QIcon(pix), f"Page {idx + 1}")
            item.setData(Qt.UserRole, idx)
            item.setTextAlignment(Qt.AlignHCenter)
            self.page_list.addItem(item)
        if self._insert_pos is not None and self._insert_pos > self.doc.page_count:
            self._insert_pos = None
        self.page_list.set_insert_marker(self._insert_pos)

    def _build_continuous(self):
        while self.cont_layout.count():
            it = self.cont_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._cont_pages = []
        self._cont_gaps: List[_InsertGap] = []
        if self._insert_pos is not None and self._insert_pos > self.doc.page_count:
            self._insert_pos = None
        selected = set(self._selected_indices())
        width = int(CONT_BASE * self._zoom)
        for idx in range(self.doc.page_count):
            self.cont_layout.addWidget(self._make_gap(idx, width))
            page = self.doc[idx]
            z = width / max(1.0, page.rect.width)
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            qpix = QPixmap()
            qpix.loadFromData(pix.tobytes("png"))
            lbl = _ContPage(idx, tool=lambda: self._tool,
                            drag_set=self._drag_set,
                            selector=self._live_selection,
                            picker=self._pick_at)
            lbl.setPixmap(qpix)
            lbl.set_selected(idx in selected)
            lbl.clicked.connect(self._toggle_page_selection)
            lbl.toolUsed.connect(self._on_tool_used)
            lbl.doubleClicked.connect(self._on_page_double_clicked)
            lbl.contextRequested.connect(self._on_page_context_menu)
            self.cont_layout.addWidget(lbl)
            self._cont_pages.append((idx, lbl))
        self._refresh_tool_cursors()
        self._refresh_overlays()
        if self.doc.page_count:
            self.cont_layout.addWidget(
                self._make_gap(self.doc.page_count, width))
        self.cont_inner.set_gaps(self._cont_gaps)

    def _make_gap(self, position: int, width: int) -> _InsertGap:
        gap = _InsertGap(position, width)
        gap.set_insert_selected(self._insert_pos == position)
        gap.clicked.connect(self._on_gap_clicked)
        self._cont_gaps.append(gap)
        return gap

    def _drag_set(self, idx: int) -> List[int]:
        """Pages emportées par un glisser démarré sur la page `idx` : la
        sélection entière si la page en fait partie, sinon cette page seule."""
        sel = self._selected_indices()
        return sel if idx in sel else [idx]

    def _on_gap_clicked(self, position: int):
        """Clic entre deux pages (mode continu ou vignettes) :
        (dé)fixe le point d'insertion du collage."""
        self._insert_pos = None if self._insert_pos == position else position
        for g in getattr(self, "_cont_gaps", []):
            g.set_insert_selected(g.position == self._insert_pos)
        self.page_list.set_insert_marker(self._insert_pos)
        if self._insert_pos is None:
            self._update_status()
        else:
            if position == 0:
                where = "avant la page 1"
            elif position == self.doc.page_count:
                where = f"après la page {self.doc.page_count}"
            else:
                where = f"entre les pages {position} et {position + 1}"
            self.statusBar().showMessage(
                f"Point d'insertion {where} — Ctrl+V (ou l'outil Coller) "
                "collera les pages copiées à cet endroit."
            )
        self.stack.currentWidget().setFocus()   # active les raccourcis Ctrl+C/X/V

    def _clear_insert_pos(self):
        self._insert_pos = None
        for g in getattr(self, "_cont_gaps", []):
            g.set_insert_selected(False)
        self.page_list.set_insert_marker(None)

    def _item_for_index(self, idx: int):
        for r in range(self.page_list.count()):
            it = self.page_list.item(r)
            if it.data(Qt.UserRole) == idx:
                return it
        return None

    def _toggle_page_selection(self, idx: int):
        """Clic sur une page en mode continu : (dé)sélectionne, comme en vignettes."""
        item = self._item_for_index(idx)
        if item is not None:
            item.setSelected(not item.isSelected())
        self._refresh_cont_highlight()
        self.cont_area.setFocus()          # active les raccourcis Ctrl+C/X/V

    def _refresh_cont_highlight(self):
        selected = set(self._selected_indices())
        for idx, lbl in getattr(self, "_cont_pages", []):
            lbl.set_selected(idx in selected)

    def _reload_views(self):
        self._load_thumbnails()
        self._build_continuous()

    def _change_mode(self, index: int):
        if index == 1:
            self.stack.setCurrentWidget(self.page_list)
        else:
            self._build_continuous()
            self.stack.setCurrentWidget(self.cont_area)
        (self.btn_thumbs if index == 1 else self.btn_continuous).setChecked(True)
        self._update_mode_icons()

    def _update_mode_icons(self):
        on, off = "#ffffff", "#1B3461"
        self.btn_continuous.setIcon(
            icons.icon("rows", on if self.btn_continuous.isChecked() else off))
        self.btn_thumbs.setIcon(
            icons.icon("grid", on if self.btn_thumbs.isChecked() else off))

    def _current_order(self) -> List[int]:
        return [
            self.page_list.item(r).data(Qt.UserRole)
            for r in range(self.page_list.count())
        ]

    def _selected_indices(self) -> List[int]:
        return sorted(i.data(Qt.UserRole) for i in self.page_list.selectedItems())

    def _mark_dirty(self):
        self._dirty = True
        self._refresh_title()

    # ---------------------------------------------- Réorganisation (drag) --
    def _move_pages(self, sources: List[int], position: int):
        """Déplace les pages `sources` juste avant la position `position`
        (glisser-déposer, mode continu ou vignettes)."""
        moving = sorted({s for s in sources if 0 <= s < self.doc.page_count})
        if not moving:
            return
        position = max(0, min(position, self.doc.page_count))
        remaining = [i for i in range(self.doc.page_count) if i not in moving]
        dest = position - sum(1 for s in moving if s < position)
        order = remaining[:dest] + moving + remaining[dest:]
        if order == list(range(self.doc.page_count)):
            return                       # dépôt au même endroit : rien à faire
        try:
            self.doc.select(order)
        except Exception as e:
            QMessageBox.critical(self, "Déplacement",
                                 f"Échec du déplacement :\n{e}")
            return
        self._clear_insert_pos()
        self._mark_dirty()
        self._reload_views()
        # Re-sélectionne les pages déplacées à leur nouvelle position.
        self.page_list.clearSelection()
        for i in range(dest, dest + len(moving)):
            item = self._item_for_index(i)
            if item is not None:
                item.setSelected(True)
        self._refresh_cont_highlight()
        self.statusBar().showMessage(f"{len(moving)} page(s) déplacée(s).")

    # --------------------------------------------------------- Rotation --
    def rotate(self, angle: int):
        targets = self._selected_indices() or list(range(self.doc.page_count))
        pdf_ops.rotate_doc_pages(self.doc, targets, angle)
        self._mark_dirty()
        self._reload_views()
        scope = "sélection" if self.page_list.selectedItems() else "tout le document"
        self.statusBar().showMessage(f"Rotation {angle}° appliquée ({scope}).")

    # ------------------------------------------------------- Suppression --
    def delete_selected(self):
        # Suppr efface d'abord l'annotation reprise, s'il y en a une.
        if self._picked is not None:
            self._delete_picked()
            return
        sel = self._selected_indices()
        if not sel:
            QMessageBox.information(
                self, "Aucune sélection",
                "Sélectionnez d'abord une ou plusieurs pages (mode Vignettes)."
            )
            if not self.single:
                self.btn_thumbs.setChecked(True)
                self._change_mode(1)
            return
        if len(sel) >= self.doc.page_count:
            QMessageBox.information(
                self, "Suppression impossible",
                "Impossible de supprimer toutes les pages du document."
            )
            return
        if QMessageBox.question(
            self, "Supprimer ?",
            f"Supprimer {len(sel)} page(s) du document ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        pdf_ops.delete_doc_pages(self.doc, sel)
        self._clear_insert_pos()
        self._mark_dirty()
        self._reload_views()
        self.statusBar().showMessage(f"{len(sel)} page(s) supprimée(s).")

    # ------------------------------------------------- Outils d'annotation --
    def _set_tool(self, tool: Optional[str]):
        """Active un outil d'annotation (None : retour au mode sélection).

        Les boutons de la barre d'outils s'excluent mutuellement : activer un
        outil relâche les deux autres.
        """
        self._tool = tool
        # Une sélection n'a de sens que dans l'outil qui l'a produite.
        if tool != TOOL_PICK:
            self._picked = None
        if tool != TOOL_TEXT_SELECT:
            self._text_sel = None
        for btn, active in ((self.pick_btn, tool == TOOL_PICK),
                            (self.sel_btn, tool == TOOL_TEXT_SELECT),
                            (self.hl_btn, tool in (TOOL_HL_SELECT, TOOL_HL_PEN)),
                            (self.text_btn, tool == TOOL_TEXT),
                            (self.check_btn, tool == TOOL_CHECK),
                            (self.draw_btn, tool in DRAW_TOOLS)):
            if btn.isChecked() != active:
                btn.blockSignals(True)
                btn.setChecked(active)
                btn.blockSignals(False)
        if tool and self.stack.currentWidget() is not self.cont_area:
            # Les outils dessinent sur la page elle-même : mode continu requis.
            self.btn_continuous.setChecked(True)
            self._change_mode(0)
        self._refresh_tool_icons()
        self._refresh_tool_cursors()
        self._refresh_overlays()
        if tool:
            self.statusBar().showMessage(
                TOOL_HINTS[tool] + "   (Échap : quitter l'outil)")
        else:
            self._update_status()

    def _refresh_tool_icons(self):
        """Icône blanche pour l'outil actif : son bouton est alors sur fond
        navy, où l'icône sombre disparaîtrait."""
        on, off = "#FFFFFF", "#1B3461"
        shape = next((ic for k, _lab, ic in DRAW_SHAPES if k == self._draw_kind),
                     "pen")
        for btn, name in (
            (self.pick_btn, "pointer"),
            (self.sel_btn, "cursor-text"),
            (self.hl_btn,
             "highlight" if self._hl_kind == TOOL_HL_SELECT else "marker"),
            (self.text_btn, "text"),
            (self.draw_btn, shape),
            (self.check_btn, "check"),
        ):
            btn.setIcon(icons.icon(name, on if btn.isChecked() else off))

    def _refresh_tool_cursors(self):
        """Curseur et style d'aperçu des pages selon l'outil actif."""
        if self._tool in (TOOL_TEXT, TOOL_TEXT_SELECT):
            cursor = Qt.IBeamCursor
        elif self._tool in (TOOL_PICK, TOOL_CHECK):
            cursor = Qt.PointingHandCursor
        elif self._tool:
            cursor = Qt.CrossCursor
        else:
            cursor = Qt.ArrowCursor
        for idx, lbl in getattr(self, "_cont_pages", []):
            lbl.setCursor(cursor)
            lbl.set_pen(*self._tool_pen(idx))

    def _tool_pen(self, page_index: int):
        """Style de l'aperçu du tracé : (couleur, épaisseur en pixels, fond)."""
        if self._tool in (TOOL_HL_SELECT, TOOL_HL_PEN):
            color = self._hl_color
            width = self._hl_width if self._tool == TOOL_HL_PEN else 1.0
            fill = None
        elif self._tool in DRAW_TOOLS or self._tool == TOOL_CHECK:
            color, width, fill = self._draw_color, self._draw_width, self._draw_fill
        else:
            return QColor("#1B3461"), 2.0, None
        return (QColor.fromRgbF(*color),
                width * self._page_scale(page_index),
                QColor.fromRgbF(*fill) if fill else None)

    # --------------------------------------- Conversion écran <-> page PDF --
    def _page_view(self, idx: int):
        """Repère d'affichage d'une page : (label, échelle, décalages).

        L'échelle convertit les points PDF en pixels écran ; les décalages
        situent le rendu dans le label, où le pixmap est centré.
        """
        lbl = next((l for i, l in getattr(self, "_cont_pages", []) if i == idx),
                   None)
        if lbl is None:
            return None
        pix = lbl.pixmap()
        if pix is None or pix.isNull():
            return None
        scale = pix.width() / max(1.0, self.doc[idx].rect.width)
        return (lbl, scale,
                (lbl.width() - pix.width()) / 2.0,
                (lbl.height() - pix.height()) / 2.0)

    def _page_scale(self, idx: int) -> float:
        view = self._page_view(idx)
        return view[1] if view else 1.0

    def _to_page_points(self, idx: int, points):
        """Points en coordonnées label -> points de la page affichée (PDF),
        rabattus à l'intérieur de la page."""
        view = self._page_view(idx)
        if view is None:
            return None
        _lbl, scale, off_x, off_y = view
        rect = self.doc[idx].rect
        out = []
        for pt in points:
            x = min(max((pt.x() - off_x) / scale, rect.x0), rect.x1)
            y = min(max((pt.y() - off_y) / scale, rect.y0), rect.y1)
            out.append(fitz.Point(x, y))
        return out

    # ------------------------------------------------ Tracé d'annotations --
    def _on_tool_used(self, idx: int, tool: str, points):
        """Fin d'un tracé sur la page `idx` : l'annotation est écrite au PDF."""
        pts = self._to_page_points(idx, points)
        if not pts or len(pts) < 2:
            return
        moved = max(abs(pts[-1].x - pts[0].x), abs(pts[-1].y - pts[0].y))
        try:
            if tool == TOOL_PICK:
                self._finish_pick(idx, pts, moved)
                return
            if tool == TOOL_TEXT_SELECT:
                self._finish_text_selection(idx)
                return
            if tool == TOOL_CHECK:
                self._check_tool(idx, pts, moved)
                return
            if tool == TOOL_TEXT:
                self._text_tool(idx, pts, moved)
                return
            if tool == TOOL_HL_SELECT:
                rect = fitz.Rect(pts[0], pts[-1])
                rect.normalize()
                if rect.width < 2 or rect.height < 2:
                    return
                kind = pdf_ops.highlight_zone(self.doc, idx, rect, self._hl_color)
                msg = "Texte surligné" if kind == "texte" else "Zone surlignée"
            elif tool == TOOL_HL_PEN:
                if moved < 2:
                    return
                pdf_ops.highlight_stroke(self.doc, idx, pts,
                                         self._hl_color, self._hl_width)
                msg = "Trait de marqueur ajouté"
            else:
                if moved < 2:
                    return
                pdf_ops.add_drawing(self.doc, idx, tool, pts,
                                    color=self._draw_color,
                                    width=self._draw_width,
                                    fill=self._draw_fill)
                msg = DRAW_DONE[tool]
        except Exception as e:
            QMessageBox.critical(self, "Annotation", f"Échec de l'annotation :\n{e}")
            return
        self._mark_dirty()
        self._refresh_page(idx)
        self.statusBar().showMessage(f"{msg} (page {idx + 1}).")

    # ------------------------------------------------------------- Texte --
    def _text_tool(self, idx: int, pts, moved: float):
        """Outil texte : clic sur un texte = modification, glisser =
        déplacement, clic ailleurs = nouveau texte."""
        hit = pdf_ops.annot_at(self.doc, idx, pts[0], families=("text",))
        if hit is not None and moved >= 3:
            origin = (hit["rect"].x0 + (pts[-1].x - pts[0].x),
                      hit["rect"].y0 + (pts[-1].y - pts[0].y))
            pdf_ops.update_text_box(
                self.doc, idx, hit["xref"], hit["text"], font=hit["font"],
                size=hit["size"], color=hit["color"], fill=hit["fill"],
                origin=origin)
            self._mark_dirty()
            self._refresh_page(idx)
            self.statusBar().showMessage(f"Texte déplacé (page {idx + 1}).")
            return
        if hit is not None:
            self._edit_text(idx, hit)
            return
        self._create_text(idx, (pts[0].x, pts[0].y))

    def _create_text(self, idx: int, origin):
        dlg = _TextDialog(self, self._text_style)
        if dlg.exec() != QDialog.Accepted or dlg.deleted:
            return
        values = dlg.values()
        if not values["text"].strip():
            return
        self._remember_text_style(values)
        try:
            pdf_ops.add_text_box(self.doc, idx, origin, values["text"],
                                 font=values["font"], size=values["size"],
                                 color=values["color"], fill=values["fill"])
        except Exception as e:
            QMessageBox.critical(self, "Texte", f"Échec de l'ajout du texte :\n{e}")
            return
        self._mark_dirty()
        self._refresh_page(idx)
        self.statusBar().showMessage(
            f"Texte ajouté (page {idx + 1}) — double-cliquez dessus pour le "
            "modifier, glissez-le avec l'outil texte pour le déplacer."
        )

    def _edit_text(self, idx: int, info: dict):
        """Ré-édition d'un texte existant (contenu et mise en forme)."""
        dlg = _TextDialog(self, info, text=info["text"], editing=True)
        if dlg.exec() != QDialog.Accepted:
            return
        values = dlg.values()
        try:
            if dlg.deleted or not values["text"].strip():
                pdf_ops.delete_annot(self.doc, idx, info["xref"])
                msg = "Texte supprimé"
            else:
                self._remember_text_style(values)
                pdf_ops.update_text_box(
                    self.doc, idx, info["xref"], values["text"],
                    font=values["font"], size=values["size"],
                    color=values["color"], fill=values["fill"])
                msg = "Texte modifié"
        except Exception as e:
            QMessageBox.critical(self, "Texte", f"Échec de la modification :\n{e}")
            return
        self._mark_dirty()
        self._refresh_page(idx)
        self.statusBar().showMessage(f"{msg} (page {idx + 1}).")

    def _remember_text_style(self, values: dict):
        """La mise en forme choisie devient celle du prochain texte."""
        self._text_style = {k: values[k]
                            for k in ("font", "size", "color", "fill")}

    def _on_page_double_clicked(self, idx: int, pos):
        """Double-clic sur une annotation : ouvre sa modification (contenu et
        mise en forme pour un texte, attributs pour un tracé), qu'un outil soit
        actif ou non."""
        pts = self._to_page_points(idx, [pos])
        if not pts:
            return
        hit = pdf_ops.annot_at(self.doc, idx, pts[0])
        if hit is None:
            return
        if hit["family"] == "text":
            self._edit_text(idx, hit)
        else:
            self._edit_shape(idx, hit)

    # -------------------------------- Reprise d'une annotation (déplacer…) --
    def _to_label_rect(self, idx: int, rect) -> Optional[QRect]:
        """Rectangle de la page (coords PDF affichées) -> coords du label."""
        view = self._page_view(idx)
        if view is None:
            return None
        _lbl, scale, off_x, off_y = view
        return QRect(int(rect.x0 * scale + off_x), int(rect.y0 * scale + off_y),
                     max(4, int(rect.width * scale)),
                     max(4, int(rect.height * scale)))

    def _refresh_overlays(self):
        """Reporte sur les pages les repères d'écran : annotation reprise et
        sélection de texte (ils suivent le zoom et la reconstruction des vues)."""
        for idx, lbl in getattr(self, "_cont_pages", []):
            pick = None
            if self._picked is not None and self._picked["page"] == idx:
                pick = self._to_label_rect(idx, self._picked["rect"])
            lbl.set_pick_rect(pick)
            rects = []
            if self._text_sel is not None and self._text_sel["page"] == idx:
                rects = [r for r in (self._to_label_rect(idx, r)
                                     for r in self._text_sel["rects"])
                         if r is not None]
            lbl.set_text_rects(rects)

    def _pick_at(self, idx: int, pos) -> Optional[QRect]:
        """Appui de l'outil de reprise : sélectionne l'annotation sous le
        curseur et renvoie son cadre (coords du label) pour l'aperçu."""
        pts = self._to_page_points(idx, [pos])
        info = pdf_ops.annot_at(self.doc, idx, pts[0]) if pts else None
        if info is None:
            self._picked = None
            self._refresh_overlays()
            self.statusBar().showMessage(
                "Aucune annotation à cet endroit — cliquez sur un texte, un "
                "tracé ou un surlignage pour le reprendre."
            )
            return None
        self._picked = {"page": idx, "xref": info["xref"],
                        "rect": fitz.Rect(info["rect"]), "family": info["family"]}
        self._refresh_overlays()
        self.statusBar().showMessage(
            f"{FAMILY_LABELS[info['family']]} sélectionné : glissez pour "
            "déplacer • double-clic : attributs • Suppr : effacer."
        )
        return self._to_label_rect(idx, info["rect"])

    def _finish_pick(self, idx: int, pts, moved: float):
        """Relâchement de l'outil de reprise : déplacement si la souris a bougé."""
        if self._picked is None or self._picked["page"] != idx or moved < 3:
            return                       # simple clic : la sélection suffit
        fresh = pdf_ops.move_annot(self.doc, idx, self._picked["xref"],
                                   pts[-1].x - pts[0].x, pts[-1].y - pts[0].y)
        if fresh is None:
            QMessageBox.information(
                self, "Déplacement",
                "Cette annotation ne peut pas être déplacée."
            )
            return
        # L'annotation est recréée à sa nouvelle place : son xref change.
        self._picked = {"page": idx, "xref": fresh["xref"],
                        "rect": fitz.Rect(fresh["rect"]),
                        "family": fresh["family"]}
        self._mark_dirty()
        self._refresh_page(idx)
        self._refresh_overlays()
        self.statusBar().showMessage(
            f"{FAMILY_LABELS[fresh['family']]} déplacé (page {idx + 1}).")

    def _delete_picked(self):
        info = self._picked
        if info is None:
            return
        if pdf_ops.delete_annot(self.doc, info["page"], info["xref"]):
            self._picked = None
            self._mark_dirty()
            self._refresh_page(info["page"])
            self._refresh_overlays()
            self.statusBar().showMessage(
                f"{FAMILY_LABELS[info['family']]} supprimé "
                f"(page {info['page'] + 1})."
            )

    def _edit_shape(self, idx: int, info: dict):
        """Change les attributs d'un tracé ou d'un surlignage déjà posé."""
        style = pdf_ops.annot_style(self.doc, idx, info["xref"])
        if style is None:
            return
        dlg = _ShapeDialog(self, style, family=info["family"])
        if dlg.exec() != QDialog.Accepted:
            return
        values = dlg.values()
        try:
            if dlg.deleted:
                pdf_ops.delete_annot(self.doc, idx, info["xref"])
                if self._picked and self._picked["xref"] == info["xref"]:
                    self._picked = None
                msg = f"{FAMILY_LABELS[info['family']]} supprimé"
            else:
                pdf_ops.set_annot_style(
                    self.doc, idx, info["xref"], color=values["color"],
                    width=values["width"], fill=values["fill"])
                if info["family"] == "draw":
                    # Les nouveaux tracés reprennent les réglages choisis ici.
                    self._apply_draw_color(values["color"])
                    self._apply_draw_width(values["width"])
                    self._apply_draw_fill(values["fill"] or None)
                else:
                    self._apply_highlight_color(values["color"])
                msg = f"{FAMILY_LABELS[info['family']]} modifié"
        except Exception as e:
            QMessageBox.critical(self, "Annotation",
                                 f"Échec de la modification :\n{e}")
            return
        self._mark_dirty()
        self._refresh_page(idx)
        self._refresh_overlays()
        self.statusBar().showMessage(f"{msg} (page {idx + 1}).")

    # ------------------------------------------- Sélection de texte (copie) --
    def _live_selection(self, idx: int, start, current):
        """Sélection montrée pendant le glisser : renvoie les rectangles à
        peindre (coords du label)."""
        pts = self._to_page_points(idx, [start, current])
        if pts is None:
            return []
        sel = pdf_ops.select_text(self.doc, idx, pts[0], pts[1])
        self._text_sel = {
            "page": idx,
            "start": (pts[0].x, pts[0].y),
            "stop": (pts[1].x, pts[1].y),
            "text": sel["text"],
            "rects": sel["rects"],
        }
        for other, lbl in getattr(self, "_cont_pages", []):
            if other != idx:
                lbl.set_text_rects([])   # une seule page sélectionnée à la fois
        return [r for r in (self._to_label_rect(idx, r) for r in sel["rects"])
                if r is not None]

    def _has_text_selection(self) -> bool:
        return bool(self._text_sel and (self._text_sel["text"] or "").strip())

    def _finish_text_selection(self, idx: int):
        if self._has_text_selection():
            count = len(self._text_sel["text"].strip())
            self.statusBar().showMessage(
                f"{count} caractères sélectionnés — Ctrl+C : copier • "
                "clic droit : copier ou surligner la sélection."
            )
            return
        self._text_sel = None
        self._refresh_overlays()
        if not pdf_ops.has_text_layer(self.doc, idx):
            self.statusBar().showMessage(
                f"La page {idx + 1} n'a pas de couche de texte (PDF image) : "
                "lancez l'OCR pour pouvoir y sélectionner du texte, ou "
                "utilisez le marqueur pour surligner."
            )
        else:
            self.statusBar().showMessage("Aucun texte sélectionné.")

    def copy_text_selection(self):
        """Copie le texte sélectionné dans le presse-papiers de Windows."""
        if not self._has_text_selection():
            self.statusBar().showMessage(
                "Aucun texte sélectionné : activez l'outil de sélection de "
                "texte puis glissez sur le document."
            )
            return
        text = self._text_sel["text"]
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(
            f"{len(text)} caractères copiés dans le presse-papiers.")

    def highlight_text_selection(self):
        """Surligne le texte sélectionné (comme dans Acrobat)."""
        if not self._has_text_selection():
            self.statusBar().showMessage(
                "Aucun texte sélectionné à surligner : activez l'outil de "
                "sélection de texte puis glissez sur le document."
            )
            return
        sel = self._text_sel
        try:
            count = pdf_ops.highlight_selection(
                self.doc, sel["page"], sel["start"], sel["stop"], self._hl_color)
        except Exception as e:
            QMessageBox.critical(self, "Surlignage", f"Échec du surlignage :\n{e}")
            return
        if not count:
            self.statusBar().showMessage("Aucun texte à surligner.")
            return
        page = sel["page"]
        self._text_sel = None
        self._mark_dirty()
        self._refresh_page(page)
        self._refresh_overlays()
        self.statusBar().showMessage(
            f"{count} ligne(s) surlignée(s) (page {page + 1}).")

    # ------------------------------------------------------ Cases à cocher --
    def _check_tool(self, idx: int, pts, moved: float):
        """Clic de l'outil « cocher » : bascule une case de formulaire, ou
        pose une coche dessinée sur une case imprimée."""
        box = pdf_ops.checkbox_at(self.doc, idx, pts[0]) if moved < 3 else None
        if box is not None:
            state = pdf_ops.toggle_checkbox(self.doc, idx, box["xref"])
            self._mark_dirty()
            self._refresh_page(idx)
            name = f" « {box['name']} »" if box["name"] else ""
            self.statusBar().showMessage(
                f"Case{name} {'cochée' if state else 'décochée'} "
                f"(page {idx + 1})."
            )
            return
        rect = fitz.Rect(pts[0], pts[-1])
        rect.normalize()
        if rect.width < 4 or rect.height < 4:
            # Simple clic : coche de taille courante, centrée sur le clic.
            half = 8.0
            rect = fitz.Rect(pts[0].x - half, pts[0].y - half,
                             pts[0].x + half, pts[0].y + half)
        pdf_ops.add_check_mark(self.doc, idx, rect, color=self._draw_color,
                               width=max(1.5, self._draw_width))
        self._mark_dirty()
        self._refresh_page(idx)
        hint = ("" if pdf_ops.count_checkboxes(self.doc, idx)
                else "  (aucune case de formulaire sur cette page : la coche "
                     "est un tracé, déplaçable et effaçable)")
        self.statusBar().showMessage(f"Coche posée (page {idx + 1}).{hint}")

    # ------------------------------------- Clic droit sur une page (continu) --
    def _on_page_context_menu(self, idx: int, pos):
        pts = self._to_page_points(idx, [pos])
        hit = pdf_ops.annot_at(self.doc, idx, pts[0]) if pts else None
        menu = QMenu(self)
        a_edit = a_del = a_move = a_copy_sel = a_hl_sel = None
        if (self._has_text_selection() and self._text_sel["page"] == idx):
            a_copy_sel = menu.addAction(icons.icon("copy"),
                                        "Copier le texte sélectionné")
            a_hl_sel = menu.addAction(icons.icon("highlight"),
                                      "Surligner le texte sélectionné")
            menu.addSeparator()
        if hit is not None:
            what = {"text": "ce texte", "draw": "ce tracé",
                    "highlight": "ce surlignage"}[hit["family"]]
            if hit["family"] == "text":
                a_edit = menu.addAction(icons.icon("edit"), "Modifier ce texte…")
            else:
                a_edit = menu.addAction(icons.icon("edit"),
                                        f"Modifier {what} (couleur, épaisseur)…")
            a_move = menu.addAction(icons.icon("pointer"),
                                    f"Sélectionner {what} (pour le déplacer)")
            a_del = menu.addAction(icons.icon("trash"), f"Supprimer {what}")
            menu.addSeparator()
        a_hl = menu.addAction("Effacer les surlignages de cette page")
        a_draw = menu.addAction("Effacer les dessins de cette page")
        a_text = menu.addAction("Effacer les textes de cette page")
        lbl = next((l for i, l in getattr(self, "_cont_pages", []) if i == idx),
                   None)
        origin = lbl.mapToGlobal(pos) if lbl is not None else self.pos()
        chosen = menu.exec(origin)
        if chosen is None:
            return
        if chosen is a_copy_sel:
            self.copy_text_selection()
        elif chosen is a_hl_sel:
            self.highlight_text_selection()
        elif chosen is a_edit:
            if hit["family"] == "text":
                self._edit_text(idx, hit)
            else:
                self._edit_shape(idx, hit)
        elif chosen is a_move:
            # Passe à l'outil de reprise, annotation déjà sélectionnée.
            self._set_tool(TOOL_PICK)
            self._pick_at(idx, pos)
        elif chosen is a_del:
            if pdf_ops.delete_annot(self.doc, idx, hit["xref"]):
                if self._picked and self._picked["xref"] == hit["xref"]:
                    self._picked = None
                self._mark_dirty()
                self._refresh_page(idx)
                self._refresh_overlays()
                self.statusBar().showMessage(
                    f"{FAMILY_LABELS[hit['family']]} supprimé (page {idx + 1}).")
        elif chosen is a_hl:
            self._clear_annots([idx], "highlight", "surlignage",
                               f"page {idx + 1}")
        elif chosen is a_draw:
            self._clear_annots([idx], "draw", "dessin", f"page {idx + 1}")
        elif chosen is a_text:
            self._clear_annots([idx], "text", "texte", f"page {idx + 1}")

    # ------------------------------------------- Réglages des outils (menus) --
    def _set_hl_kind(self, kind: str):
        self._hl_kind = kind
        self._set_tool(kind)              # choisir un mode active le surligneur

    def _set_highlight_color(self, name: str):
        self._hl_color = pdf_ops.HIGHLIGHT_COLORS[name]
        for a in self._hl_color_actions:
            a.setChecked(a.text() == name)
        self._set_tool(self._hl_kind)

    def _set_highlight_width(self, value: float):
        self._hl_width = value
        for a, v in self._hl_width_actions:
            a.setChecked(v == value)
        self._set_tool(self._hl_kind)

    def _set_draw_kind(self, kind: str):
        self._draw_kind = kind
        self._refresh_draw_button()
        self._set_tool(kind)

    # Les réglages se mémorisent (_apply_*) sans forcément activer l'outil :
    # les modifier depuis le dialogue d'attributs ne doit pas faire sortir de
    # l'outil de reprise.
    def _apply_draw_color(self, rgb):
        self._draw_color = rgb
        for a, c in self._draw_color_actions:
            a.setChecked(c == rgb)

    def _apply_draw_fill(self, rgb):
        self._draw_fill = rgb
        for a, c in self._draw_fill_actions:
            a.setChecked(c == rgb)

    def _apply_draw_width(self, value: float):
        self._draw_width = value
        for a, v in self._draw_width_actions:
            a.setChecked(v == value)

    def _apply_highlight_color(self, rgb):
        self._hl_color = rgb
        for a in self._hl_color_actions:
            a.setChecked(pdf_ops.HIGHLIGHT_COLORS.get(a.text()) == rgb)

    def _set_draw_color(self, rgb):
        self._apply_draw_color(rgb)
        self._set_tool(self._draw_kind)

    def _set_draw_fill(self, rgb):
        self._apply_draw_fill(rgb)
        self._set_tool(self._draw_kind)

    def _set_draw_width(self, value: float):
        self._apply_draw_width(value)
        self._set_tool(self._draw_kind)

    def _refresh_draw_button(self):
        """Le bouton « dessiner » porte l'icône de la forme choisie."""
        label, icon_name = next(
            ((lab, ic) for k, lab, ic in DRAW_SHAPES if k == self._draw_kind),
            ("Main levée", "pen"))
        self.draw_btn.setIcon(icons.icon(
            icon_name, "#FFFFFF" if self.draw_btn.isChecked() else "#1B3461"))
        self.draw_btn.setToolTip(
            f"Dessiner : {label.lower()}. Flèche : forme, couleur, épaisseur "
            "et remplissage."
        )

    # ---------------------------------------------- Rendu d'une seule page --
    def _refresh_page(self, idx: int):
        """Re-rend une seule page (vue continue + vignette) après annotation."""
        for i, lbl in getattr(self, "_cont_pages", []):
            if i == idx:
                page = self.doc[idx]
                width = int(CONT_BASE * self._zoom)
                z = width / max(1.0, page.rect.width)
                pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
                qpix = QPixmap()
                qpix.loadFromData(pix.tobytes("png"))
                lbl.setPixmap(qpix)
                break
        item = self._item_for_index(idx)
        if item is not None:
            size = int(PAGE_THUMB * self._zoom)
            png = pdf_ops.render_page_to_png(self.doc, idx, max_size=size)
            pm = QPixmap()
            pm.loadFromData(png)
            item.setIcon(QIcon(pm))

    # ------------------------------------------- Effacement d'annotations --
    def _clear_annots(self, indices, family: str, label: str, scope: str = ""):
        try:
            count = pdf_ops.remove_annots(self.doc, indices, (family,))
        except Exception as e:
            QMessageBox.critical(self, "Effacement", f"Échec de l'effacement :\n{e}")
            return
        where = f" ({scope})" if scope else ""
        if not count:
            self.statusBar().showMessage(f"Aucun {label} à effacer{where}.")
            return
        self._mark_dirty()
        self._reload_views()
        self.statusBar().showMessage(f"{count} {label}(s) effacé(s){where}.")

    def _clear_selected_annots(self, family: str, label: str):
        """Efface sur les pages sélectionnées, ou sur tout le document."""
        targets = self._selected_indices() or list(range(self.doc.page_count))
        scope = "sélection" if self.page_list.selectedItems() else "tout le document"
        self._clear_annots(targets, family, label, scope)

    def clear_highlights(self):
        self._clear_selected_annots("highlight", "surlignage")

    def clear_drawings(self):
        self._clear_selected_annots("draw", "dessin")

    def clear_texts(self):
        self._clear_selected_annots("text", "texte")

    def keyPressEvent(self, event):
        """Échap : lève d'abord la sélection en cours, puis quitte l'outil."""
        if event.key() == Qt.Key_Escape:
            if self._picked is not None or self._text_sel is not None:
                self._picked = None
                self._text_sel = None
                self._refresh_overlays()
                self._update_status()
                event.accept()
                return
            if self._tool:
                self._set_tool(None)
                event.accept()
                return
        super().keyPressEvent(event)

    # ----------------------------------------- Copier / couper / coller --
    def copy_pages(self):
        # Avec l'outil de sélection de texte, Ctrl+C copie le texte choisi ;
        # ailleurs, il copie les pages sélectionnées.
        if self._tool == TOOL_TEXT_SELECT and self._has_text_selection():
            self.copy_text_selection()
            return
        sel = self._selected_indices() or ([0] if self.single else [])
        if not sel:
            QMessageBox.information(
                self, "Copier",
                "Sélectionnez d'abord une ou plusieurs pages, même non "
                "contiguës (clic sur chaque page ; Maj+clic : plage)."
            )
            return
        try:
            data = pdf_ops.copy_pages_to_bytes(self.doc, sel)
        except Exception as e:
            QMessageBox.critical(self, "Copier", f"Échec de la copie :\n{e}")
            return
        _PAGE_CLIPBOARD.update(
            data=data, count=len(sel), source=os.path.basename(self.path))
        self.statusBar().showMessage(
            f"{len(sel)} page(s) copiée(s) — collez-les ici ou dans un autre "
            "document ouvert (Ctrl+V ou clic droit)."
        )

    def cut_pages(self):
        sel = self._selected_indices()
        if not sel:
            QMessageBox.information(
                self, "Couper",
                "Sélectionnez d'abord une ou plusieurs pages à couper."
            )
            return
        if len(sel) >= self.doc.page_count:
            QMessageBox.information(
                self, "Couper impossible",
                "Impossible de couper toutes les pages du document."
            )
            return
        try:
            data = pdf_ops.copy_pages_to_bytes(self.doc, sel)
        except Exception as e:
            QMessageBox.critical(self, "Couper", f"Échec de la coupe :\n{e}")
            return
        _PAGE_CLIPBOARD.update(
            data=data, count=len(sel), source=os.path.basename(self.path))
        pdf_ops.delete_doc_pages(self.doc, sel)
        self._clear_insert_pos()
        self._mark_dirty()
        self._reload_views()
        self.statusBar().showMessage(
            f"{len(sel)} page(s) coupée(s) — collez-les ici ou dans un autre "
            "document ouvert (Ctrl+V ou clic droit)."
        )

    def paste_pages(self, at: Optional[int] = None):
        if at is not None and (isinstance(at, bool) or not isinstance(at, int)):
            at = None      # garde-fou : `checked` d'un signal Qt n'est pas une position
        if not _PAGE_CLIPBOARD["data"]:
            QMessageBox.information(
                self, "Coller",
                "Le presse-papiers de pages est vide : copiez ou coupez "
                "d'abord des pages (Ctrl+C / Ctrl+X)."
            )
            return
        if at is None:
            if self._insert_pos is not None:
                at = self._insert_pos      # point d'insertion choisi entre 2 pages
            else:
                sel = self._selected_indices()
                at = (max(sel) + 1) if sel else self.doc.page_count
        at = max(0, min(at, self.doc.page_count))
        try:
            n = pdf_ops.paste_pages_from_bytes(self.doc, _PAGE_CLIPBOARD["data"], at)
        except Exception as e:
            QMessageBox.critical(self, "Coller", f"Échec du collage :\n{e}")
            return
        self._clear_insert_pos()
        self._mark_dirty()
        self._reload_views()
        src = _PAGE_CLIPBOARD["source"]
        self.statusBar().showMessage(
            f"{n} page(s) collée(s) en position {at + 1}"
            + (f" (depuis {src})." if src else ".")
        )

    # --------------------------------------------------------- Découpe --
    def _page_context_menu(self, pos):
        item = self.page_list.itemAt(pos)
        if item is None:
            return
        # clic droit sur une page hors sélection : elle devient la sélection
        if not item.isSelected():
            self.page_list.clearSelection()
            item.setSelected(True)
        row = self.page_list.row(item)
        nsel = len(self.page_list.selectedItems())
        pages_txt = f"les {nsel} pages sélectionnées" if nsel > 1 else "cette page"
        menu = QMenu(self)
        a_rcw = menu.addAction(icons.icon("rotate-cw"), "Pivoter 90° horaire")
        a_rccw = menu.addAction(icons.icon("rotate-ccw"), "Pivoter 90° anti-horaire")
        menu.addSeparator()
        a_copy = menu.addAction(icons.icon("copy"), f"Copier {pages_txt}")
        a_cut = menu.addAction(icons.icon("scissors"), f"Couper {pages_txt}")
        a_paste_b = menu.addAction(icons.icon("clipboard"), "Coller AVANT cette page")
        a_paste_a = menu.addAction(icons.icon("clipboard"), "Coller APRÈS cette page")
        has_clip = bool(_PAGE_CLIPBOARD["data"])
        a_paste_b.setEnabled(has_clip)
        a_paste_a.setEnabled(has_clip)
        menu.addSeparator()
        a_print = menu.addAction(icons.icon("printer"), f"Imprimer {pages_txt}")
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash"), "Supprimer cette page")
        menu.addSeparator()
        a_before = menu.addAction("✂  Découper AVANT cette page")
        a_after = menu.addAction("✂  Découper APRÈS cette page")
        chosen = menu.exec(self.page_list.mapToGlobal(pos))
        idx = item.data(Qt.UserRole)
        if chosen == a_copy:
            self.copy_pages()
        elif chosen == a_cut:
            self.cut_pages()
        elif chosen == a_paste_b:
            self.paste_pages(at=row)
        elif chosen == a_paste_a:
            self.paste_pages(at=row + 1)
        elif chosen == a_rcw:
            pdf_ops.rotate_doc_pages(self.doc, [idx], 90); self._mark_dirty(); self._reload_views()
        elif chosen == a_rccw:
            pdf_ops.rotate_doc_pages(self.doc, [idx], 270); self._mark_dirty(); self._reload_views()
        elif chosen == a_print:
            self.print_selected_pages()
        elif chosen == a_del:
            self.page_list.clearSelection()
            item.setSelected(True)
            self.delete_selected()
        elif chosen == a_before:
            self._split_at(row, before=True)
        elif chosen == a_after:
            self._split_at(row, before=False)

    def _split_at(self, row: int, before: bool):
        order = self._current_order()
        cut = row if before else row + 1
        first, second = order[:cut], order[cut:]
        if not first or not second:
            QMessageBox.information(
                self, "Découpe impossible", "La découpe créerait un document vide."
            )
            return
        base, ext = os.path.splitext(self.path)
        out1, out2 = f"{base}_partie1{ext}", f"{base}_partie2{ext}"
        try:
            pdf_ops.save_doc_pages(self.doc, first, out1)
            pdf_ops.save_doc_pages(self.doc, second, out2)
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Échec de la découpe :\n{e}")
            return
        if self.library:
            self.library.notify_new_file(out1)
            self.library.notify_new_file(out2)
        QMessageBox.information(
            self, "Découpe terminée",
            f"Deux documents créés (compressés) :\n{out1}\n{out2}"
        )

    # -------------------------------------------------------- Imprimer --
    def _printable(self, only_selection: bool = False):
        """Pages à imprimer, dans l'ordre affiché.

        On imprime le document tel qu'il est à l'écran — réordonné, pivoté,
        annoté — et non le fichier sur le disque.
        """
        order = self._current_order()
        if only_selection:
            chosen = set(self._selected_indices())
            if not chosen:
                return []
            order = [index for index in order if index in chosen]
        return printing.pages_of(self.doc, order)

    def _print_ready(self) -> bool:
        if self.doc.page_count == 0:
            QMessageBox.information(
                self, "Imprimer", "Ce document ne contient aucune page.")
            return False
        if not printing.printers_available():
            QMessageBox.warning(
                self, "Aucune imprimante",
                "Aucune imprimante n'est installée sur ce poste.\n\n"
                "Ajoutez-en une dans les paramètres Windows, ou utilisez "
                "« Microsoft Print to PDF » pour produire un fichier."
            )
            return False
        return True

    def print_document(self):
        """Imprime le document ; la boîte système propose la sélection."""
        if not self._print_ready():
            return
        selection = self._printable(only_selection=True)
        printed = printing.print_pages(
            self, self._printable(), title=self.tab_title(),
            selection=selection or None,
        )
        if printed:
            self.statusBar().showMessage(
                f"{printed} page(s) envoyée(s) à l'impression.")
        else:
            self.statusBar().showMessage("Impression annulée.")

    def print_selected_pages(self):
        """Imprime directement les pages sélectionnées (menu contextuel)."""
        if not self._print_ready():
            return
        pages = self._printable(only_selection=True) or self._printable()
        printed = printing.print_pages(self, pages, title=self.tab_title())
        self.statusBar().showMessage(
            f"{printed} page(s) envoyée(s) à l'impression." if printed
            else "Impression annulée."
        )

    def print_preview(self):
        if not self._print_ready():
            return
        printing.preview_pages(self, self._printable(), title=self.tab_title())

    # ----------------------------------------------------- Enregistrer --
    def save_as(self):
        order = self._current_order()
        original = self.path

        # Une seule question : remplacer l'original, ou choisir un autre nom.
        resp = QMessageBox.question(
            self, "Enregistrer",
            "Remplacer le fichier original ?\n\n"
            "Oui  : ecrase le fichier d'origine.\n"
            "Non  : choisir un autre nom de fichier.",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if resp == QMessageBox.Cancel:
            return

        if resp == QMessageBox.Yes:
            out_path = original
        else:
            suggested = pdf_ops.suggest_name_from(original, suffix="_modifie")
            start_path = os.path.join(os.path.dirname(original), suggested)
            out_path, _ = QFileDialog.getSaveFileName(
                self, "Enregistrer sous", start_path, "Fichiers PDF (*.pdf)"
            )
            if not out_path:
                return
            if not out_path.lower().endswith(".pdf"):
                out_path += ".pdf"

        overwrite_current = os.path.abspath(out_path) == os.path.abspath(original)

        # 1) Ecriture dans un fichier temporaire (meme dossier que la cible).
        tmp = out_path + ".tmp_save.pdf"
        try:
            pdf_ops.save_doc_pages(self.doc, order, tmp)
        except Exception as e:
            self._safe_remove(tmp)
            QMessageBox.critical(self, "Erreur", f"Echec de l'enregistrement :\n{e}")
            return

        # 2) On libere notre verrou si on ecrase le fichier en cours.
        if overwrite_current:
            try:
                self.doc.close()
            except Exception:
                pass

        # 3) Remplacement robuste (re-essais en cas de verrou transitoire).
        ok, err = self._safe_replace(tmp, out_path)
        if not ok:
            self._safe_remove(tmp)
            if overwrite_current:
                try:
                    self.doc = fitz.open(original)
                    self.path = original
                except Exception:
                    pass
            QMessageBox.critical(
                self, "Fichier verrouille",
                "Impossible de remplacer le fichier : il est ouvert ou verrouille "
                "par un autre programme (visionneuse/apercu PDF, OneDrive, antivirus).\n\n"
                "Fermez ce programme puis reessayez.\n\nDetail : " + err
            )
            return

        # 4) Rechargement du document enregistre + vues.
        self.path = out_path
        try:
            self.doc = fitz.open(self.path)
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Document enregistre mais non rouvert :\n{e}")
            return
        self._reload_views()
        self._dirty = False
        self._refresh_title()

        # 5) Mise a jour de la liste / vignette dans la bibliotheque.
        if self.library:
            self.library.notify_new_file(out_path)

        self.statusBar().showMessage(f"Enregistre : {out_path}")

    def _safe_replace(self, src, dst):
        """Remplace dst par src avec quelques re-essais (verrous transitoires)."""
        last = ""
        for _ in range(6):
            try:
                os.replace(src, dst)
                return True, ""
            except Exception as e:
                last = str(e)
                time.sleep(0.3)
        return False, last

    def _safe_remove(self, path):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    def _delete_source(self):
        try:
            src = self.path
            os.remove(src)
            if self.library:
                self.library.notify_removed_file(src)
        except OSError:
            pass

    # ------------------------------------------------------------- OCR --
    def run_ocr(self):
        if not ocr.is_available():
            QMessageBox.warning(
                self, "OCR indisponible",
                "Le moteur Tesseract est introuvable. Placez-le dans le dossier "
                "'tesseract/' (voir README) ou installez Tesseract-OCR."
            )
            return
        original = self.path
        # Meme logique que l'enregistrement : remplacer l'original ou choisir un nom.
        resp = QMessageBox.question(
            self, "OCR",
            "Remplacer le fichier original par sa version cherchable (OCR) ?\n\n"
            "Oui  : ecrase le fichier d'origine.\n"
            "Non  : choisir un autre nom de fichier.",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes,
        )
        if resp == QMessageBox.Cancel:
            return
        if resp == QMessageBox.Yes:
            out_path = original
        else:
            suggested = pdf_ops.suggest_name_from(original, suffix="_ocr")
            start = os.path.join(os.path.dirname(original), suggested)
            out_path, _ = QFileDialog.getSaveFileName(
                self, "Enregistrer le PDF cherchable (OCR)", start, "Fichiers PDF (*.pdf)"
            )
            if not out_path:
                return
            if not out_path.lower().endswith(".pdf"):
                out_path += ".pdf"

        # OCR sur l'état courant (édité) du document : source dans un temporaire.
        self._ocr_src_tmp = os.path.join(tempfile.gettempdir(), "gpdf_ocr_src.pdf")
        try:
            pdf_ops.save_doc_pages(self.doc, self._current_order(), self._ocr_src_tmp)
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Préparation OCR échouée :\n{e}")
            return
        self._ocr_final = out_path
        self._ocr_out_tmp = out_path + ".ocr_tmp.pdf"
        self._progress = QProgressDialog("Préparation de l'OCR…", "Annuler", 0, 100, self)
        self._progress.setWindowTitle("OCR en cours")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._ocr_worker = OcrWorker(self._ocr_src_tmp, self._ocr_out_tmp)
        self._ocr_worker.progress.connect(self._on_ocr_progress)
        self._ocr_worker.done.connect(self._on_ocr_done)
        self._ocr_worker.failed.connect(self._on_ocr_failed)
        self._progress.canceled.connect(self._ocr_worker.requestInterruption)
        self._ocr_worker.start()

    def _on_ocr_progress(self, current, total, message):
        if self._progress is None:
            return
        if total > 0:
            self._progress.setMaximum(total)
            self._progress.setValue(current)
        self._progress.setLabelText(message)

    def _on_ocr_done(self, lang):
        if self._progress:
            self._progress.close()
        final = getattr(self, "_ocr_final", None)
        out_tmp = getattr(self, "_ocr_out_tmp", None)
        self._safe_remove(getattr(self, "_ocr_src_tmp", ""))
        if not final or not out_tmp:
            return

        overwrite_current = os.path.abspath(final) == os.path.abspath(self.path)
        if overwrite_current:
            try:
                self.doc.close()
            except Exception:
                pass
        ok, err = self._safe_replace(out_tmp, final)
        if not ok:
            self._safe_remove(out_tmp)
            if overwrite_current:
                try:
                    self.doc = fitz.open(self.path)
                except Exception:
                    pass
            QMessageBox.critical(
                self, "Fichier verrouille",
                "Impossible de remplacer le fichier : il est ouvert ou verrouille "
                "par un autre programme.\n\nDetail : " + err
            )
            return

        if overwrite_current:
            self.path = final
            try:
                self.doc = fitz.open(self.path)
            except Exception:
                pass
            self._reload_views()
            self._dirty = False
            self._refresh_title()

        if self.library:
            self.library.notify_new_file(final)
        QMessageBox.information(
            self, "OCR terminé",
            f"Document cherchable créé (langue : {lang}) et compressé :\n{final}"
        )

    def _on_ocr_failed(self, msg):
        if self._progress:
            self._progress.close()
        self._safe_remove(getattr(self, "_ocr_src_tmp", ""))
        self._safe_remove(getattr(self, "_ocr_out_tmp", ""))
        QMessageBox.critical(self, "Erreur OCR", f"Échec de l'OCR :\n{msg}")

    # ----------------------------------------------------------- Cycle --
    def closeEvent(self, event):
        try:
            if self.doc:
                self.doc.close()
        except Exception:
            pass
        super().closeEvent(event)
