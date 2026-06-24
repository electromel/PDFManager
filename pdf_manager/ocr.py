"""
ocr.py  (variante Tesseract)
============================
OCR via **Tesseract** (le moteur tesseract.exe est embarqué dans l'exécutable).

Robustesse :
- Les modèles de langue sont gérés dans un dossier ACCESSIBLE EN ÉCRITURE
  (sous %LOCALAPPDATA%). Au besoin, eng/fra y sont copiés depuis l'installation
  Tesseract trouvée, ou téléchargés depuis le dépôt officiel tessdata_fast.
- La couche de texte cherchable est construite par l'application (via PyMuPDF)
  à partir des positions de mots renvoyées par Tesseract : aucune dépendance à
  pdf.ttf ni aux fichiers configs d'une installation complète.

API : `is_available()` et `ocr_document()`.
"""

from __future__ import annotations

import os
import sys
import shutil
import urllib.request
from typing import Callable, List, Optional

import fitz  # PyMuPDF

DEFAULT_LANGS = ["eng", "fra"]

_TESSDATA_URLS = [
    "https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata_fast@main/{lang}.traineddata",
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{lang}.traineddata",
    "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata",
]

_LANGDETECT_TO_TESS = {
    "en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita",
    "pt": "por", "nl": "nld", "ca": "cat", "ro": "ron", "id": "ind",
    "vi": "vie", "tr": "tur", "pl": "pol", "cs": "ces", "sk": "slk",
    "hu": "hun", "da": "dan", "sv": "swe", "no": "nor", "nb": "nor",
    "fi": "fin", "hr": "hrv", "sl": "slv", "et": "est", "lt": "lit",
    "lv": "lav", "ru": "rus", "uk": "ukr", "bg": "bul", "el": "ell",
    "ar": "ara", "fa": "fas", "ur": "urd", "hi": "hin", "th": "tha",
    "ja": "jpn", "ko": "kor", "zh-cn": "chi_sim", "zh-tw": "chi_tra",
}


