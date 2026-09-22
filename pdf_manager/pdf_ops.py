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
#  Annotations : surlignage, dessin, texte
# --------------------------------------------------------------------------- #
# Toutes les annotations posées par l'application sont de vraies annotations
# PDF (conservées à l'enregistrement, relues par n'importe quel lecteur) et
# portent un marqueur dans leur champ /Subj. Ce marqueur sert à les retrouver
# pour les ré-éditer (texte), les supprimer une par une, ou n'effacer qu'une
# famille (surlignages / dessins / textes).
#
# Convention de coordonnées : toutes les fonctions de cette section reçoivent
# et renvoient des coordonnées de la page **affichée** (donc telle qu'elle est
# rendue à l'écran, rotation comprise). La conversion vers les coordonnées
# internes du PDF est faite ici, une fois pour toutes.
SUBJ_HIGHLIGHT = "PDFM:highlight"
SUBJ_DRAW = "PDFM:draw"
SUBJ_TEXT = "PDFM:text"

HIGHLIGHT_COLORS = {
    "Jaune": (1.0, 0.85, 0.0),
    "Vert":  (0.35, 0.85, 0.35),
    "Bleu":  (0.40, 0.70, 1.0),
    "Rose":  (1.0, 0.45, 0.70),
}

# Épaisseur (en points PDF) du trait de marqueur.
HIGHLIGHT_WIDTHS = {"Fin": 8.0, "Moyen": 14.0, "Épais": 22.0}

DRAW_COLORS = {
    "Rouge":  (0.85, 0.12, 0.12),
    "Noir":   (0.0, 0.0, 0.0),
    "Bleu":   (0.10, 0.30, 0.75),
    "Vert":   (0.10, 0.55, 0.20),
    "Orange": (0.95, 0.55, 0.05),
    "Blanc":  (1.0, 1.0, 1.0),
}

DRAW_WIDTHS = {"Fin": 1.0, "Moyen": 2.0, "Épais": 4.0, "Très épais": 8.0}

# Polices de base du PDF (aucun fichier à embarquer, rendu identique partout).
TEXT_FONTS = {
    "Helvetica":          "helv",
    "Helvetica gras":     "hebo",
    "Helvetica italique": "heit",
    "Times":              "tiro",
    "Times gras":         "tibo",
    "Times italique":     "tiit",
    "Courier":            "cour",
    "Courier gras":       "cobo",
}

TEXT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 60, 72]


# ------------------------------------------------------- outils internes --
def _page_rect(page, rect) -> "fitz.Rect":
    """Rectangle affiché -> rectangle en coordonnées internes de la page."""
    r = fitz.Rect(rect) * page.derotation_matrix
    r.normalize()
    return r


def _page_point(page, point) -> "fitz.Point":
    """Point affiché -> point en coordonnées internes de la page."""
    return fitz.Point(point) * page.derotation_matrix


def _view_rect(page, rect) -> "fitz.Rect":
    """Rectangle interne -> rectangle affiché (opération inverse)."""
    r = fitz.Rect(rect) * page.rotation_matrix
    r.normalize()
    return r


def _mark(annot, subject: str) -> None:
    try:
        annot.set_info(subject=subject)
    except Exception:
        pass


def _subject(annot) -> str:
    try:
        return annot.info.get("subject") or ""
    except Exception:
        return ""


def _family(annot) -> Optional[str]:
    """Famille d'une annotation posée par l'application, sinon None."""
    subj = _subject(annot)
    if subj.startswith(SUBJ_TEXT):
        return "text"
    if subj == SUBJ_DRAW:
        return "draw"
    if subj == SUBJ_HIGHLIGHT:
        return "highlight"
    # Annotations des versions antérieures : seuls les surlignages existaient.
    if not subj and annot.type[0] in (fitz.PDF_ANNOT_HIGHLIGHT,
                                      fitz.PDF_ANNOT_SQUARE):
        return "highlight"
    return None


