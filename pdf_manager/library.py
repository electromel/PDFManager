"""
library.py
==========
Fenêtre principale : la « bibliothèque » de PDF.

- Glisser-déposer de fichiers PDF, ou ajout via une boîte de dialogue.
- Affichage des vignettes de la 1ère page de chaque PDF.
- Sélection multiple numérotée (1, 2, 3…) ; re-cliquer désélectionne et
  renumérote les suivants.
- Fusion des documents sélectionnés (dans l'ordre des numéros).
- Double-clic : ouvre la visionneuse du document.
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QSize, QThread
from PySide6.QtGui import QAction, QPixmap, QFont
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QWidget, QScrollArea, QMainWindow,
    QFileDialog, QMessageBox, QToolBar, QInputDialog, QSizePolicy,
    QProgressDialog, QLineEdit, QDialog, QListWidget, QListWidgetItem,
    QHBoxLayout, QPushButton, QTabWidget, QSplitter, QMenu,
)

from . import pdf_ops, ocr
from .flowlayout import FlowLayout
from . import icons

THUMB_MAX = 260
CARD_W = 300


class SearchResultsDialog(QDialog):
    """Affiche les résultats de recherche ; double-clic ouvre le document."""

    def __init__(self, results, query, on_open, parent=None):
        super().__init__(parent)
        self.on_open = on_open
        self.setWindowTitle(f"Résultats pour « {query} »")
        self.resize(560, 420)
        lay = QVBoxLayout(self)

        total = sum(len(r["pages"]) for r in results)
        ndocs = sum(1 for r in results if r["pages"])
        lay.addWidget(QLabel(
            f"{total} page(s) trouvée(s) dans {ndocs} document(s)."
            if total else "Aucune correspondance."
        ))

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.list)

        for r in results:
            name = os.path.basename(r["path"])
            if r["pages"]:
                pages = ", ".join(str(n) for n in r["pages"])
                txt = f"📄  {name}  —  pages : {pages}"
            elif not r["has_text"]:
                txt = f"⚠  {name}  —  pas de texte (document scanné ? lancez l'OCR)"
            else:
                txt = f"—  {name}  —  aucune correspondance"
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, r["path"])
            if not r["pages"]:
                it.setForeground(Qt.gray)
            self.list.addItem(it)

        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("Fermer")
        btn.clicked.connect(self.accept)
        row.addWidget(btn)
        lay.addLayout(row)

    def _open(self, item):
        path = item.data(Qt.UserRole)
        if path and self.on_open:
            self.on_open(path)


class MultiOcrWorker(QThread):
    """OCR de plusieurs documents en arrière-plan (un fichier *_ocr.pdf par source)."""
    progress = Signal(int, int, str)   # pages traitées, pages totales, message
    done = Signal(list)                # chemins créés
    failed = Signal(str)

    def __init__(self, paths, replace=True):
        super().__init__()
        self.paths = list(paths)
        self.replace = replace

    @staticmethod
    def _safe_replace(src, dst):
        for _ in range(6):
            try:
                os.replace(src, dst)
                return True
            except Exception:
                time.sleep(0.3)
        return False

    def run(self):
        try:
            totals = [(p, max(1, pdf_ops.page_count(p))) for p in self.paths]
            total_pages = sum(n for _, n in totals) or 1
            outputs = []
            base_done = 0
            for p, n in totals:
                name = os.path.basename(p)

                def cb(c, t, m, _bd=base_done, _name=name):
                    self.progress.emit(_bd + max(0, c), total_pages, f"{_name} — {m}")

                if self.replace:
                    # OCR vers un temporaire, puis remplacement de l'original.
                    tmp = p + ".ocr_tmp.pdf"
                    ocr.ocr_document(p, tmp, progress=cb)
                    if self._safe_replace(tmp, p):
                        outputs.append(p)
                    else:
                        # repli : si l'original est verrouille, on garde une copie _ocr
                        alt = os.path.join(
                            os.path.dirname(p), pdf_ops.suggest_name_from(p, "_ocr")
                        )
                        if self._safe_replace(tmp, alt):
                            outputs.append(alt)
                else:
                    out = os.path.join(
                        os.path.dirname(p), pdf_ops.suggest_name_from(p, "_ocr")
                    )
                    ocr.ocr_document(p, out, progress=cb)
                    outputs.append(out)
                base_done += n
            self.done.emit(outputs)
        except Exception as e:
            self.failed.emit(str(e))


class PdfCard(QFrame):
    """Vignette cliquable représentant un document PDF."""

    clicked = Signal(str)
    doubleClicked = Signal(str)
    rightClicked = Signal(str, object)   # (path, position globale)

    def __init__(self, path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = path
        self._selected_number: Optional[int] = None
        self._active: bool = False        # document actuellement affiché à droite

        self.setObjectName("PdfCard")
        self.setFixedWidth(CARD_W)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Vignette
        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFixedHeight(THUMB_MAX + 16)
        self.thumb.setStyleSheet(
            "background:#F4F5F8;border:1px solid #D5D9E2;border-radius:0;")
        png = pdf_ops.render_first_page_png(path, max_size=THUMB_MAX)
        if png:
            pix = QPixmap()
            pix.loadFromData(png)
            self.thumb.setPixmap(pix)
        else:
            self.thumb.setText("PDF illisible")
        layout.addWidget(self.thumb)

        # Badge de sélection (au-dessus de la vignette)
        self.badge = QLabel("", self.thumb)
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedSize(36, 36)
        self.badge.move(12, 12)
        f_badge = QFont(); f_badge.setPointSize(13); f_badge.setBold(True)
        self.badge.setFont(f_badge)
        self.badge.setStyleSheet(
            "background:#B8892C;color:white;border-radius:18px;font-weight:bold;"
            "border:2px solid white;"
        )
        self.badge.hide()

        # Nom du fichier
        name = os.path.basename(path)
        self.name_label = QLabel(name)
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.name_label.setFixedHeight(46)
        f = QFont()
        f.setPointSize(10)
        self.name_label.setFont(f)
        layout.addWidget(self.name_label)

        # Nombre de pages
        n = pdf_ops.page_count(path)
        self.pages_label = QLabel(f"{n} page(s)")
        self.pages_label.setAlignment(Qt.AlignCenter)
        self.pages_label.setStyleSheet(
            "color:#8F99AD;font-family:Consolas,monospace;font-size:10px;"
        )
        gf = QFont("Consolas")
        gf.setPointSize(8)
        self.pages_label.setFont(gf)
        layout.addWidget(self.pages_label)

    def _apply_style(self):
        if self._selected_number is not None:
            self.setStyleSheet(
                "#PdfCard{"
                "background:#FEF8EE;"
                "border-top:1px solid #D5D9E2;"
                "border-right:1px solid #D5D9E2;"
                "border-bottom:1px solid #D5D9E2;"
                "border-left:4px solid #B8892C;"
                "border-radius:0;}"
            )
        elif self._active:
            self.setStyleSheet(
                "#PdfCard{"
                "background:#F5F2E8;"
                "border-top:1px solid #D5D9E2;"
                "border-right:1px solid #D5D9E2;"
                "border-bottom:1px solid #D5D9E2;"
                "border-left:4px solid #B8892C;"
                "border-radius:0;}"
            )
        else:
            self.setStyleSheet(
                "#PdfCard{"
                "background:#FFFFFF;"
                "border-top:1px solid #D5D9E2;"
                "border-right:1px solid #D5D9E2;"
                "border-bottom:1px solid #D5D9E2;"
                "border-left:4px solid transparent;"
                "border-radius:0;}"
                "#PdfCard:hover{"
                "border-left:4px solid #1B3461;"
                "border-top:1px solid #C8D0DB;"
                "border-right:1px solid #C8D0DB;"
                "border-bottom:1px solid #C8D0DB;}"
            )

    def set_active(self, active: bool):
        if self._active != active:
            self._active = active
            self._apply_style()

    def reload(self):
        """Recharge la vignette et le nombre de pages depuis le fichier (après
        une modification enregistrée sous le même nom)."""
        png = pdf_ops.render_first_page_png(self.path, max_size=THUMB_MAX)
        if png:
            pix = QPixmap()
            pix.loadFromData(png)
            self.thumb.setPixmap(pix)
        else:
            self.thumb.setText("PDF illisible")
        n = pdf_ops.page_count(self.path)
        self.pages_label.setText(f"{n} page(s)")

    def set_selected_number(self, number: Optional[int]):
        self._selected_number = number
        if number is None:
            self.badge.hide()
        else:
            self.badge.setText(str(number))
            self.badge.show()
        self._apply_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.path)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        self.rightClicked.emit(self.path, event.globalPos())


class LibraryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Manager")
        self.resize(1000, 720)
        self.setAcceptDrops(True)

        self._cards: Dict[str, PdfCard] = {}
        self._order: List[str] = []          # ordre d'ajout
        self._selection: List[str] = []      # ordre de sélection (numérotation)
        self._open_tabs: dict = {}           # path -> panneau visionneuse (onglet)

        self._build_toolbar()

        # Zone de défilement avec galerie de vignettes
        self.container = QWidget()
        self.flow = FlowLayout(self.container)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.container)

        # Volet droit : onglets de visionneuses (caché tant qu'aucun PDF ouvert)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_context_menu)
        self.tabs.hide()

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.scroll)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)

        self._empty_hint = QLabel(
            "Glissez-déposez des fichiers PDF ici\nou utilisez « Ajouter des PDF »",
            self.container,
        )
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setStyleSheet(
            "color:#8F99AD;font-size:13px;font-family:'Segoe UI Variable','Segoe UI',sans-serif;"
        )
        self._update_empty_hint()

        self.statusBar().showMessage("Prêt")

    # ----------------------------------------------------------------- UI --
    def _build_toolbar(self):
        tb = QToolBar("Actions")
        tb.setMovable(False)
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        # Icône seule (le texte complet reste en infobulle)
        act_add = QAction(icons.icon("file-plus"), "", self)
        act_add.setToolTip("Ajouter des PDF")
        act_add.triggered.connect(self.add_dialog)
        tb.addAction(act_add)

        tb.addSeparator()

        self.act_merge = QAction(icons.icon("merge"), "Fusion", self)
        self.act_merge.setToolTip("Fusionner la sélection")
        self.act_merge.triggered.connect(self.merge_selection)
        tb.addAction(self.act_merge)

        self.act_ocr = QAction(icons.icon("ocr"), "OCR", self)
        self.act_ocr.setToolTip("OCR sur la sélection")
        self.act_ocr.triggered.connect(self.ocr_selection)
        tb.addAction(self.act_ocr)

        self.act_open = QAction(icons.icon("eye"), "Ouvrir", self)
        self.act_open.setToolTip("Ouvrir le document sélectionné dans le volet de droite")
        self.act_open.triggered.connect(self._open_selected_single)
        tb.addAction(self.act_open)

        tb.addSeparator()

        self.act_select_all = QAction(icons.icon("check"), "Tout sélectionner", self)
        self.act_select_all.setToolTip("Tout sélectionner / désélectionner")
        self.act_select_all.triggered.connect(self.toggle_select_all)
        tb.addAction(self.act_select_all)

        self.act_remove = QAction(icons.icon("trash"), "", self)
        self.act_remove.setToolTip("Retirer de la liste (option : supprimer du disque)")
        self.act_remove.triggered.connect(self.remove_selected)
        tb.addAction(self.act_remove)

        tb.addSeparator()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Rechercher dans la sélection…")
        self.search_edit.setMaximumWidth(240)
        self.search_edit.returnPressed.connect(self.search_selection)
        tb.addWidget(self.search_edit)
        act_search = QAction(icons.icon("search"), "", self)
        act_search.setToolTip("Rechercher")
        act_search.triggered.connect(self.search_selection)
        tb.addAction(act_search)

    def _update_empty_hint(self):
        if self._order:
            self._empty_hint.hide()
        else:
            self._empty_hint.setGeometry(0, 0, self.container.width() or 800, 400)
            self._empty_hint.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._order:
            self._empty_hint.setGeometry(0, 0, self.container.width(), 300)

    # ------------------------------------------------------ Ajout fichiers --
    def add_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Ajouter des PDF", "", "Fichiers PDF (*.pdf)"
        )
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths: List[str]):
        added = 0
        for p in paths:
            if not p.lower().endswith(".pdf"):
                continue
            if p in self._cards:
                continue
            if not os.path.isfile(p):
                continue
            card = PdfCard(p)
            card.clicked.connect(self.toggle_selection)
            card.doubleClicked.connect(self.open_viewer)
            card.rightClicked.connect(self._card_context_menu)
            self.flow.addWidget(card)
            self._cards[p] = card
            self._order.append(p)
            added += 1
        if added:
            self._relayout_sorted()
        self._update_empty_hint()
        if added:
            self.statusBar().showMessage(f"{added} document(s) ajouté(s)")

    def _relayout_sorted(self):
        """Ordonne les cartes par nom de fichier (insensible à la casse)."""
        self._order.sort(key=lambda p: os.path.basename(p).lower())
        for p in self._order:
            card = self._cards.get(p)
            if card:
                self.flow.removeWidget(card)
        for p in self._order:
            card = self._cards.get(p)
            if card:
                self.flow.addWidget(card)
        self.container.updateGeometry()

    # ---------------------------------------------------- Glisser-déposer --
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if any(u.toLocalFile().lower().endswith(".pdf") for u in event.mimeData().urls()):
                event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self.add_paths(paths)

    # --------------------------------------------------------- Sélection --
    def toggle_selection(self, path: str):
        if path in self._selection:
            self._selection.remove(path)
        else:
            self._selection.append(path)
        self._refresh_badges()

    def clear_selection(self):
        self._selection.clear()
        self._refresh_badges()

    def toggle_select_all(self):
        if self._order and len(self._selection) == len(self._order):
            self._selection.clear()
        else:
            self._selection = list(self._order)
        self._refresh_badges()

    def _refresh_badges(self):
        for p, card in self._cards.items():
            if p in self._selection:
                card.set_selected_number(self._selection.index(p) + 1)
            else:
                card.set_selected_number(None)
        if self._order and len(self._selection) == len(self._order):
            self.act_select_all.setText("Tout désélectionner")
        else:
            self.act_select_all.setText("Tout sélectionner")
        self.statusBar().showMessage(f"{len(self._selection)} sélectionné(s)")

    def remove_selected(self):
        targets = list(self._selection) if self._selection else []
        if not targets:
            QMessageBox.information(
                self, "Aucune sélection",
                "Sélectionnez d'abord un ou plusieurs documents."
            )
            return

        self._remove_paths(targets)

    def _remove_paths(self, targets):
        """Propose de retirer de la liste (défaut) ou supprimer aussi du disque."""
        if not targets:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Retirer le(s) document(s)")
        box.setText(
            f"{len(targets)} document(s).\n\nQue souhaitez-vous faire ?"
        )
        btn_list = box.addButton("Retirer de la liste", QMessageBox.AcceptRole)
        btn_disk = box.addButton("Supprimer aussi du disque", QMessageBox.DestructiveRole)
        box.addButton("Annuler", QMessageBox.RejectRole)
        box.setDefaultButton(btn_list)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (btn_list, btn_disk):
            return
        delete_disk = clicked is btn_disk
        if delete_disk:
            confirm = QMessageBox.question(
                self, "Confirmer la suppression",
                f"Supprimer définitivement {len(targets)} fichier(s) du disque ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        for p in targets:
            self._close_tab_for_path(p)        # ferme l'onglet et libère le fichier
            if delete_disk:
                try:
                    os.remove(p)
                except OSError:
                    pass
            card = self._cards.pop(p, None)
            if card:
                self.flow.removeWidget(card)
                card.deleteLater()
            if p in self._order:
                self._order.remove(p)
            if p in self._selection:
                self._selection.remove(p)
        self._refresh_badges()
        self._update_empty_hint()

    # ----------------------------------------------- Menu contextuel carte --
    def _card_context_menu(self, path, global_pos):
        menu = QMenu(self)
        a_open = menu.addAction(icons.icon("eye"), "Ouvrir")
        a_rename = menu.addAction(icons.icon("edit"), "Renommer")
        a_ocr = menu.addAction(icons.icon("ocr"), "OCR")
        a_merge = menu.addAction(icons.icon("merge"), "Fusionner la sélection")
        a_merge.setEnabled(len(self._selection) >= 2)
        a_merge.setToolTip("Sélectionnez au moins deux documents")
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash"), "Supprimer")
        chosen = menu.exec(global_pos)
        if chosen == a_open:
            self.open_viewer(path)
        elif chosen == a_rename:
            self._rename_file(path)
        elif chosen == a_ocr:
            self._run_ocr_on([path])
        elif chosen == a_merge:
            self.merge_selection()
        elif chosen == a_del:
            self._remove_paths([path])

    def _rename_file(self, path):
        base = os.path.basename(path)
        name, ext = os.path.splitext(base)
        new_name, ok = QInputDialog.getText(
            self, "Renommer", "Nouveau nom du fichier :", text=name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        if not new_name.lower().endswith(".pdf"):
            new_name += ext if ext else ".pdf"
        new_path = os.path.join(os.path.dirname(path), new_name)
        if os.path.abspath(new_path) == os.path.abspath(path):
            return
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Renommer", "Un fichier de ce nom existe déjà.")
            return
        self._close_tab_for_path(path)        # libère le verrou si ouvert
        try:
            os.rename(path, new_path)
        except OSError as e:
            QMessageBox.critical(self, "Renommer", f"Échec du renommage :\n{e}")
            return
        card = self._cards.pop(path, None)
        if card:
            card.path = new_path
            card.name_label.setText(new_name)
            self._cards[new_path] = card
        self._order = [new_path if p == path else p for p in self._order]
        self._selection = [new_path if p == path else p for p in self._selection]
        self._relayout_sorted()
        self._refresh_badges()
        self.statusBar().showMessage(f"Renommé : {new_name}")

    # ------------------------------------------------------- Visionneuse --
    def _open_selected_single(self):
        if len(self._selection) == 1:
            self.open_viewer(self._selection[0])
        else:
            QMessageBox.information(
                self, "Ouvrir",
                "Sélectionnez UN seul document (badge « 1 ») pour l'ouvrir, "
                "ou double-cliquez sur sa vignette."
            )

    def open_viewer(self, path: str):
        from .viewer import ViewerWindow
        # Onglet déjà ouvert pour ce document ?
        existing = self._open_tabs.get(path)
        if existing is not None and self.tabs.indexOf(existing) != -1:
            self.tabs.setCurrentWidget(existing)
            self._reveal_tabs()
            return
        panel = ViewerWindow(path, library=self)
        idx = self.tabs.addTab(panel, panel.tab_title())
        self.tabs.setTabToolTip(idx, path)
        self._open_tabs[path] = panel
        panel.titleChanged.connect(lambda pn=panel: self._update_tab_title(pn))
        self.tabs.setCurrentIndex(idx)
        self._reveal_tabs()

    def _reveal_tabs(self):
        if self.tabs.isHidden():
            self.tabs.show()
            total = self.splitter.width() or self.width()
            self.splitter.setSizes([total // 2, total // 2])

    def _update_tab_title(self, panel):
        idx = self.tabs.indexOf(panel)
        if idx != -1:
            self.tabs.setTabText(idx, panel.tab_title())

    def _close_tab(self, index: int):
        panel = self.tabs.widget(index)
        closed_path = getattr(panel, "path", None)
        # retire l'entrée du dictionnaire
        for k, v in list(self._open_tabs.items()):
            if v is panel:
                del self._open_tabs[k]
        self.tabs.removeTab(index)
        try:
            panel.close()
        except Exception:
            pass
        panel.deleteLater()
        if self.tabs.count() == 0:
            self.tabs.hide()
            # plus aucun onglet : on sélectionne dans la liste le fichier fermé
            if closed_path and closed_path in self._cards:
                self._selection = [closed_path]
                self._refresh_badges()
                self.scroll.ensureWidgetVisible(self._cards[closed_path])

    def _tab_context_menu(self, pos):
        bar = self.tabs.tabBar()
        index = bar.tabAt(pos)
        if index < 0:
            return
        menu = QMenu(self)
        a_close = menu.addAction("Fermer le fichier courant")
        a_all = menu.addAction("Fermer tous les fichiers")
        chosen = menu.exec(bar.mapToGlobal(pos))
        if chosen == a_close:
            self._close_tab(index)
        elif chosen == a_all:
            self._close_all_tabs()

    def _close_all_tabs(self):
        while self.tabs.count():
            self._close_tab(0)

    def _on_tab_changed(self, index: int):
        """Synchronise la sélection visuelle à gauche avec l'onglet affiché."""
        path = None
        if index >= 0:
            panel = self.tabs.widget(index)
            path = getattr(panel, "path", None)
        self._set_active_card(path)

    def _set_active_card(self, path):
        for p, card in self._cards.items():
            card.set_active(p == path)
        if path and path in self._cards:
            self.scroll.ensureWidgetVisible(self._cards[path])

    def _close_tab_for_path(self, path: str):
        """Ferme l'onglet (et libère le fichier) si ce document est ouvert."""
        panel = self._open_tabs.get(path)
        if panel is not None:
            idx = self.tabs.indexOf(panel)
            if idx != -1:
                self._close_tab(idx)

    def notify_new_file(self, path: str):
        """Appelé par la visionneuse après une sauvegarde/split/OCR.
        Ajoute le document à la bibliothèque, ou rafraîchit sa vignette s'il
        y figure déjà (enregistrement sous le même nom)."""
        if path in self._cards:
            self.refresh_file(path)
        else:
            self.add_paths([path])

    def refresh_file(self, path: str):
        """Met à jour la vignette et le nombre de pages d'un document existant."""
        card = self._cards.get(path)
        if card:
            card.reload()
            self.statusBar().showMessage(f"Vignette mise à jour : {os.path.basename(path)}")

    def notify_removed_file(self, path: str):
        """Retire de la bibliothèque un fichier source supprimé."""
        # ferme d'abord l'onglet ouvert sur ce fichier (libère le verrou)
        self._close_tab_for_path(path)
        card = self._cards.pop(path, None)
        if card:
            self.flow.removeWidget(card)
            card.deleteLater()
        if path in self._order:
            self._order.remove(path)
        if path in self._selection:
            self._selection.remove(path)
        self._refresh_badges()
        self._update_empty_hint()

    # --------------------------------------------------------- OCR multi --
    def ocr_selection(self):
        if not self._selection:
            QMessageBox.information(
                self, "OCR",
                "Sélectionnez d'abord un ou plusieurs documents à océriser."
            )
            return
        self._run_ocr_on(list(self._selection))

    def _run_ocr_on(self, paths):
        """Lance l'OCR sur une liste de documents (sélection ou menu contextuel)."""
        if not paths:
            return
        if not ocr.is_available():
            QMessageBox.warning(
                self, "OCR indisponible",
                "Le moteur Tesseract est introuvable. Placez-le dans le dossier "
                "'tesseract/' (voir README) ou installez Tesseract-OCR."
            )
            return
        replace = (
            QMessageBox.question(
                self, "OCR",
                "Remplacer le(s) fichier(s) original(aux) par leur version cherchable (OCR) ?\n\n"
                "Oui : ecrase les fichiers.\n"
                "Non : cree des copies suffixees _ocr.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            ) == QMessageBox.Yes
        )
        self._ocr_progress = QProgressDialog(
            "Préparation de l'OCR…", "Annuler", 0, 100, self
        )
        self._ocr_progress.setWindowTitle("OCR en cours")
        self._ocr_progress.setWindowModality(Qt.WindowModal)
        self._ocr_progress.setMinimumDuration(0)
        self._ocr_progress.setValue(0)

        self._ocr_worker = MultiOcrWorker(list(paths), replace=replace)
        self._ocr_worker.progress.connect(self._on_ocr_progress)
        self._ocr_worker.done.connect(self._on_ocr_done)
        self._ocr_worker.failed.connect(self._on_ocr_failed)
        self._ocr_progress.canceled.connect(self._ocr_worker.requestInterruption)
        self._ocr_worker.start()

    def _on_ocr_progress(self, done_pages, total_pages, message):
        if not hasattr(self, "_ocr_progress") or self._ocr_progress is None:
            return
        self._ocr_progress.setMaximum(total_pages)
        self._ocr_progress.setValue(done_pages)
        self._ocr_progress.setLabelText(message)

    def _on_ocr_done(self, outputs):
        if getattr(self, "_ocr_progress", None):
            self._ocr_progress.close()
        for out in outputs:
            self.notify_new_file(out)
        self.clear_selection()
        QMessageBox.information(
            self, "OCR terminé",
            f"{len(outputs)} document(s) cherchable(s) créé(s) et compressé(s)."
        )

    def _on_ocr_failed(self, msg):
        if getattr(self, "_ocr_progress", None):
            self._ocr_progress.close()
        QMessageBox.critical(self, "Erreur OCR", f"Échec de l'OCR :\n{msg}")

    # --------------------------------------------------------- Recherche --
    def search_selection(self):
        query = self.search_edit.text().strip()
        if not query:
            return
        if not self._selection:
            QMessageBox.information(
                self, "Aucune sélection",
                "Sélectionnez d'abord les documents où chercher."
            )
            return
        results = []
        for p in self._selection:
            r = pdf_ops.search_in_file(p, query)
            r["path"] = p
            results.append(r)
        dlg = SearchResultsDialog(results, query, self.open_viewer, self)
        dlg.exec()

    # ------------------------------------------------------------ Fusion --
    def merge_selection(self):
        if len(self._selection) < 2:
            QMessageBox.information(
                self, "Fusion",
                "Sélectionnez au moins DEUX documents (dans l'ordre voulu) à fusionner."
            )
            return
        sources = list(self._selection)
        suggested = pdf_ops.suggest_name_from(sources[0], suffix="_fusion")
        start_dir = os.path.dirname(sources[0])
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le document fusionné",
            os.path.join(start_dir, suggested), "Fichiers PDF (*.pdf)"
        )
        if not out_path:
            return
        if not out_path.lower().endswith(".pdf"):
            out_path += ".pdf"

        delete_sources = (
            QMessageBox.question(
                self, "Supprimer les sources ?",
                "Supprimer les documents source d'origine après la fusion ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) == QMessageBox.Yes
        )

        try:
            pdf_ops.merge_files(sources, out_path)
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Échec de la fusion :\n{e}")
            return

        if delete_sources:
            for p in sources:
                if os.path.abspath(p) == os.path.abspath(out_path):
                    continue
                # ferme l'onglet ouvert sur ce fichier (sinon suppression bloquée)
                self._close_tab_for_path(p)
                try:
                    os.remove(p)
                except OSError:
                    pass
                self.notify_removed_file(p)

        self.clear_selection()
        self.notify_new_file(out_path)
        QMessageBox.information(
            self, "Fusion terminée",
            f"Document fusionné et compressé :\n{out_path}"
        )