# --------------------------------------------------------------------------- #
#  Localisation du moteur Tesseract
# --------------------------------------------------------------------------- #
def _app_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_tesseract() -> Optional[str]:
    """Chemin de l'exécutable tesseract (embarqué, installé, ou dans le PATH)."""
    root = _app_root()
    candidates = [
        os.path.join(root, "tesseract", "tesseract.exe"),
        os.path.join(root, "tesseract", "tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which("tesseract")


def is_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return _find_tesseract() is not None


# --------------------------------------------------------------------------- #
#  Dossier de langues accessible en écriture
# --------------------------------------------------------------------------- #
def _has_models(d: Optional[str]) -> bool:
    try:
        return bool(d) and os.path.isdir(d) and any(
            f.endswith(".traineddata") for f in os.listdir(d)
        )
    except OSError:
        return False


def _valid_model(path: str) -> bool:
    """Un .traineddata valide pèse au moins ~100 Ko (évite les fichiers vides,
    partiels ou les espaces réservés OneDrive non synchronisés)."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 100000
    except OSError:
        return False


def _work_tessdata() -> str:
    """Dossier tessdata persistant et accessible en écriture."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "PDFManager", "tessdata")
    os.makedirs(d, exist_ok=True)
    return d


def _source_tessdatas(tess_cmd: Optional[str]) -> List[str]:
    """Dossiers tessdata existants où piocher des modèles déjà présents."""
    dirs: List[str] = []
    if tess_cmd:
        dirs.append(os.path.join(os.path.dirname(tess_cmd), "tessdata"))
    dirs.append(os.path.join(_app_root(), "tessdata"))
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        dirs.append(env)
        dirs.append(os.path.join(env, "tessdata"))
    dirs += [
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    ]
    import glob
    dirs += glob.glob("/usr/share/tesseract-ocr/*/tessdata")
    # dédoublonne en conservant l'ordre
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen:
            seen.add(d); out.append(d)
    return out


def _download_lang(lang: str, dest_dir: str,
                   progress: Optional[Callable] = None) -> bool:
    target = os.path.join(dest_dir, f"{lang}.traineddata")
    if progress:
        progress(0, 0, f"Téléchargement du modèle « {lang} »…")
    for url in _TESSDATA_URLS:
        try:
            req = urllib.request.Request(
                url.format(lang=lang), headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=120) as r, open(target, "wb") as f:
                shutil.copyfileobj(r, f)
            if os.path.getsize(target) > 300000:
                return True
        except Exception:
            continue
    if os.path.isfile(target):
        try:
            os.remove(target)
        except OSError:
            pass
    return False


def _prepare_langs(tess_cmd: Optional[str], langs: List[str],
                   progress: Optional[Callable] = None) -> str:
    """S'assure que chaque langue demandée est disponible dans le dossier de
    travail (copie depuis une install existante, sinon téléchargement).
    Renvoie le dossier tessdata de travail."""
    work = _work_tessdata()
    sources = [d for d in _source_tessdatas(tess_cmd) if _has_models(d)]
    for lang in langs:
        tgt = os.path.join(work, f"{lang}.traineddata")

        # Cherche un modèle VALIDE dans une source (priorité au modèle embarqué).
        src_model = None
        for s in sources:
            sp = os.path.join(s, f"{lang}.traineddata")
            if _valid_model(sp):
                src_model = sp
                break

        if src_model:
            # (Re)copie si la cible est absente OU de taille differente :
            # cela remplace tout fichier local invalide/corrompu.
            try:
                need = (not os.path.isfile(tgt)) or \
                    os.path.getsize(tgt) != os.path.getsize(src_model)
            except OSError:
                need = True
            if need:
                try:
                    if os.path.isfile(tgt):
                        os.remove(tgt)
                    shutil.copyfile(src_model, tgt)
                except OSError:
                    pass
            continue

        # Pas de source valide : si la cible est deja bonne on garde, sinon
        # on supprime un eventuel fichier invalide puis on telecharge.
        if _valid_model(tgt):
            continue
        if os.path.isfile(tgt):
            try:
                os.remove(tgt)
            except OSError:
                pass
        _download_lang(lang, work, progress)
    return work


def _available(work: str, langs: List[str]) -> List[str]:
    """Sous-ensemble des langues réellement présentes dans le dossier work."""
    return [l for l in langs if _valid_model(os.path.join(work, f"{l}.traineddata"))]


def _detect_language(text: str) -> Optional[str]:
    text = (text or "").strip()
    if len(text) < 12:
        return None
    try:
        from langdetect import detect
        return _LANGDETECT_TO_TESS.get(detect(text))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Couche de texte (construite par nous -> indépendante de pdf.ttf)
# --------------------------------------------------------------------------- #
def _page_image(doc: "fitz.Document", index: int, zoom: float):
    from PIL import Image
    import io
    pix = doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _insert_text_layer(page: "fitz.Page", data: dict, zoom: float) -> None:
    """Écrit une couche de texte invisible, regroupée par LIGNE, à partir de la
    sortie image_to_data (recherche de phrases possible)."""
    n = len(data.get("text", []))
    lines: dict = {}
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        if conf < 30:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left = data["left"][i]
        top = data["top"][i]
        right = left + data["width"][i]
        bottom = top + data["height"][i]
        entry = lines.get(key)
        if entry is None:
            lines[key] = [txt, left, top, right, bottom]
        else:
            entry[0] += " " + txt
            entry[1] = min(entry[1], left)
            entry[2] = min(entry[2], top)
            entry[3] = max(entry[3], right)
            entry[4] = max(entry[4], bottom)

    for txt, left, top, right, bottom in lines.values():
        x0 = left / zoom
        y0 = top / zoom
        h = (bottom - top) / zoom
        if h <= 0:
            continue
        fontsize = max(4.0, h * 0.85)
        try:
            page.insert_text(
                fitz.Point(x0, y0 + h * 0.85),
                txt, fontsize=fontsize, render_mode=3, fontname="helv",
            )
        except Exception:
            continue


def ocr_document(
    in_path: str,
    out_path: str,
    zoom: float = 2.5,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    """OCR d'un PDF complet -> PDF cherchable compressé. Renvoie la langue."""
    import pytesseract
    from pytesseract import Output

    tess = _find_tesseract()
    if not tess:
        raise RuntimeError(
            "Moteur Tesseract introuvable. Placez-le dans le dossier 'tesseract/' "
            "ou installez Tesseract-OCR."
        )
    pytesseract.pytesseract.tesseract_cmd = tess

    # Langues par défaut prêtes (copiées ou téléchargées) dans un dossier writable.
    if progress:
        progress(0, 1, "Préparation des langues…")
    work = _prepare_langs(tess, DEFAULT_LANGS, progress)
    base = _available(work, DEFAULT_LANGS)
    if not base:
        # repli : un dossier tessdata existant contient peut-être déjà eng/fra
        for src in _source_tessdatas(tess):
            avail = _available(src, DEFAULT_LANGS)
            if avail:
                work = src
                base = avail
                break
    if not base:
        raise RuntimeError(
            "Aucun modèle de langue disponible.\n"
            "Placez eng.traineddata (et fra.traineddata) dans :\n"
            f"{_work_tessdata()}\n"
            "puis relancez l'OCR."
        )
    # On s'appuie UNIQUEMENT sur TESSDATA_PREFIX (le sous-processus tesseract
    # en hérite). Passer --tessdata-dir via config casse les chemins Windows
    # (guillemets/backslashes mal découpés par pytesseract).
    os.environ["TESSDATA_PREFIX"] = work
    base_str = "+".join(base)            # ex. "eng+fra" ou "eng"
    primary = base[0]                    # langue d'appui (eng si présent)

    doc = fitz.open(in_path)
    total = doc.page_count

    # 1) Détection de la langue.
    if progress:
        progress(0, total, "Détection de la langue…")
    detected = None
    for i in range(min(total, 3)):
        img = _page_image(doc, i, zoom)
        try:
            sample = pytesseract.image_to_string(img, lang=base_str)
        except Exception:
            sample = ""
        detected = _detect_language(sample)
        if detected:
            break

    if detected and detected not in DEFAULT_LANGS:
        _prepare_langs(tess, [detected], progress)
        if _available(work, [detected]):
            lang_str = f"{detected}+{primary}"
            detected_label = detected
        else:
            lang_str = base_str
            detected_label = f"{base_str} (langue {detected} indisponible)"
    else:
        lang_str = base_str
        detected_label = detected or f"{base_str} (par défaut)"

    # 2) OCR page par page + couche de texte.
    for i in range(total):
        if progress:
            progress(i + 1, total, f"OCR page {i + 1}/{total}…")
        page = doc[i]
        img = _page_image(doc, i, zoom)
        data = pytesseract.image_to_data(
            img, lang=lang_str, output_type=Output.DICT
        )
        _insert_text_layer(page, data, zoom)

    from . import pdf_ops
    pdf_ops.save_compressed(doc, out_path)
    doc.close()
    return detected_label