def _text_subject(font: str, size: float, color, fill) -> str:
    """Marqueur d'un texte : mémorise sa mise en forme pour la ré-édition."""
    def enc(c):
        return "-" if c is None else ",".join(f"{v:.3f}" for v in c)
    return f"{SUBJ_TEXT}|{font}|{size:g}|{enc(color)}|{enc(fill)}"


def _parse_text_subject(subj: str) -> dict:
    """Relit la mise en forme mémorisée (valeurs par défaut si illisible)."""
    def dec(raw):
        if not raw or raw == "-":
            return None
        try:
            vals = tuple(float(v) for v in raw.split(","))
        except ValueError:
            return None
        return vals if len(vals) == 3 else None

    style = {"font": "helv", "size": 12.0, "color": (0.0, 0.0, 0.0), "fill": None}
    parts = (subj or "").split("|")
    if len(parts) >= 3:
        if parts[1] in TEXT_FONTS.values():
            style["font"] = parts[1]
        try:
            style["size"] = float(parts[2])
        except ValueError:
            pass
    if len(parts) >= 4:
        style["color"] = dec(parts[3]) or (0.0, 0.0, 0.0)
    if len(parts) >= 5:
        style["fill"] = dec(parts[4])
    return style


def _annot_info(page, annot) -> Optional[dict]:
    """Description d'une annotation de l'application (coordonnées affichées)."""
    family = _family(annot)
    if family is None:
        return None
    info = {
        "xref": annot.xref,
        "family": family,
        "rect": _view_rect(page, annot.rect),
        "text": "",
        "font": "helv",
        "size": 12.0,
        "color": (0.0, 0.0, 0.0),
        "fill": None,
    }
    if family == "text":
        info["text"] = annot.info.get("content") or ""
        info.update(_parse_text_subject(_subject(annot)))
    return info


def _clean_points(points) -> List[tuple]:
    """Points d'un tracé, débarrassés des points confondus (rendu identique,
    fichier plus léger). Retourne des couples (x, y), seul format accepté par
    les annotations d'encre de PyMuPDF."""
    out: List[tuple] = []
    for p in points:
        pt = fitz.Point(p)
        if not out or abs(pt.x - out[-1][0]) > 0.4 or abs(pt.y - out[-1][1]) > 0.4:
            out.append((pt.x, pt.y))
    if not out:
        first = fitz.Point(points[0])
        out.append((first.x, first.y))
    return out


# ------------------------------------------------------------ surlignage --
def highlight_zone(doc: "fitz.Document", page_index: int, rect,
                   color=(1.0, 0.85, 0.0)) -> str:
    """Surligne la zone `rect` d'une page (coordonnées de la page affichée).

    S'il y a du texte dans la zone, chaque mot est surligné comme dans Acrobat ;
    sinon (image, page scannée…) la zone reçoit un aplat de couleur en fondu
    « Multiply », qui teinte le fond sans masquer ce qu'il y a dessous.
    Renvoie "texte" ou "zone".
    """
    page = doc[page_index]
    # Le rendu est fait sur la page pivotée ; le texte et les annotations
    # utilisent les coordonnées de la page NON pivotée.
    sel = _page_rect(page, rect)
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
        _mark(annot, SUBJ_HIGHLIGHT)
        annot.update()
        return "texte"
    annot = page.add_rect_annot(sel)
    annot.set_colors(stroke=color, fill=color)
    annot.set_border(width=0)
    _mark(annot, SUBJ_HIGHLIGHT)
    annot.update(blend_mode=fitz.PDF_BM_Multiply, opacity=1.0)
    return "zone"


