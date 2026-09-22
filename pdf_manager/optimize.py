"""
optimize.py
===========
Contrôle, réparation, nettoyage et compression des PDF.

Un seul passage « Optimiser » enchaîne, dans cet ordre :

  1. contrôle    — diagnostic d'intégrité du fichier (structure, pages, contenu) ;
  2. réparation  — reconstruction du document quand le contrôle l'exige ;
  3. nettoyage   — suppression des données parasites (métadonnées, scripts…) ;
  4. compression — recompression de la structure, des polices et des images.

Comme le reste du projet, tout repose sur PyMuPDF : aucun outil externe.
Ce module ne connaît pas Qt ; l'interface vit dans library.py.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Dict, List, Optional, Sequence

import fitz  # PyMuPDF


# --------------------------------------------------------------------------- #
#  Réglages exposés à l'interface
# --------------------------------------------------------------------------- #
#: Niveaux de compression, du plus prudent au plus agressif.
COMPRESS_LEVELS: List[str] = ["none", "light", "standard", "strong", "max"]

COMPRESS_LABELS: Dict[str, str] = {
    "none":     "Aucune — ne pas recompresser",
    "light":    "Légère — structure seulement (sans perte)",
    "standard": "Standard — structure + polices (sans perte)",
    "strong":   "Forte — images ré-échantillonnées à 110 ppp",
    "max":      "Maximale — images à 96 ppp, qualité réduite",
}

#: Ré-échantillonnage des images, pour les niveaux qui y touchent.
_IMAGE_SETTINGS: Dict[str, dict] = {
    "strong": {"dpi_threshold": 150, "dpi_target": 110, "quality": 70},
    "max":    {"dpi_threshold": 110, "dpi_target": 96,  "quality": 55},
}

#: Options de nettoyage : (clé, libellé, explication, coché par défaut).
#: Par défaut on ne retire que ce qui n'est jamais du contenu utile.
CLEAN_OPTIONS: List[tuple] = [
    ("metadata", "Métadonnées",
     "Titre, auteur, producteur, dates, et les métadonnées XMP.", True),
    ("javascript", "Scripts JavaScript",
     "Code exécuté à l'ouverture du document ou depuis un champ.", True),
    ("thumbnails", "Vignettes incorporées",
     "Aperçus de page stockés dans le fichier, recalculés à l'affichage.", True),
    ("clean_pages", "Flux de contenu",
     "Réécrit la syntaxe des pages en écartant ce qui ne sert à rien.", True),
    ("embedded_files", "Fichiers joints",
     "Pièces jointes incorporées au document.", False),
    ("hidden_text", "Texte masqué",
     "Texte présent dans le fichier mais invisible à l'écran.", False),
    ("remove_links", "Liens hypertexte",
     "Liens cliquables vers une page du document ou une adresse web.", False),
    ("reset_fields", "Champs de formulaire",
     "Remet les champs de saisie à leur valeur par défaut.", False),
    ("annotations", "Annotations",
     "Surlignages, dessins et textes ajoutés au document.", False),
]

DEFAULT_CLEAN: Dict[str, bool] = {
    key: default for key, _label, _hint, default in CLEAN_OPTIONS
}

#: Suffixe des copies lorsque l'utilisateur ne remplace pas les originaux.
COPY_SUFFIX = "_optimise"

#: Options de sauvegarde communes à tous les niveaux « réels ».
_SAVE_BASE = {
    "garbage": 4,          # objets inutilisés supprimés + déduplication
    "deflate": True,
    "deflate_images": True,
    "deflate_fonts": True,
    "clean": True,         # nettoyage de la syntaxe
    "pretty": False,
}


# --------------------------------------------------------------------------- #
#  Petits utilitaires
# --------------------------------------------------------------------------- #
def human_size(num_bytes: int) -> str:
    """Taille lisible : 1234567 -> « 1,2 Mo »."""
    value = float(max(0, int(num_bytes)))
    for unit in ("o", "Ko", "Mo", "Go"):
        if value < 1024 or unit == "Go":
            if unit == "o":
                return f"{int(value)} o"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{value:.1f} Go".replace(".", ",")


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def page_list(pages: Sequence[int], limit: int = 8) -> str:
    """« 3, 7, 12… » — liste de numéros de page abrégée."""
    numbers = list(pages)
    head = ", ".join(str(n) for n in numbers[:limit])
    if len(numbers) > limit:
        return f"{head}… (+{len(numbers) - limit})"
    return head


def safe_replace(src: str, dst: str) -> bool:
    """os.replace avec quelques tentatives : le fichier peut être verrouillé."""
    for _ in range(6):
        try:
            os.replace(src, dst)
            return True
        except OSError:
            time.sleep(0.3)
    return False


def _discard(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def copy_path_for(path: str) -> str:
    """Chemin de la copie optimisée, à côté de l'original."""
    base, ext = os.path.splitext(path)
    return f"{base}{COPY_SUFFIX}{ext or '.pdf'}"


