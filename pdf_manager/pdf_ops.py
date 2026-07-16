"""
pdf_ops.py
==========
Toutes les opérations bas niveau sur les PDF, basées sur PyMuPDF (fitz).

Aucune dépendance à un programme externe : PyMuPDF est une bibliothèque Python
autonome qui sait rendre, fusionner, découper et compresser les PDF.
"""

from __future__ import annotations

import os
from typing import List, Sequence, Optional

import fitz  # PyMuPDF


# --------------------------------------------------------------------------- #
#  Rendu / vignettes
# --------------------------------------------------------------------------- #
def render_page_to_png(
    doc: "fitz.Document",
    page_index: int,
    max_size: int = 220,
) -> bytes:
    """Rend une page en PNG (octets), redimensionnée pour tenir dans max_size px.

    Retourne les octets PNG, directement utilisables par QPixmap.loadFromData().
    """
    page = doc[page_index]
    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        zoom = 1.0
    else:
        zoom = max_size / max(rect.width, rect.height)
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return pix.tobytes("png")


def render_first_page_png(path: str, max_size: int = 220) -> Optional[bytes]:
    """Vignette de la 1ère page d'un fichier PDF. None si illisible / vide."""
    try:
        with fitz.open(path) as doc:
            if doc.page_count == 0:
                return None
            return render_page_to_png(doc, 0, max_size=max_size)
    except Exception:
        return None


def page_count(path: str) -> int:
    try:
        with fitz.open(path) as doc:
            return doc.page_count
    except Exception:
        return 0


# --------------------------------------------------------------------------- #
#  Compression
# --------------------------------------------------------------------------- #
def save_compressed(doc: "fitz.Document", out_path: str) -> None:
    """Sauvegarde un document en appliquant une compression maximale.

    - garbage=4 : suppression des objets inutilisés + déduplication
    - deflate   : recompression des flux
    - clean     : nettoyage de la structure
    """
    doc.save(
        out_path,
        garbage=4,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        clean=True,
        pretty=False,
    )


def compress_file(in_path: str, out_path: str) -> None:
    """Compresse un PDF existant vers out_path."""
    with fitz.open(in_path) as doc:
        save_compressed(doc, out_path)


# --------------------------------------------------------------------------- #
#  Fusion (merge)
# --------------------------------------------------------------------------- #
def merge_files(paths: Sequence[str], out_path: str) -> None:
    """Fusionne plusieurs PDF dans l'ordre donné, puis compresse le résultat."""
    merged = fitz.open()
    try:
        for p in paths:
            with fitz.open(p) as src:
                merged.insert_pdf(src)
        save_compressed(merged, out_path)
    finally:
        merged.close()


# --------------------------------------------------------------------------- #
#  Découpe (split)
# --------------------------------------------------------------------------- #
def split_after_page(in_path: str, page_index: int) -> tuple[str, str]:
    """Découpe un PDF en deux APRÈS la page `page_index` (index 0-based).

    Renvoie (chemin_part1, chemin_part2). Les deux parties sont compressées.
    Exemple : split_after_page(doc, 2) -> part1 = pages 1-3, part2 = pages 4..N
    """
    base, ext = os.path.splitext(in_path)
    out1 = f"{base}_partie1{ext}"
    out2 = f"{base}_partie2{ext}"
    with fitz.open(in_path) as doc:
        n = doc.page_count
        d1 = fitz.open()
        d2 = fitz.open()
        d1.insert_pdf(doc, from_page=0, to_page=page_index)
        if page_index + 1 <= n - 1:
            d2.insert_pdf(doc, from_page=page_index + 1, to_page=n - 1)
        save_compressed(d1, out1)
        if d2.page_count:
            save_compressed(d2, out2)
        d1.close()
        d2.close()
    return out1, out2


def build_from_page_order(
    source_path: str,
    page_indices: Sequence[int],
    out_path: str,
) -> None:
    """Construit un nouveau PDF à partir d'un sous-ensemble/réordonnancement
    de pages d'un document source, puis compresse.

    page_indices : liste d'indices 0-based dans l'ordre voulu.
    """
    with fitz.open(source_path) as src:
        out = fitz.open()
        try:
            for idx in page_indices:
                out.insert_pdf(src, from_page=idx, to_page=idx)
            save_compressed(out, out_path)
        finally:
            out.close()


def save_reordered_document(doc: "fitz.Document", out_path: str) -> None:
    """Sauvegarde (compressée) un document fitz déjà manipulé en mémoire."""
    save_compressed(doc, out_path)


# --------------------------------------------------------------------------- #
#  Aide nommage
# --------------------------------------------------------------------------- #
def suggest_name_from(path: str, suffix: str = "") -> str:
    """Propose un nom de fichier de sortie à partir du 1er document source."""
    base = os.path.splitext(os.path.basename(path))[0]
    if suffix:
        return f"{base}{suffix}.pdf"
    return f"{base}.pdf"


