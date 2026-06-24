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
- réorganisation par glisser-déposer ;
- clic droit : pivoter / supprimer / découper avant ou après la page.

Le document est édité en mémoire ; « Enregistrer sous… » écrit un nouveau PDF
compressé (proposition de nom, option de suppression de la source). OCR possible.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import List, Optional

import fitz
from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QAction, QPixmap, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QListWidget, QListWidgetItem, QListView, QToolBar,
    QFileDialog, QMessageBox, QStackedWidget, QScrollArea, QWidget,
    QVBoxLayout, QLabel, QMenu, QProgressDialog, QComboBox, QToolButton,
    QButtonGroup, QFrame, QHBoxLayout,
)

from . import pdf_ops, ocr, icons

PAGE_THUMB = 230
CONT_BASE = 780
ZOOM_MIN = 0.25
ZOOM_MAX = 5.0


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


class _ContPage(QLabel):
    """Page affichée en mode continu, cliquable et surlignable (sélection)."""
    clicked = Signal(int)

    def __init__(self, index: int):
        super().__init__()
        self._index = index
        self._sel = False
        self.setAlignment(Qt.AlignCenter)
        self._restyle()

    def _restyle(self):
        if self._sel:
            self.setStyleSheet("margin:6px;border:3px solid #2d7ef7;background:#e9f1ff;")
        else:
            self.setStyleSheet("margin:6px;border:1px solid #ccc;")

    def set_selected(self, value: bool):
        if self._sel != value:
            self._sel = value
            self._restyle()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._index)
        super().mousePressEvent(event)


class ViewerWindow(QMainWindow):
    titleChanged = Signal()

    def __init__(self, path: str, library=None):
        super().__init__()
        self.path = path
        self.library = library
        self.doc = fitz.open(path)        # document de travail (édité en mémoire)
        self._zoom = 1.0
        self._dirty = False
        self._reloading = False
        self._ocr_worker: Optional[OcrWorker] = None
        self._progress: Optional[QProgressDialog] = None

        self._refresh_title()
        self.resize(960, 820)

        self._build_toolbar()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # --- Mode vignettes (sélection + réorganisation) ---
        self.page_list = QListWidget()
        self.page_list.setViewMode(QListView.IconMode)
        self.page_list.setResizeMode(QListView.Adjust)
        self.page_list.setMovement(QListView.Snap)
        self.page_list.setDragDropMode(QListWidget.InternalMove)
        self.page_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.page_list.setSpacing(12)
        self.page_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.page_list.customContextMenuRequested.connect(self._page_context_menu)
        self.page_list.model().rowsMoved.connect(self._on_rows_moved)
        self.page_list.itemSelectionChanged.connect(self._refresh_cont_highlight)
        self.stack.addWidget(self.page_list)

        # --- Mode continu / grand ---
        self.cont_area = QScrollArea()
        self.cont_area.setWidgetResizable(True)
        self.cont_inner = QWidget()
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
            self.statusBar().showMessage("Zoom : molette + Ctrl, ou les boutons")
        else:
            self.statusBar().showMessage(
                "Vignettes : sélection multi (Ctrl/Maj) • glisser pour réordonner "
                "• clic droit pour pivoter / supprimer / découper"
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
        self._reloading = True
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
        self._reloading = False

    def _build_continuous(self):
        while self.cont_layout.count():
            it = self.cont_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._cont_pages = []
        selected = set(self._selected_indices())
        width = int(CONT_BASE * self._zoom)
        for idx in range(self.doc.page_count):
            page = self.doc[idx]
            z = width / max(1.0, page.rect.width)
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            qpix = QPixmap()
            qpix.loadFromData(pix.tobytes("png"))
            lbl = _ContPage(idx)
            lbl.setPixmap(qpix)
            lbl.set_selected(idx in selected)
            lbl.clicked.connect(self._toggle_page_selection)
            self.cont_layout.addWidget(lbl)
            self._cont_pages.append((idx, lbl))

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
        on, off = "#ffffff", "#243044"
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
    def _on_rows_moved(self, *args):
        if self._reloading:
            return
        order = self._current_order()
        if order and order != list(range(self.doc.page_count)):
            try:
                self.doc.select(order)   # applique le nouvel ordre au document
            except Exception:
                pass
            self._mark_dirty()
            self._reload_views()

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
        self._mark_dirty()
        self._reload_views()
        self.statusBar().showMessage(f"{len(sel)} page(s) supprimée(s).")

    # --------------------------------------------------------- Découpe --
    def _page_context_menu(self, pos):
        item = self.page_list.itemAt(pos)
        if item is None:
            return
        row = self.page_list.row(item)
        menu = QMenu(self)
        a_rcw = menu.addAction(icons.icon("rotate-cw"), "Pivoter 90° horaire")
        a_rccw = menu.addAction(icons.icon("rotate-ccw"), "Pivoter 90° anti-horaire")
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash"), "Supprimer cette page")
        menu.addSeparator()
        a_before = menu.addAction("✂  Découper AVANT cette page")
        a_after = menu.addAction("✂  Découper APRÈS cette page")
        chosen = menu.exec(self.page_list.mapToGlobal(pos))
        idx = item.data(Qt.UserRole)
        if chosen == a_rcw:
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