# --------------------------------------------------------------------------- #
#  1. Contrôle
# --------------------------------------------------------------------------- #
def _blank_report(path: str) -> dict:
    return {
        "path": path,
        "size": file_size(path),
        "readable": False,
        "error": None,
        "locked": False,          # mot de passe : contenu inaccessible
        "encrypted": False,
        "repaired": False,        # MuPDF a dû reconstruire la table des objets
        "page_count": 0,
        "broken_pages": [],       # numéros 1-based
        "text_pages": 0,
        "images": 0,
        "annots": 0,
        "links": 0,
        "is_form": False,
        "embedded_files": 0,
        "metadata": False,
        "xml_metadata": False,
        "javascript": False,
        "issues": [],             # descriptions lisibles, en français
    }


def _catalog_xref(doc: "fitz.Document") -> Optional[int]:
    """Numéro d'objet du catalogue (/Root), ou None."""
    try:
        kind, value = doc.xref_get_key(-1, "Root")
        if kind != "xref":
            return None
        return int(value.split()[0])
    except Exception:
        return None


def _has_javascript(doc: "fitz.Document") -> bool:
    """JavaScript déclaré au niveau du document (noms, action d'ouverture)."""
    root = _catalog_xref(doc)
    if root is None:
        return False
    for key in ("Names/JavaScript", "OpenAction/JS", "AA"):
        try:
            kind, _value = doc.xref_get_key(root, key)
        except Exception:
            continue
        if kind not in ("null", "unknown"):
            return True
    return False


def _inspect_catalog(doc: "fitz.Document", report: dict) -> None:
    meta = doc.metadata or {}
    report["metadata"] = any(
        (meta.get(key) or "").strip()
        for key in ("title", "author", "subject", "keywords", "creator", "producer")
    )
    try:
        report["xml_metadata"] = bool((doc.get_xml_metadata() or "").strip())
    except Exception:
        pass
    try:
        report["embedded_files"] = int(doc.embfile_count())
    except Exception:
        pass
    try:
        report["is_form"] = bool(doc.is_form_pdf)
    except Exception:
        pass

    report["javascript"] = _has_javascript(doc)
    if report["javascript"]:
        report["issues"].append("Le document embarque du code JavaScript.")
    if report["embedded_files"]:
        report["issues"].append(
            f"{report['embedded_files']} fichier(s) joint(s) incorporé(s)."
        )