def highlight_stroke(doc: "fitz.Document", page_index: int, points,
                     color=(1.0, 0.85, 0.0), width: float = 14.0) -> None:
    """Trait de marqueur (surligneur à main levée), comme dans Acrobat.

    Contrairement au surlignage de texte, il ne dépend pas d'une couche de
    texte : il fonctionne donc aussi sur un PDF **image** (page scannée).
    Le fondu « Multiply » teinte le fond en laissant voir ce qu'il y a dessous.
    """
    page = doc[page_index]
    pts = _clean_points([_page_point(page, p) for p in points])
    if len(pts) < 2:
        pts.append((pts[0][0] + 0.5, pts[0][1]))
    annot = page.add_ink_annot([pts])
    annot.set_colors(stroke=color)
    annot.set_border(width=width)
    _mark(annot, SUBJ_HIGHLIGHT)
    annot.update(blend_mode=fitz.PDF_BM_Multiply, opacity=1.0)


# --------------------------------------------------------------- dessin --
def add_drawing(doc: "fitz.Document", page_index: int, kind: str, points,
                color=(0.85, 0.12, 0.12), width: float = 2.0, fill=None) -> None:
    """Ajoute un tracé sur une page (coordonnées de la page affichée).

    kind : "ink" (main levée), "line" (ligne droite), "arrow" (flèche),
    "rect" (rectangle) ou "ellipse". `fill` remplit les formes fermées.
    """
    page = doc[page_index]
    pts = [_page_point(page, p) for p in points]
    if not pts:
        return
    if kind == "ink":
        annot = page.add_ink_annot([_clean_points(pts)])
    elif kind in ("line", "arrow"):
        annot = page.add_line_annot(pts[0], pts[-1])
        if kind == "arrow":
            annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE,
                                fitz.PDF_ANNOT_LE_CLOSED_ARROW)
    else:
        rect = fitz.Rect(pts[0], pts[-1])
        rect.normalize()
        if rect.width < 1 or rect.height < 1:
            return
        annot = (page.add_circle_annot(rect) if kind == "ellipse"
                 else page.add_rect_annot(rect))
    if kind in ("rect", "ellipse", "arrow"):
        annot.set_colors(stroke=color, fill=fill)
    else:
        annot.set_colors(stroke=color)
    annot.set_border(width=max(0.5, width))
    _mark(annot, SUBJ_DRAW)
    annot.update()


# ---------------------------------------------------------------- texte --
def text_box_size(text: str, font: str = "helv", size: float = 12.0):
    """Dimensions (largeur, hauteur) du cadre nécessaire à un texte."""
    lines = (text or "").splitlines() or [""]
    width = max(fitz.get_text_length(line or " ", fontname=font, fontsize=size)
                for line in lines)
    return width + size * 1.2, len(lines) * size * 1.3 + size * 0.7


def _text_rect(page, origin, text: str, font: str, size: float) -> "fitz.Rect":
    """Cadre d'un texte posé à `origin` (coin haut-gauche, coords affichées),
    ramené à l'intérieur de la page."""
    w, h = text_box_size(text, font, size)
    view = fitz.Rect(page.rect)      # page.rect est déjà le cadre affiché
    x = min(max(origin[0], view.x0), max(view.x0, view.x1 - w))
    y = min(max(origin[1], view.y0), max(view.y0, view.y1 - h))
    return fitz.Rect(x, y, x + w, y + h)


def add_text_box(doc: "fitz.Document", page_index: int, origin, text: str,
                 font: str = "helv", size: float = 12.0,
                 color=(0.0, 0.0, 0.0), fill=None) -> Optional[dict]:
    """Ajoute un texte modifiable sur une page (annotation FreeText).

    `origin` est le coin haut-gauche voulu, en coordonnées de la page affichée.
    Le cadre est dimensionné automatiquement d'après le texte et la police.
    Renvoie la description de l'annotation créée (voir `annot_at`).
    """
    text = (text or "").strip("\n")
    if not text.strip():
        return None
    page = doc[page_index]
    view = _text_rect(page, origin, text, font, size)
    annot = page.add_freetext_annot(
        _page_rect(page, view), text,
        fontsize=size, fontname=font, text_color=color, fill_color=fill,
        border_width=0, rotate=page.rotation,
    )
    _mark(annot, _text_subject(font, size, color, fill))
    annot.update()
    return _annot_info(page, annot)


