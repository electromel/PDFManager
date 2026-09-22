"""
printing.py
===========
Impression des PDF.

Qt ne sait pas imprimer un PDF directement : chaque page est rendue en image
par PyMuPDF, puis peinte sur la feuille. Ce module encapsule ce va-et-vient et
expose deux entrées : la boîte d'impression système et l'aperçu avant
impression.

Une « page à imprimer » est un couple `(document, index)`. Un même travail
d'impression peut donc enchaîner les pages de plusieurs documents, ce qui sert
à imprimer une sélection entière depuis la bibliothèque.

Contrairement à pdf_ops.py et optimize.py, ce module dépend de Qt : imprimer
est une opération d'interface, pas une manipulation de PDF.
"""

from __future__ import annotations

import math
import os
from typing import Callable, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage, QPainter, QTransform
from PySide6.QtWidgets import QApplication, QProgressDialog
from PySide6.QtPrintSupport import (
    QAbstractPrintDialog, QPrintDialog, QPrintPreviewDialog, QPrinter,
    QPrinterInfo,
)

#: Résolution de rendu maximale. Une imprimante annonce souvent 600 ou
#: 1200 ppp ; rendre une A4 à 1200 ppp demanderait 420 Mo pour une seule
#: page, sans gain visible. 400 ppp reste net sur du texte comme sur une
#: photo, pour 46 Mo par page A4.
MAX_DPI = 400

#: Plafond absolu, qui protège des très grands formats (plans, affiches) :
#: une A0 à 400 ppp ferait 250 millions de pixels. Au-delà, la résolution
#: est réduite jusqu'à retomber sous ce seuil.
MAX_PIXELS = 40_000_000

#: Un couple (document, index de page 0-based).
Page = Tuple["fitz.Document", int]


def printers_available() -> bool:
    """Au moins une imprimante est-elle déclarée sur le poste ?"""
    return bool(QPrinterInfo.availablePrinters())


def pages_of(doc: "fitz.Document", indices: Optional[Sequence[int]] = None
             ) -> List[Page]:
    """Couples (document, index) pour les pages demandées, tout le document
    si `indices` est vide."""
    if not indices:
        indices = range(doc.page_count)
    return [(doc, index) for index in indices]


# --------------------------------------------------------------------------- #
#  Rendu d'une page sur la feuille
# --------------------------------------------------------------------------- #
def _dpi_for(rect, dpi: int) -> int:
    """Résolution retenue pour une page, ramenée sous le plafond de pixels."""
    width = max(1.0, rect.width) / 72.0
    height = max(1.0, rect.height) / 72.0
    pixels = width * dpi * height * dpi
    if pixels > MAX_PIXELS:
        dpi = int(dpi * math.sqrt(MAX_PIXELS / pixels))
    return max(96, dpi)


def _render(doc: "fitz.Document", index: int, dpi: int) -> Optional[QImage]:
    """Rend une page en QImage, à la résolution demandée ou un peu moins."""
    try:
        page = doc[index]
        zoom = _dpi_for(page.rect, dpi) / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    except Exception:
        return None
    image = QImage(pix.samples, pix.width, pix.height, pix.stride,
                   QImage.Format_RGB888)
    # QImage pointe sur la mémoire du pixmap, qui disparaît avec lui :
    # la copie est indispensable, pas une précaution.
    return image.copy()


def _fit(image: QImage, target: QRect, rotate: bool) -> Tuple[QImage, QRect]:
    """Ajuste l'image à la feuille : rotation éventuelle, puis centrage."""
    if rotate and (image.width() > image.height()) != (target.width() > target.height()):
        # Page paysage sur feuille portrait (ou l'inverse) : la tourner d'un
        # quart de tour la fait tenir en pleine page au lieu d'une bande.
        image = image.transformed(QTransform().rotate(90))
    size = image.size().scaled(target.size(), Qt.KeepAspectRatio)
    rect = QRect(QPoint(0, 0), size)
    rect.moveCenter(target.center())
    return image, rect


def _paint(printer: QPrinter, pages: Sequence[Page], rotate: bool = True,
           progress: Optional[Callable[[int, int], bool]] = None) -> int:
    """Peint les pages sur l'imprimante. Renvoie le nombre de pages imprimées.

    `progress(faite, total)` peut renvoyer False pour interrompre le travail.
    """
    if not pages:
        return 0

    painter = QPainter()
    if not painter.begin(printer):
        return 0

    dpi = min(printer.resolution() or MAX_DPI, MAX_DPI)
    target = printer.pageLayout().paintRectPixels(printer.resolution())
    grayscale = printer.colorMode() == QPrinter.GrayScale
    done = 0
    try:
        for position, (doc, index) in enumerate(pages):
            if progress and not progress(position, len(pages)):
                break
            if position and not printer.newPage():
                break
            image = _render(doc, index, dpi)
            if image is None:
                continue          # page illisible : on saute, sans tout perdre
            if grayscale:
                image = image.convertToFormat(QImage.Format_Grayscale8)
            image, rect = _fit(image, target, rotate)
            painter.drawImage(rect, image)
            done += 1
    finally:
        painter.end()
    return done