def _inspect_pages(doc: "fitz.Document", report: dict,
                   deep: bool = False,
                   progress: Optional[Callable[[str], None]] = None) -> None:
    total = doc.page_count
    for index in range(total):
        if progress and (deep or index % 25 == 0):
            progress(f"contrôle de la page {index + 1}/{total}")
        try:
            page = doc[index]
            if page.get_text("text").strip():
                report["text_pages"] += 1
            report["images"] += len(page.get_images(full=True))
            report["annots"] += sum(1 for _ in page.annots())
            report["links"] += len(page.get_links())
            if deep:
                # Rendu minuscule : le seul moyen sûr de repérer un flux de
                # contenu corrompu sans y passer la journée.
                page.get_pixmap(matrix=fitz.Matrix(0.1, 0.1), alpha=False)
        except Exception:
            report["broken_pages"].append(index + 1)

    if report["broken_pages"]:
        report["issues"].append(
            "Page(s) illisible(s) : " + page_list(report["broken_pages"]) + "."
        )
    if total and report["text_pages"] == 0:
        report["issues"].append(
            "Aucune couche de texte : document probablement scanné "
            "(un passage OCR le rendrait cherchable)."
        )


def inspect_file(path: str, deep: bool = False,
                 progress: Optional[Callable[[str], None]] = None) -> dict:
    """Contrôle d'intégrité d'un PDF. Ne modifie rien, renvoie un rapport.

    `deep` ajoute un rendu basse résolution de chaque page : c'est plus lent,
    mais c'est ce qui révèle les pages dont le contenu est corrompu.
    """
    report = _blank_report(path)
    try:
        doc = fitz.open(path)
    except Exception as exc:
        # Le texte de MuPDF est anglais et cite le chemin complet : il reste
        # dans « error » pour le diagnostic, l'utilisateur lit la phrase.
        report["error"] = str(exc)
        report["issues"].append(
            "Fichier illisible : format non reconnu ou document endommagé."
        )
        return report

    try:
        report["readable"] = True
        report["encrypted"] = bool(doc.is_encrypted)
        if doc.needs_pass and not doc.authenticate(""):
            report["locked"] = True
            report["issues"].append(
                "Document protégé par un mot de passe : contenu inaccessible."
            )
            return report

        report["repaired"] = bool(doc.is_repaired)
        if report["repaired"]:
            report["issues"].append(
                "Structure endommagée : la table des objets a dû être "
                "reconstruite à l'ouverture."
            )

        report["page_count"] = doc.page_count
        if report["page_count"] == 0:
            report["issues"].append("Document sans aucune page.")

        _inspect_catalog(doc, report)
        _inspect_pages(doc, report, deep=deep, progress=progress)
    except Exception as exc:
        report["error"] = str(exc)
        report["issues"].append(f"Contrôle interrompu : {exc}")
    finally:
        doc.close()
    return report


def needs_repair(report: dict) -> bool:
    """Le contrôle a-t-il trouvé quelque chose qu'une reconstruction corrige ?"""
    return bool(
        report.get("repaired")
        or report.get("broken_pages")
        or (report.get("readable") and report.get("error"))
    )


# --------------------------------------------------------------------------- #
#  2. Réparation
# --------------------------------------------------------------------------- #
def _rebuild(doc: "fitz.Document") -> tuple:
    """Reconstruit le document page par page.

    Renvoie (nouveau_document, pages_écartées). L'ancien document est fermé.
    Les pages qui refusent d'être copiées sont irrécupérables : on les écarte
    plutôt que de perdre tout le fichier.
    """
    rebuilt = fitz.open()
    dropped: List[int] = []
    for index in range(doc.page_count):
        try:
            rebuilt.insert_pdf(doc, from_page=index, to_page=index, annots=True)
        except Exception:
            dropped.append(index + 1)
    try:
        toc = doc.get_toc()
        if toc and not dropped:
            rebuilt.set_toc(toc)
    except Exception:
        pass
    doc.close()
    return rebuilt, dropped


# --------------------------------------------------------------------------- #
#  3. Nettoyage
# --------------------------------------------------------------------------- #
_SCRUB_KEYS = (
    "metadata", "javascript", "thumbnails", "clean_pages",
    "embedded_files", "hidden_text", "remove_links", "reset_fields",
)