def update_text_box(doc: "fitz.Document", page_index: int, xref: int, text: str,
                    font: str = "helv", size: float = 12.0,
                    color=(0.0, 0.0, 0.0), fill=None,
                    origin=None) -> Optional[dict]:
    """Remplace un texte existant par sa version modifiée.

    L'annotation est recréée : c'est le seul moyen sûr de refléter tous les
    changements possibles (police, corps, couleur, nombre de lignes). Le coin
    haut-gauche est conservé, sauf si `origin` en impose un autre (déplacement).
    """
    page = doc[page_index]
    old = None
    # Une annotation ne doit pas être conservée au-delà de l'itération qui la
    # produit : on lit son cadre et on la supprime dans la même boucle.
    for annot in page.annots():
        if annot.xref == xref:
            old = _view_rect(page, annot.rect)
            page.delete_annot(annot)
            break
    if old is None:
        return None
    if origin is None:
        origin = (old.x0, old.y0)
    return add_text_box(doc, page_index, origin, text, font, size, color, fill)


# ---------------------------------------------- recherche / suppression --
def annot_at(doc: "fitz.Document", page_index: int, point,
             families=None) -> Optional[dict]:
    """Annotation de l'application sous le point donné (coords affichées).

    Renvoie la plus « au-dessus » (la dernière posée), ou None.
    `families` restreint la recherche ("text", "draw", "highlight").
    """
    page = doc[page_index]
    pt = _page_point(page, point)
    found = None
    for annot in page.annots():
        info = _annot_info(page, annot)
        if info is None:
            continue
        if families and info["family"] not in families:
            continue
        if pt in annot.rect:
            found = info
    return found


def delete_annot(doc: "fitz.Document", page_index: int, xref: int) -> bool:
    """Supprime une annotation désignée par son xref."""
    page = doc[page_index]
    for annot in page.annots():
        if annot.xref == xref:
            page.delete_annot(annot)
            return True
    return False


def remove_annots(doc: "fitz.Document", indices, families) -> int:
    """Supprime, sur les pages indiquées, les annotations des familles données.

    Renvoie le nombre d'annotations supprimées.
    """
    wanted = set(families)
    removed = 0
    for i in indices:
        page = doc[i]
        # `delete_annot` renvoie l'annotation suivante : c'est la façon sûre de
        # parcourir la liste tout en la modifiant.
        annot = page.first_annot
        while annot:
            if _family(annot) in wanted:
                annot = page.delete_annot(annot)
                removed += 1
            else:
                annot = annot.next
    return removed


def remove_highlights(doc: "fitz.Document", indices) -> int:
    """Supprime les surlignages (texte, zone et traits de marqueur)."""
    return remove_annots(doc, indices, ("highlight",))


def remove_drawings(doc: "fitz.Document", indices) -> int:
    """Supprime les tracés (main levée, lignes, formes)."""
    return remove_annots(doc, indices, ("draw",))


def remove_texts(doc: "fitz.Document", indices) -> int:
    """Supprime les textes ajoutés."""
    return remove_annots(doc, indices, ("text",))


