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
- suppression des pages sélectionnées ;
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

Surlignage (mode continu) : bouton surligneur puis glisser à la souris —
texte surligné mot à mot (comme Acrobat) ou aplat semi-transparent sur une
image/zone sans texte ; couleur au choix ; effacement possible.

Le document est édité en mémoire ; « Enregistrer sous… » écrit un nouveau PDF
compressé (proposition de nom, option de suppression de la source). OCR possible.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import List, Optional

import fitz
from PySide6.QtCore import Qt, QMimeData, QRect, QSize, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QDrag, QKeySequence, QMouseEvent, QPainter, QPen,
    QPixmap, QIcon,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QListWidgetItem, QListView,
    QToolBar, QFileDialog, QMessageBox, QStackedWidget, QScrollArea, QWidget,
    QVBoxLayout, QLabel, QMenu, QProgressDialog, QComboBox, QToolButton,
    QButtonGroup, QFrame, QHBoxLayout, QRubberBand,
)

from . import pdf_ops, ocr, icons

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
    glisser-déposer (réorganisation) et, en mode surligneur, sélection d'une
    zone à la souris (bande élastique)."""
    clicked = Signal(int)
    regionSelected = Signal(int, object)   # (index page, QRect en coords label)

    def __init__(self, index: int, highlight_mode=lambda: False,
                 drag_set=None):
        super().__init__()
        self._index = index
        self._sel = False
        self._hl_mode = highlight_mode      # callable -> bool
        self._drag_set = drag_set or (lambda i: [i])   # callable -> indices à déplacer
        self._band: Optional[QRubberBand] = None
        self._press_pos = None
        self._drag_origin = None
        self.setAlignment(Qt.AlignCenter)
        self._restyle()

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
        if event.button() == Qt.LeftButton and self._hl_mode():
            self._press_pos = event.pos()
            if self._band is None:
                self._band = QRubberBand(QRubberBand.Rectangle, self)
            self._band.setGeometry(QRect(self._press_pos, QSize()))
            self._band.show()
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
        if self._press_pos is not None and self._band is not None:
            self._band.setGeometry(QRect(self._press_pos, event.pos()).normalized())
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
        if self._press_pos is not None and event.button() == Qt.LeftButton:
            rect = QRect(self._press_pos, event.pos()).normalized()
            self._band.hide()
            self._press_pos = None
            if rect.width() < 5 and rect.height() < 5:
                self.clicked.emit(self._index)   # simple clic : (dé)sélection
            else:
                self.regionSelected.emit(self._index, rect)
            event.accept()
            return
        if self._drag_origin is not None and event.button() == Qt.LeftButton:
            self._drag_origin = None
            self.clicked.emit(self._index)       # simple clic : (dé)sélection
            event.accept()
            return
        super().mouseReleaseEvent(event)

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


class ViewerWindow(QMainWindow):
    titleChanged = Signal()

    def __init__(self, path: str, library=None):
        super().__init__()
        self.path = path
        self.library = library
        self.doc = fitz.open(path)        # document de travail (édité en mémoire)
        self._zoom = 1.0
        self._dirty = False
        self._hl_mode = False
        self._hl_color = pdf_ops.HIGHLIGHT_COLORS["Jaune"]
        self._insert_pos: Optional[int] = None   # point d'insertion du collage
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
                "Zoom : molette + Ctrl • surligneur dans la barre d'outils"
            )
        else:
            self.statusBar().showMessage(
                "Clic : (dé)sélectionner des pages, même non contiguës "
                "(Maj+clic : plage) • glisser la sélection pour réordonner "
                "• clic entre 2 pages : point d'insertion du collage "
                "• clic droit : pivoter / copier / coller / supprimer / découper "
                "• Ctrl+C/X/V : copier, couper, coller des pages"
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
        self.act_del.setToolTip("Supprimer la/les page(s) sélectionnée(s)")
        self.act_del.triggered.connect(self.delete_selected)
        tb.addAction(self.act_del)
        tb.addSeparator()

        # Surligneur (comme Acrobat) : bouton bascule + menu de couleurs.
        self.hl_btn = QToolButton(self)
        self.hl_btn.setCheckable(True)
        self.hl_btn.setIcon(icons.icon("highlight"))
        self.hl_btn.setToolTip(
            "Surligner : glissez sur du texte (surlignage mot à mot) ou sur "
            "une image/zone (aplat de couleur). Flèche : choix de la couleur."
        )
        self.hl_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.hl_btn.toggled.connect(self._set_highlight_mode)
        hl_menu = QMenu(self.hl_btn)
        self._hl_color_actions = []
        for name, rgb in pdf_ops.HIGHLIGHT_COLORS.items():
            a = hl_menu.addAction(self._color_icon(rgb), name)
            a.setCheckable(True)
            a.setChecked(name == "Jaune")
            a.triggered.connect(
                lambda checked=False, n=name: self._set_highlight_color(n))
            self._hl_color_actions.append(a)
        hl_menu.addSeparator()
        hl_menu.addAction(icons.icon("trash"),
                          "Effacer les surlignages (sélection/tout)",
                          self.clear_highlights)
        self.hl_btn.setMenu(hl_menu)
        tb.addWidget(self.hl_btn)
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
            lbl = _ContPage(idx, highlight_mode=lambda: self._hl_mode,
                            drag_set=self._drag_set)
            lbl.setPixmap(qpix)
            lbl.set_selected(idx in selected)
            lbl.clicked.connect(self._toggle_page_selection)
            lbl.regionSelected.connect(self._on_region_selected)
            lbl.setCursor(Qt.CrossCursor if self._hl_mode else Qt.ArrowCursor)
            self.cont_layout.addWidget(lbl)
            self._cont_pages.append((idx, lbl))
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

    # ------------------------------------------------------- Surlignage --
    @staticmethod
    def _color_icon(rgb) -> QIcon:
        """Petite pastille de couleur pour le menu du surligneur."""
        pm = QPixmap(18, 18)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setBrush(QColor.fromRgbF(*rgb))
        p.setPen(QColor("#8F99AD"))
        p.drawRoundedRect(1, 1, 15, 15, 3, 3)
        p.end()
        return QIcon(pm)

    def _set_highlight_color(self, name: str):
        self._hl_color = pdf_ops.HIGHLIGHT_COLORS[name]
        for a in self._hl_color_actions:
            a.setChecked(a.text() == name)
        if not self.hl_btn.isChecked():
            self.hl_btn.setChecked(True)   # choisir une couleur active le mode

    def _set_highlight_mode(self, on: bool):
        self._hl_mode = on
        if on and self.stack.currentWidget() is not self.cont_area:
            self.btn_continuous.setChecked(True)
            self._change_mode(0)
        for _idx, lbl in getattr(self, "_cont_pages", []):
            lbl.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        if on:
            self.statusBar().showMessage(
                "Surligneur actif : glissez sur du texte ou une zone à surligner."
            )
        else:
            self._update_status()

    def _on_region_selected(self, idx: int, qrect):
        """Zone sélectionnée à la souris (mode surligneur) sur la page `idx`."""
        if not self._hl_mode:
            return
        lbl = next((l for i, l in self._cont_pages if i == idx), None)
        if lbl is None or lbl.pixmap() is None or lbl.pixmap().isNull():
            return
        pix = lbl.pixmap()
        # coords label -> coords pixmap (le pixmap est centré dans le label)
        off_x = (lbl.width() - pix.width()) / 2.0
        off_y = (lbl.height() - pix.height()) / 2.0
        page = self.doc[idx]
        z = pix.width() / max(1.0, page.rect.width)
        rect = fitz.Rect(
            (qrect.left() - off_x) / z, (qrect.top() - off_y) / z,
            (qrect.right() - off_x) / z, (qrect.bottom() - off_y) / z,
        ) & page.rect
        if rect.is_empty or rect.width < 1 or rect.height < 1:
            return
        try:
            kind = pdf_ops.highlight_zone(self.doc, idx, rect, self._hl_color)
        except Exception as e:
            QMessageBox.critical(self, "Surlignage", f"Échec du surlignage :\n{e}")
            return
        self._mark_dirty()
        self._refresh_page(idx)
        msg = "Texte surligné" if kind == "texte" else "Zone surlignée"
        self.statusBar().showMessage(f"{msg} (page {idx + 1}).")

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

    def clear_highlights(self):
        targets = self._selected_indices() or list(range(self.doc.page_count))
        count = pdf_ops.remove_highlights(self.doc, targets)
        if not count:
            self.statusBar().showMessage("Aucun surlignage à effacer.")
            return
        self._mark_dirty()
        self._reload_views()
        scope = "sélection" if self.page_list.selectedItems() else "tout le document"
        self.statusBar().showMessage(
            f"{count} surlignage(s) effacé(s) ({scope}).")

    # ----------------------------------------- Copier / couper / coller --
    def copy_pages(self):
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