#: Ce que le contrôle doit avoir repéré pour qu'on annonce un nettoyage.
#: Les options absentes d'ici agissent en silence (rien de mesurable à citer).
_CLEAN_EVIDENCE: Dict[str, Callable[[dict], bool]] = {
    "metadata":       lambda rep: bool(rep.get("metadata") or rep.get("xml_metadata")),
    "javascript":     lambda rep: bool(rep.get("javascript")),
    "embedded_files": lambda rep: bool(rep.get("embedded_files")),
    "remove_links":   lambda rep: bool(rep.get("links")),
    "reset_fields":   lambda rep: bool(rep.get("is_form")),
}


def _drop_annotations(doc: "fitz.Document") -> int:
    """Supprime toutes les annotations du document. Renvoie le nombre retiré."""
    removed = 0
    for page in doc:
        try:
            annot = page.first_annot
            while annot:
                annot = page.delete_annot(annot)
                removed += 1
        except Exception:
            continue
    return removed


def _forget_javascript(doc: "fitz.Document") -> None:
    """Retire l'entrée /Names/JavaScript du catalogue.

    `scrub()` vide bien le code, mais laisse la clé en place : un contrôle
    ultérieur signalerait encore un document « avec JavaScript ».
    """
    root = _catalog_xref(doc)
    if root is None:
        return
    for key in ("Names/JavaScript", "OpenAction/JS"):
        try:
            doc.xref_set_key(root, key, "null")
        except Exception:
            pass


def _clean(doc: "fitz.Document", options: Dict[str, bool],
           report: dict) -> List[str]:
    """Applique le nettoyage demandé ; renvoie ce qui a été retiré.

    Seules les suppressions que le contrôle a pu constater sont citées :
    annoncer « vignettes supprimées » sur un document qui n'en avait aucune
    ne renseignerait personne.
    """
    done: List[str] = []

    if options.get("annotations"):
        removed = _drop_annotations(doc)
        if removed:
            done.append(f"{removed} annotation(s) supprimée(s)")

    if not any(options.get(key) for key in _SCRUB_KEYS):
        return done

    doc.scrub(
        attached_files=bool(options.get("embedded_files")),
        clean_pages=bool(options.get("clean_pages")),
        embedded_files=bool(options.get("embedded_files")),
        hidden_text=bool(options.get("hidden_text")),
        javascript=bool(options.get("javascript")),
        metadata=bool(options.get("metadata")),
        redactions=False,
        remove_links=bool(options.get("remove_links")),
        reset_fields=bool(options.get("reset_fields")),
        reset_responses=False,
        thumbnails=bool(options.get("thumbnails")),
        xml_metadata=bool(options.get("metadata")),
    )
    if options.get("javascript"):
        _forget_javascript(doc)

    labels = {key: label for key, label, _hint, _d in CLEAN_OPTIONS}
    done += [
        f"Nettoyage : {labels[key][0].lower()}{labels[key][1:]}"
        for key in _SCRUB_KEYS
        if options.get(key) and _CLEAN_EVIDENCE.get(key, lambda _r: False)(report)
    ]
    return done


# --------------------------------------------------------------------------- #
#  4. Compression
# --------------------------------------------------------------------------- #
def _save(doc: "fitz.Document", out_path: str, options: dict) -> None:
    """doc.save() tolérant : les options récentes sont abandonnées si besoin."""
    try:
        doc.save(out_path, **options)
    except TypeError:
        legacy = {
            key: value for key, value in options.items()
            if key not in ("use_objstms", "compression_effort")
        }
        doc.save(out_path, **legacy)


def _write(doc: "fitz.Document", out_path: str, level: str) -> None:
    """Écrit le document au niveau de compression demandé (images exclues)."""
    if level == "none":
        options = {"garbage": 1, "deflate": True, "clean": False, "pretty": False}
    else:
        options = dict(_SAVE_BASE)

    if level in ("standard", "strong", "max"):
        try:
            doc.subset_fonts(verbose=False)
        except Exception:
            pass
        options["use_objstms"] = 1
        options["compression_effort"] = 100

    if doc.is_encrypted:
        # Un document chiffré le reste : ce n'est pas à l'optimisation d'en
        # décider (le défaut de PyMuPDF retirerait le chiffrement).
        options["encryption"] = fitz.PDF_ENCRYPT_KEEP

    _save(doc, out_path, options)