# --------------------------------------------------------------------------- #
#  Reprise d'une annotation : déplacement, changement d'attributs
# --------------------------------------------------------------------------- #
# Une annotation posée reste manipulable : on peut la reprendre pour la
# déplacer ou changer sa couleur, son épaisseur et son remplissage.
#
# PyMuPDF ne sait pas déplacer un tracé (encre, ligne, surlignage) par
# `set_rect` : ces annotations n'ont pas de rectangle modifiable, seulement des
# sommets. Le déplacement se fait donc en relevant tout ce qui définit
# l'annotation, en la supprimant, puis en la recréant décalée — d'où le couple
# `_capture` / `_recreate`, également utilisé pour les rectangles et les textes
# afin de n'avoir qu'un seul chemin de code.
def _capture(annot) -> dict:
    """Relève tout ce qui est nécessaire pour recréer une annotation."""
    colors = annot.colors or {}
    stroke = tuple(colors.get("stroke") or ()) or None
    fill = tuple(colors.get("fill") or ()) or None
    opacity = annot.opacity
    return {
        "atype": annot.type[0],
        "subject": _subject(annot),
        "content": annot.info.get("content") or "",
        "rect": fitz.Rect(annot.rect),
        "vertices": annot.vertices,
        "stroke": stroke,
        "fill": fill,
        "width": (annot.border or {}).get("width") or 0.0,
        "opacity": 1.0 if opacity is None or opacity < 0 else opacity,
        "blend": annot.blendmode,
        "line_ends": getattr(annot, "line_ends", None),
    }


def _round_color(color) -> Optional[tuple]:
    """Couleur arrondie : les couleurs relues d'un PDF sont stockées en
    simple précision (0.85 revient en 0.8500000238…), ce qui les empêcherait
    de correspondre aux couleurs proposées dans les menus."""
    if not color:
        return None
    return tuple(round(float(v), 3) for v in color)


def _shift(point, delta) -> tuple:
    return (point[0] + delta.x, point[1] + delta.y)


def _recreate(page, cap: dict, delta=None, color=None, width=None, fill=None):
    """Recrée une annotation relevée par `_capture`, éventuellement décalée
    de `delta` et avec de nouveaux attributs."""
    d = fitz.Point(delta) if delta is not None else fitz.Point(0, 0)
    atype = cap["atype"]
    verts = cap["vertices"] or []
    rect = fitz.Rect(cap["rect"]) + (d.x, d.y, d.x, d.y)
    if atype == fitz.PDF_ANNOT_INK:
        strokes = [[_shift(p, d) for p in stroke] for stroke in verts]
        if not strokes or not strokes[0]:
            return None
        annot = page.add_ink_annot(strokes)
    elif atype == fitz.PDF_ANNOT_LINE:
        if len(verts) < 2:
            return None
        annot = page.add_line_annot(_shift(verts[0], d), _shift(verts[-1], d))
        if cap["line_ends"]:
            annot.set_line_ends(*cap["line_ends"])
    elif atype == fitz.PDF_ANNOT_HIGHLIGHT:
        quads = [fitz.Quad(*(fitz.Point(_shift(p, d)) for p in verts[i:i + 4]))
                 for i in range(0, len(verts) - 3, 4)]
        if not quads:
            return None
        annot = page.add_highlight_annot(quads)
    elif atype == fitz.PDF_ANNOT_CIRCLE:
        annot = page.add_circle_annot(rect)
    elif atype == fitz.PDF_ANNOT_SQUARE:
        annot = page.add_rect_annot(rect)
    elif atype == fitz.PDF_ANNOT_FREE_TEXT:
        style = _parse_text_subject(cap["subject"])
        annot = page.add_freetext_annot(
            rect, cap["content"], fontsize=style["size"], fontname=style["font"],
            text_color=style["color"], fill_color=style["fill"],
            border_width=0, rotate=page.rotation)
        _mark(annot, cap["subject"])
        annot.update()
        return annot
    else:
        return None
    annot.set_colors(stroke=color or cap["stroke"],
                     fill=fill if fill is not None else cap["fill"])
    annot.set_border(width=cap["width"] if width is None else width)
    _mark(annot, cap["subject"])
    annot.update(blend_mode=cap["blend"], opacity=cap["opacity"])
    return annot