# --------------------------------------------------------------------------- #
#  Rotation / suppression / sauvegarde depuis un document en mémoire
# --------------------------------------------------------------------------- #
def rotate_doc_pages(doc: "fitz.Document", indices, angle: int) -> None:
    """Pivote les pages indiquées (indices 0-based) de `angle` degrés (cumulatif).

    angle : 90, 180 ou 270 (sens horaire). Modifie le document en mémoire.
    """
    for i in indices:
        page = doc[i]
        page.set_rotation((page.rotation + angle) % 360)


def delete_doc_pages(doc: "fitz.Document", indices) -> None:
    """Supprime les pages indiquées (indices 0-based) du document en mémoire."""
    for i in sorted(set(indices), reverse=True):
        if 0 <= i < doc.page_count:
            doc.delete_page(i)


def save_doc_pages(doc: "fitz.Document", page_indices, out_path: str) -> None:
    """Construit un PDF à partir des pages de `doc` (ordre/sous-ensemble donné),
    en conservant rotations et contenu, puis compresse."""
    out = fitz.open()
    try:
        for idx in page_indices:
            out.insert_pdf(doc, from_page=idx, to_page=idx)
        save_compressed(out, out_path)
    finally:
        out.close()


# --------------------------------------------------------------------------- #
#  Surlignage (annotations)
# --------------------------------------------------------------------------- #
HIGHLIGHT_COLORS = {
    "Jaune": (1.0, 0.85, 0.0),
    "Vert":  (0.35, 0.85, 0.35),
    "Bleu":  (0.40, 0.70, 1.0),
    "Rose":  (1.0, 0.45, 0.70),
}


def highlight_zone(doc: "fitz.Document", page_index: int, rect,
                   color=(1.0, 0.85, 0.0)) -> str:
    """Surligne la zone `rect` d'une page (coordonnées de la page affichée).

    S'il y a du texte dans la zone, chaque mot est surligné comme dans Acrobat ;
    sinon (image, schéma…) la zone reçoit un aplat de couleur semi-transparent.
    Renvoie "texte" ou "zone".
    """
    page = doc[page_index]
    # Le rendu est fait sur la page pivotée ; le texte et les annotations
    # utilisent les coordonnées de la page NON pivotée.
    sel = fitz.Rect(rect) * page.derotation_matrix
    sel.normalize()
    quads = []
    for w in page.get_text("words"):
        r = fitz.Rect(w[:4])
        inter = r & sel
        if inter.is_empty:
            continue
        # mot retenu si la sélection couvre au moins la moitié de sa hauteur
        if inter.height >= r.height * 0.5 and inter.width >= min(4.0, r.width):
            quads.append(r.quad)
    if quads:
        annot = page.add_highlight_annot(quads)
        annot.set_colors(stroke=color)
        annot.update()
        return "texte"
    annot = page.add_rect_annot(sel)
    annot.set_colors(stroke=color, fill=color)
    annot.set_border(width=0)
    annot.set_opacity(0.35)
    annot.update()
    return "zone"


def remove_highlights(doc: "fitz.Document", indices) -> int:
    """Supprime les surlignages (texte et zone) des pages indiquées.

    Renvoie le nombre d'annotations supprimées.
    """
    removed = 0
    types = (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_SQUARE)
    for i in indices:
        page = doc[i]
        while True:
            annot = next(page.annots(types=types), None)
            if annot is None:
                break
            page.delete_annot(annot)
            removed += 1
    return removed


# --------------------------------------------------------------------------- #
#  Copier / coller de pages (presse-papiers interne)
# --------------------------------------------------------------------------- #
def copy_pages_to_bytes(doc: "fitz.Document", indices) -> bytes:
    """Sérialise les pages indiquées (dans l'ordre donné) en un PDF (octets).

    Le résultat est autonome : il reste valable même si le document source
    est modifié ou fermé ensuite.
    """
    out = fitz.open()
    try:
        for idx in indices:
            out.insert_pdf(doc, from_page=idx, to_page=idx)
        return out.tobytes(garbage=2, deflate=True)
    finally:
        out.close()


def paste_pages_from_bytes(doc: "fitz.Document", data: bytes, at: int) -> int:
    """Insère les pages du presse-papiers (octets PDF) à la position `at`
    (0-based ; `at = page_count` pour coller à la fin).

    Renvoie le nombre de pages insérées.
    """
    src = fitz.open("pdf", data)
    try:
        n = src.page_count
        doc.insert_pdf(src, start_at=at)
        return n
    finally:
        src.close()


# --------------------------------------------------------------------------- #
#  Recherche plein texte
# --------------------------------------------------------------------------- #
def search_in_file(path: str, query: str):
    """Recherche `query` (insensible à la casse) dans le texte d'un PDF.

    Renvoie un dict : {pages: [n° de pages 1-based], has_text: bool}.
    has_text = False indique un PDF probablement scanné sans OCR.
    """
    q = (query or "").lower().strip()
    pages, has_text = [], False
    if not q:
        return {"pages": pages, "has_text": has_text}
    try:
        with fitz.open(path) as doc:
            for i in range(doc.page_count):
                t = doc[i].get_text()
                if t and t.strip():
                    has_text = True
                if t and q in t.lower():
                    pages.append(i + 1)
    except Exception:
        pass
    return {"pages": pages, "has_text": has_text}