def _shrink_images(in_path: str, out_path: str, level: str) -> bool:
    """Ré-échantillonne les images de in_path vers out_path. False si impossible."""
    settings = _IMAGE_SETTINGS.get(level)
    if not settings:
        return False
    doc = fitz.open(in_path)
    try:
        if not hasattr(doc, "rewrite_images"):
            return False
        doc.rewrite_images(
            lossy=True, lossless=True, color=True, gray=True, bitonal=False,
            **settings,
        )
        options = dict(_SAVE_BASE)
        options["use_objstms"] = 1
        options["compression_effort"] = 100
        if doc.is_encrypted:
            options["encryption"] = fitz.PDF_ENCRYPT_KEEP
        _save(doc, out_path, options)
        return True
    except Exception:
        return False
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
#  Enchaînement complet
# --------------------------------------------------------------------------- #
#: Étapes de l'enchaînement, dans l'ordre où elles s'exécutent.
STEP_LABELS: Dict[str, str] = {
    "check":    "contrôle",
    "repair":   "réparation",
    "clean":    "nettoyage",
    "compress": "compression",
    "write":    "écriture",
}


def _blank_result(in_path: str) -> dict:
    return {
        "path": in_path,
        "out_path": None,
        "ok": False,
        "error": None,
        "skipped": False,          # aucun gain : original conservé
        "size_before": file_size(in_path),
        "size_after": 0,
        "report": None,
        "repaired": False,
        "dropped_pages": [],
        "cleaned": [],
        "compress": "none",
        "actions": [],             # ce qui a réellement été fait
        # --- suivi de déroulement
        "status": "failed",        # done | unchanged | failed | cancelled
        "steps": [],               # [(libellé, état ou None), …]
        "notes": [],               # explications courtes, une par ligne
        "stopped_at": None,        # clé de l'étape qui a échoué, sinon None
        "summary": "",             # phrase récapitulative, en français
    }


def cancelled_result(in_path: str) -> dict:
    """Compte rendu d'un document jamais traité (annulation de l'utilisateur)."""
    result = _blank_result(in_path)
    result["status"] = "cancelled"
    result["size_after"] = result["size_before"]
    result["summary"] = "Annulé — ce document n'a pas été traité."
    result["notes"] = [
        "Le traitement s'est arrêté avant d'arriver à ce document.",
        "Le fichier n'a pas été modifié.",
    ]
    return result


def _mark(result: dict, key: str, state: Optional[str] = None) -> None:
    """Note qu'une étape s'est déroulée, avec éventuellement une nuance."""
    result["steps"].append((STEP_LABELS[key], state))


def steps_text(result: dict) -> str:
    """« contrôle · réparation (rien à réparer) · … » — le parcours en entier."""
    return " · ".join(
        label if state is None else f"{label} ({state})"
        for label, state in result["steps"]
    )


def steps_headline(result: dict) -> str:
    """Une ligne qui dit, sans rien déplier, si l'on est allé jusqu'au bout."""
    total = len(STEP_LABELS)
    count = len(result["steps"])
    if result["status"] == "cancelled":
        return "Étapes : aucune, le document n'a pas été traité"
    if result["stopped_at"]:
        return (f"Étapes : arrêt à « {STEP_LABELS[result['stopped_at']]} » "
                f"({count} sur {total})")
    return f"Étapes : les {total} ont été exécutées"


def _fail(result: dict, key: str, message: str, *advice: str) -> dict:
    """Arrête le traitement en notant où et pourquoi."""
    result["error"] = message
    result["stopped_at"] = key
    result["notes"] = [message, *advice,
                       "Le fichier d'origine n'a pas été modifié."]
    result["steps"].append((STEP_LABELS[key], "échec"))
    return _finish(result)