def _page_delta(page, dx: float, dy: float) -> "fitz.Point":
    """Déplacement exprimé à l'écran -> déplacement en coordonnées internes
    (la rotation de la page échange et inverse les axes)."""
    m = page.derotation_matrix
    origin = fitz.Point(0, 0) * m
    return (fitz.Point(dx, dy) * m) - origin


def move_annot(doc: "fitz.Document", page_index: int, xref: int,
               dx: float, dy: float) -> Optional[dict]:
    """Déplace une annotation de (dx, dy) exprimés en coordonnées affichées.

    Renvoie la description de l'annotation déplacée (son xref change, car elle
    est recréée), ou None si elle est introuvable.
    """
    page = doc[page_index]
    delta = _page_delta(page, dx, dy)
    cap = None
    for annot in page.annots():
        if annot.xref == xref:
            cap = _capture(annot)
            page.delete_annot(annot)
            break
    if cap is None:
        return None
    fresh = _recreate(page, cap, delta=delta)
    if fresh is None:
        _recreate(page, cap)          # remise en place si la recréation échoue
        return None
    return _annot_info(page, fresh)


def set_annot_style(doc: "fitz.Document", page_index: int, xref: int,
                    color=None, width=None, fill=False) -> Optional[dict]:
    """Change les attributs d'un tracé ou d'un surlignage déjà posé.

    `fill=False` laisse le remplissage inchangé ; `fill=None` le retire.
    Les textes se modifient avec `update_text_box`.
    """
    page = doc[page_index]
    for annot in page.annots():
        if annot.xref != xref:
            continue
        colors = annot.colors or {}
        stroke = color or tuple(colors.get("stroke") or ()) or None
        if fill is False:                 # remplissage inchange
            new_fill = tuple(colors.get("fill") or ()) or None
        else:
            # PyMuPDF interprete None comme « ne rien changer » : pour retirer
            # un remplissage, il faut lui passer une couleur vide.
            new_fill = [] if fill is None else fill
        annot.set_colors(stroke=stroke, fill=new_fill)
        if width is not None:
            annot.set_border(width=max(0.0, width))
        opacity = annot.opacity
        annot.update(blend_mode=annot.blendmode,
                     opacity=1.0 if opacity is None or opacity < 0 else opacity)
        return _annot_info(page, annot)
    return None


def annot_style(doc: "fitz.Document", page_index: int, xref: int) -> Optional[dict]:
    """Attributs actuels d'une annotation : couleur, épaisseur, remplissage."""
    page = doc[page_index]
    for annot in page.annots():
        if annot.xref == xref:
            colors = annot.colors or {}
            return {
                "color": _round_color(colors.get("stroke")),
                "fill": _round_color(colors.get("fill")),
                "width": round((annot.border or {}).get("width") or 0.0, 2),
                "family": _family(annot),
            }
    return None


# --------------------------------------------------------------------------- #
#  Sélection de texte (PDF avec couche de texte)
# --------------------------------------------------------------------------- #
def _selection_quads(page, start, stop):
    """Quadrilatères de la sélection « au fil du texte » entre deux points
    (coordonnées internes), comme le glisser d'Acrobat."""
    try:
        quads = fitz.get_highlight_selection(page, start=start, stop=stop) or []
    except Exception:
        quads = []
    if not quads:
        # Glisser de bas en haut (ou de droite à gauche) : on réessaie dans
        # l'autre sens, la sélection de MuPDF suit le sens de lecture.
        try:
            quads = fitz.get_highlight_selection(page, start=stop, stop=start) or []
        except Exception:
            quads = []
    return quads


