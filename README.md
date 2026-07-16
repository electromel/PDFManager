# PDF Manager

Application de bureau autonome pour **gérer, fusionner, découper et OCRiser des
PDF**. Le moteur OCR **Tesseract** est embarqué dans l'exécutable : l'utilisateur
final n'installe rien.

**Exécution sans installation et sans dépendance tierce** : l'exécutable se lance
directement par double-clic, ne nécessite aucune installation et ne dépend
d'aucune application ou logiciel tiers pour fonctionner (Tesseract et toutes les
bibliothèques requises sont embarqués).

---

## 1. Fonctionnalités

### Bibliothèque (écran principal)

- **Ajout de PDF** par glisser-déposer ou via le bouton « Ajouter des PDF ».
- **Vignettes** de la première page de chaque document.
- **Sélection multiple numérotée** : un `1` apparaît sur le premier document
  sélectionné, puis `2`, `3`… ; recliquer sur un document le désélectionne et
  renumérote automatiquement les suivants.
- **Tout sélectionner / désélectionner** (bouton bascule).
- **Fusion (merge)** des documents sélectionnés dans l'ordre de sélection.
- **OCR sur la sélection** : applique l'OCR à tous les documents sélectionnés
  (produit un PDF cherchable et compressé par document).
- **Recherche plein texte** dans les documents sélectionnés (résultats par
  document et par page, double-clic pour ouvrir la page).

### Visionneuse (double-clic sur un document)

- **Affichage 1 page** en grand, avec **zoom**.
- **Affichage multi-pages** : **en continu** (par défaut) ou en **vignettes**,
  les deux avec zoom (boutons ➖ ➕ ⤢ ou molette + Ctrl).
- **OCR** du document ouvert (bouton dédié).
- **Découpe (split)** : clic droit sur une page → découper **avant** ou
  **après** cette page.
- **Rotation** des pages (90° / 180°, sens horaire / anti-horaire) : pages
  sélectionnées, ou tout le document si rien n'est sélectionné.
- **Suppression** d'une ou plusieurs pages sélectionnées.
- **Réorganisation** des pages par glisser-déposer (mode vignettes).
- **Surlignage** (comme Acrobat) : bouton surligneur puis glisser à la souris —
  sur du **texte**, chaque mot est surligné ; sur une **image/zone sans texte**,
  un aplat de couleur semi-transparent est posé. Choix de la couleur (jaune,
  vert, bleu, rose) via la flèche du bouton ; effacement des surlignages
  (sélection ou tout le document) depuis le même menu. Les surlignages sont de
  vraies annotations PDF, conservées à l'enregistrement.
- **Copier / couper / coller de pages** : `Ctrl+C` / `Ctrl+X` / `Ctrl+V` (ou
  clic droit sur une vignette : copier, couper, coller **avant** ou **après**
  la page). Le collage fonctionne dans le **même document** ou dans **un autre
  document ouvert** (onglets) ; sans sélection, les pages sont collées à la fin.
- **Enregistrement** d'un nouveau document :
  - nom proposé automatiquement à partir du premier document ;
  - option de **suppression du document source** ;
  - le document enregistré est **toujours compressé**.

### OCR

L'OCR Tesseract **détecte la langue automatiquement**. Les langues **anglais
(eng)** et **français (fra)** sont disponibles par défaut ; toute autre langue
nécessaire est **chargée à la volée** selon le document. Le résultat est un PDF
cherchable.

---

## 2. Préparer Tesseract (une seule fois, avant le build)

1. Installez Tesseract pour Windows (UB Mannheim) :
   https://github.com/UB-Mannheim/tesseract/wiki
   — sous **Additional language data**, cochez le **français**.
2. Ouvrez le dossier d'installation (par défaut `C:\Program Files\Tesseract-OCR`).
3. **Copiez tout son contenu** dans le dossier **`tesseract\`** du projet
   (au minimum `tesseract.exe` + les `.dll`).

L'application n'a **pas** besoin de `pdf.ttf` ni des fichiers `configs` : elle
construit elle-même la couche de texte cherchable. Les modèles de langue
manquants (eng/fra puis autres) sont copiés ou téléchargés automatiquement au
premier OCR, dans `%LOCALAPPDATA%\PDFManager\tessdata` (accessible en écriture).

> Repli : si `tesseract\` reste vide, l'application utilise un Tesseract
> installé sur la machine (`C:\Program Files\Tesseract-OCR` ou PATH).

---

## 3. Générer l'exécutable autonome

Pré-requis de build : **Python 3.10+** (uniquement pour fabriquer l'exe ; pas
nécessaire pour l'utilisateur final).

1. Vérifiez que `tesseract\tesseract.exe` est présent (étape 2).
2. Double-cliquez sur **`build.bat`**.
3. Résultat : `dist\PDFManager\PDFManager.exe`.

Copiez tout le dossier `dist\PDFManager` où vous voulez : lancement par
double-clic, **sans installation**.

---

## 4. Tester sans build (optionnel)

Double-cliquez sur **`lancer_sans_build.bat`** (nécessite `tesseract\` rempli ou
Tesseract installé sur le PC).

---

## 5. Structure du projet

```
PDFManager/
├─ run.py
├─ build.bat                Génère l'exe (embarque tesseract\ et tessdata\)
├─ telecharger_langues.bat  Récupère eng + fra dans tesseract\tessdata\
├─ lancer_sans_build.bat
├─ requirements.txt
├─ README.md
├─ tesseract\               <-- y copier Tesseract-OCR (étape 2)
├─ tessdata\                Dossier de repli (langues)
└─ pdf_manager\
   ├─ main.py
   ├─ library.py    Bibliothèque + sélection + fusion + OCR sur la sélection
   ├─ viewer.py     Visionneuse (1 page grand / multi continu-vignettes + zoom)
   ├─ pdf_ops.py    Opérations PDF (rendu, fusion, découpe, compression)
   ├─ ocr.py        OCR Tesseract (langues writable, couche texte maison)
   └─ flowlayout.py Galerie
```

---

## 6. Développement

Application développée avec **Claude Opus 4.8** (Anthropic).