# --------------------------------------------------------------------------- #
#  Entrées publiques
# --------------------------------------------------------------------------- #
def _configure(printer: QPrinter, pages: Sequence[Page], title: str) -> None:
    printer.setDocName(title or "Document")
    printer.setFullPage(False)
    if pages:
        printer.setFromTo(1, len(pages))


def _chosen_pages(printer: QPrinter, pages: Sequence[Page],
                  selection: Optional[Sequence[Page]]) -> List[Page]:
    """Applique l'étendue retenue dans la boîte système."""
    mode = printer.printRange()
    if mode == QPrinter.Selection and selection:
        return list(selection)
    if mode == QPrinter.PageRange:
        first = max(1, printer.fromPage()) - 1
        last = min(len(pages), printer.toPage() or len(pages))
        return list(pages[first:last])
    return list(pages)


def _paint_watched(parent, printer: QPrinter, pages: Sequence[Page],
                   title: str) -> int:
    """Peint en montrant une progression annulable.

    La peinture occupe le fil de l'interface — QPainter sur une QPrinter n'est
    utilisable que là — d'où le pompage explicite des évènements, sans lequel
    la fenêtre resterait figée et le bouton Annuler inerte.
    """
    dialog = QProgressDialog("Préparation…", "Annuler", 0, len(pages), parent)
    dialog.setWindowTitle(f"Impression — {title}" if title else "Impression")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(300)

    def report(done: int, total: int) -> bool:
        dialog.setMaximum(total)
        dialog.setValue(done)
        dialog.setLabelText(f"Page {done + 1} sur {total}…")
        QApplication.processEvents()
        return not dialog.wasCanceled()

    try:
        return _paint(printer, pages, progress=report)
    finally:
        dialog.close()


def print_pages(parent, pages: Sequence[Page], title: str = "",
                selection: Optional[Sequence[Page]] = None) -> int:
    """Ouvre la boîte d'impression système et imprime. 0 si l'on a annulé."""
    if not pages:
        return 0

    printer = QPrinter(QPrinter.HighResolution)
    _configure(printer, pages, title)

    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle("Imprimer")
    options = (QAbstractPrintDialog.PrintToFile
               | QAbstractPrintDialog.PrintPageRange
               | QAbstractPrintDialog.PrintCollateCopies)
    if selection:
        options |= QAbstractPrintDialog.PrintSelection
    dialog.setOptions(options)
    if dialog.exec() != QPrintDialog.Accepted:
        return 0

    chosen = _chosen_pages(printer, pages, selection)
    if len(chosen) > 1:
        return _paint_watched(parent, printer, chosen, title)
    return _paint(printer, chosen)


def preview_pages(parent, pages: Sequence[Page], title: str = "") -> None:
    """Aperçu avant impression, avec son propre bouton d'impression."""
    if not pages:
        return
    printer = QPrinter(QPrinter.HighResolution)
    _configure(printer, pages, title)

    dialog = QPrintPreviewDialog(printer, parent)
    dialog.setWindowTitle(f"Aperçu avant impression — {title}" if title
                          else "Aperçu avant impression")
    dialog.resize(900, 780)
    # L'aperçu redemande la peinture à chaque changement de réglage.
    dialog.paintRequested.connect(lambda target: _paint(target, pages))
    dialog.exec()


def print_files(parent, paths: Sequence[str], title: str = ""
                ) -> Tuple[int, List[str]]:
    """Imprime des fichiers en un seul travail.

    Renvoie (pages imprimées, fichiers illisibles). Les documents sont
    ouverts le temps de l'impression, puis refermés.
    """
    docs = []
    pages: List[Page] = []
    failed: List[str] = []
    try:
        for path in paths:
            try:
                doc = fitz.open(path)
            except Exception:
                failed.append(os.path.basename(path))
                continue
            if doc.needs_pass and not doc.authenticate(""):
                failed.append(os.path.basename(path))
                doc.close()
                continue
            docs.append(doc)
            pages += pages_of(doc)
        printed = print_pages(parent, pages, title=title)
    finally:
        for doc in docs:
            try:
                doc.close()
            except Exception:
                pass
    return printed, failed