def _size_change(result: dict) -> str:
    before = human_size(result["size_before"])
    after = human_size(result["size_after"])
    percent = gain_percent(result)
    if percent > 0:
        return f"{before} → {after}, soit {percent} % de moins"
    if percent < 0:
        return f"{before} → {after}, soit {-percent} % de plus"
    return f"taille inchangée ({after})"


def _unchanged_reasons(result: dict, clean: Optional[Dict[str, bool]],
                       candidate: int) -> List[str]:
    """Pourquoi le fichier d'origine a été conservé tel quel.

    Une raison par ligne, courte : ce texte s'affiche dans une ligne d'arbre,
    qui tronque au lieu de revenir à la ligne.
    """
    reasons = ["Rien à réparer : le contrôle n'a signalé aucun défaut."]
    if not clean or not any(clean.values()):
        reasons.append("Nettoyage : aucune option n'était cochée.")
    else:
        reasons.append("Rien à retirer : les données visées étaient absentes.")
    if result["compress"] == "none":
        reasons.append("Compression : désactivée.")
    else:
        reasons.append(
            f"Aucun gain : {human_size(result['size_before'])} avant, "
            f"{human_size(candidate)} après recompression."
        )
    return reasons


def _finish(result: dict, clean: Optional[Dict[str, bool]] = None,
            candidate: int = 0) -> dict:
    """Détermine le statut final, la phrase de verdict et ses explications."""
    if result["error"]:
        result["status"] = "failed"
        step = STEP_LABELS.get(result["stopped_at"] or "", "préparation")
        result["summary"] = f"Échec à l'étape « {step} »."
        return result

    if result["skipped"]:
        result["status"] = "unchanged"
        result["summary"] = "Terminé — fichier d'origine conservé tel quel."
        result["notes"] = _unchanged_reasons(result, clean, candidate)
        return result

    result["status"] = "done"
    result["ok"] = True
    result["summary"] = f"Terminé — {_size_change(result)}."
    return result