def select_text(doc: "fitz.Document", page_index: int, start, stop) -> dict:
    """Sélectionne le texte entre deux points (coordonnées affichées).

    Renvoie {"text": texte sélectionné, "rects": rectangles à mettre en
    évidence (coordonnées affichées)}. Un PDF image (sans couche de texte)
    renvoie une sélection vide : c'est le cas où il faut passer par l'OCR ou
    par le marqueur.
    """
    page = doc[page_index]
    p1, p2 = _page_point(page, start), _page_point(page, stop)
    quads = _selection_quads(page, p1, p2)
    rects = [_view_rect(page, fitz.Rect(q)) for q in quads]
    text = ""
    if quads:
        try:
            text = page.get_text_selection(p1, p2) or ""
            if not text.strip():
                text = page.get_text_selection(p2, p1) or ""
        except Exception:
            text = ""
    return {"text": text, "rects": rects}


def highlight_selection(doc: "fitz.Document", page_index: int, start, stop,
                        color=(1.0, 0.85, 0.0)) -> int:
    """Surligne le texte sélectionné entre deux points (coords affichées).

    Renvoie le nombre de lignes surlignées (0 si aucun texte sélectionné).
    """
    page = doc[page_index]
    quads = _selection_quads(page, _page_point(page, start),
                             _page_point(page, stop))
    if not quads:
        return 0
    annot = page.add_highlight_annot([fitz.Rect(q).quad for q in quads])
    annot.set_colors(stroke=color)
    _mark(annot, SUBJ_HIGHLIGHT)
    annot.update()
    return len(quads)


def has_text_layer(doc: "fitz.Document", page_index: int) -> bool:
    """Vrai si la page contient du texte sélectionnable (sinon : PDF image)."""
    try:
        return bool(doc[page_index].get_text().strip())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Cases à cocher
# --------------------------------------------------------------------------- #
def _is_checked(widget) -> bool:
    value = widget.field_value
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("", "off", "false", "0", "none")


def checkbox_at(doc: "fitz.Document", page_index: int, point) -> Optional[dict]:
    """Case à cocher de formulaire sous le point donné (coords affichées)."""
    page = doc[page_index]
    pt = _page_point(page, point)
    for widget in page.widgets():
        if widget.field_type != fitz.PDF_WIDGET_TYPE_CHECKBOX:
            continue
        if pt in widget.rect:
            return {
                "xref": widget.xref,
                "rect": _view_rect(page, widget.rect),
                "checked": _is_checked(widget),
                "name": widget.field_name or "",
            }
    return None


def toggle_checkbox(doc: "fitz.Document", page_index: int,
                    xref: int) -> Optional[bool]:
    """Coche / décoche une case de formulaire. Renvoie son nouvel état."""
    page = doc[page_index]
    for widget in page.widgets():
        if widget.xref != xref:
            continue
        state = not _is_checked(widget)
        widget.field_value = state
        widget.update()
        return state
    return None


def count_checkboxes(doc: "fitz.Document", page_index: int) -> int:
    """Nombre de cases à cocher de formulaire sur une page."""
    page = doc[page_index]
    return sum(1 for w in page.widgets()
               if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX)


def add_check_mark(doc: "fitz.Document", page_index: int, rect,
                   color=(0.10, 0.30, 0.75), width: float = 2.0) -> None:
    """Dessine une coche (✓) dans le rectangle donné (coords affichées).

    Sert aux cases à cocher **imprimées** (PDF image ou PDF sans formulaire) :
    la coche est un tracé ordinaire, donc déplaçable et effaçable comme les
    autres dessins.
    """
    page = doc[page_index]
    r = _page_rect(page, rect)
    if r.width < 3 or r.height < 3:
        r = fitz.Rect(r.x0, r.y0, r.x0 + 14, r.y0 + 14) & page.rect
    points = [
        (r.x0 + r.width * 0.12, r.y0 + r.height * 0.55),
        (r.x0 + r.width * 0.40, r.y0 + r.height * 0.86),
        (r.x0 + r.width * 0.90, r.y0 + r.height * 0.14),
    ]
    annot = page.add_ink_annot([points])
    annot.set_colors(stroke=color)
    annot.set_border(width=max(1.0, width))
    _mark(annot, SUBJ_DRAW)
    annot.update()


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