def optimize_file(
    in_path: str,
    out_path: Optional[str] = None,
    *,
    deep_check: bool = False,
    repair: bool = True,
    clean: Optional[Dict[str, bool]] = None,
    compress: str = "standard",
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """Contrôle, répare au besoin, nettoie et compresse un PDF.

    `out_path` vaut `in_path` par défaut (remplacement sur place, via un
    fichier temporaire). Renvoie un compte rendu détaillé ; aucune exception
    n'est propagée, les échecs sont décrits dans la clé « error ».
    """
    result = _blank_result(in_path)
    target = out_path or in_path
    result["out_path"] = target
    result["compress"] = compress if compress in COMPRESS_LEVELS else "standard"
    step = progress or (lambda _message: None)
    name = os.path.basename(in_path)

    step(f"{name} — contrôle…")
    report = inspect_file(
        in_path, deep=deep_check,
        progress=lambda message: step(f"{name} — {message}"),
    )
    result["report"] = report

    if report["locked"]:
        return _fail(
            result, "check",
            "Le document est protégé par un mot de passe.",
            "Son contenu est inaccessible sans le mot de passe.",
        )
    if not report["readable"]:
        return _fail(
            result, "check",
            "Fichier illisible : ce n'est pas un PDF exploitable.",
            "Format non reconnu, ou document trop endommagé pour s'ouvrir.",
        )
    _mark(result, "check",
          "aucun problème" if not report["issues"]
          else f"{len(report['issues'])} constat(s)")

    tmp_base = target + ".opt_tmp"
    tmp_image = target + ".opt_img_tmp"
    try:
        doc = fitz.open(in_path)
    except Exception as exc:
        return _fail(result, "check", "Ouverture impossible.", str(exc))

    current = "repair"   # étape en cours, citée si une exception survient
    try:
        if doc.needs_pass and not doc.authenticate(""):
            return _fail(result, "check",
                         "Le document est protégé par un mot de passe.")

        if not needs_repair(report):
            _mark(result, "repair", "rien à réparer")
        elif not repair:
            _mark(result, "repair", "désactivée alors qu'elle était nécessaire")
        else:
            step(f"{name} — réparation…")
            if report["broken_pages"]:
                doc, dropped = _rebuild(doc)
                result["dropped_pages"] = dropped
            result["repaired"] = True
            message = "Structure reconstruite"
            if result["dropped_pages"]:
                message += (
                    f" — {len(result['dropped_pages'])} page(s) irrécupérable(s) "
                    f"écartée(s) : {page_list(result['dropped_pages'])}"
                )
            result["actions"].append(message)
            _mark(result, "repair", "effectuée")

        current = "clean"
        if not clean or not any(clean.values()):
            _mark(result, "clean", "désactivé")
        else:
            step(f"{name} — nettoyage…")
            result["cleaned"] = _clean(doc, clean, report)
            result["actions"] += result["cleaned"]
            _mark(result, "clean",
                  "effectué" if result["cleaned"] else "rien à retirer")

        current = "compress"
        step(f"{name} — compression…")
        base_level = ("standard" if result["compress"] in _IMAGE_SETTINGS
                      else result["compress"])
        _write(doc, tmp_base, base_level)
    except Exception as exc:
        _discard(tmp_base)
        return _fail(result, current,
                     f"Erreur pendant l'étape : {exc}")
    finally:
        try:
            doc.close()
        except Exception:
            pass

    best = tmp_base
    if result["compress"] in _IMAGE_SETTINGS:
        step(f"{name} — recompression des images…")
        if (_shrink_images(tmp_base, tmp_image, result["compress"])
                and 0 < file_size(tmp_image) < file_size(tmp_base)):
            best = tmp_image
            _mark(result, "compress",
                  COMPRESS_LABELS[result["compress"]].split("—")[0].strip().lower())
        else:
            # Ré-échantillonner a échoué ou a grossi le fichier : on garde la
            # version sans perte plutôt que de dégrader les images pour rien.
            _discard(tmp_image)
            _mark(result, "compress",
                  "sans perte — ré-échantillonner les images n'aurait rien gagné")
    elif result["compress"] == "none":
        _mark(result, "compress", "désactivée")
    else:
        _mark(result, "compress",
              COMPRESS_LABELS[result["compress"]].split("—")[0].strip().lower())

    size_after = file_size(best)
    nothing_to_fix = not result["repaired"] and not result["cleaned"]
    same_file = os.path.abspath(target) == os.path.abspath(in_path)

    if nothing_to_fix and same_file and size_after >= result["size_before"]:
        # Rien à corriger et rien à gagner : on ne touche pas à l'original.
        _discard(tmp_base)
        _discard(tmp_image)
        result["ok"] = True
        result["skipped"] = True
        result["size_after"] = result["size_before"]
        result["actions"].append("Fichier d'origine conservé tel quel.")
        _mark(result, "write", "original conservé")
        return _finish(result, clean, size_after)

    if not safe_replace(best, target):
        _discard(tmp_base)
        _discard(tmp_image)
        return _fail(
            result, "write",
            "Écriture impossible : le fichier est verrouillé.",
            "Un autre programme le tient ouvert : Acrobat, l'aperçu de "
            "l'explorateur, ou une synchronisation OneDrive en cours.",
            "Fermez-le puis relancez l'optimisation.",
        )

    _discard(tmp_image if best == tmp_base else tmp_base)
    result["size_after"] = file_size(target)
    if result["compress"] != "none":
        label = COMPRESS_LABELS[result["compress"]].split("—")[0].strip()
        result["actions"].append(f"Compression « {label} »")
    _mark(result, "write", "fichier écrit")
    return _finish(result, clean, size_after)


def gain_percent(result: dict) -> int:
    """Gain de place en pourcentage (négatif si le fichier a grossi)."""
    before = result.get("size_before") or 0
    after = result.get("size_after") or 0
    if before <= 0:
        return 0
    return int(round((before - after) * 100.0 / before))
