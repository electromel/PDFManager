# PDF Manager — variante Tesseract empaqueté

Même application que la version principale, mais l'**OCR utilise Tesseract**
(exécutable plus léger et OCR plus rapide qu'EasyOCR). Le moteur `tesseract.exe`
est embarqué : l'utilisateur final n'installe rien.

---

## 1. Fonctionnalités

Écran des PDF (bibliothèque) :

- ajout par glisser-déposer ou bouton « Ajouter des PDF » ;
- vignettes de la 1ère page de chaque document ;
- sélection multiple numérotée (1, 2, 3…) ; recliquer désélectionne et
  renumérote ;
- **OCR sur la sélection** : applique l'OCR à tous les documents sélectionnés
  (un `*_ocr.pdf` cherchable et compressé par document) ;
- **« Tout sélectionner / désélectionner »** (bouton bascule) ;
- **recherche plein texte** dans les documents sélectionnés (résultats par
  document et par page, double-clic pour ouvrir) ;
- fusion des documents sélectionnés.

Double-clic sur un document → visionneuse :

- **1 page** : le contenu s'affiche en grand, avec **zoom** ;
- **plusieurs pages** : affichage **en continu (par défaut)** ou en
  **vignettes**, les deux avec **zoom** (boutons ➖ ➕ ⤢, ou molette + Ctrl) ;
- bouton **OCR** du document ;
- **rotation** des pages (90°/180°, sens horaire/anti-horaire) : pages
  sélectionnées, ou tout le document si rien n'est sélectionné ;
- **suppression** d'une ou plusieurs pages sélectionnées ;
- **clic droit** sur une vignette : pivoter / supprimer / découper avant ou après ;
- **réorganisation** des pages par glisser-déposer (mode vignettes) ;
- **enregistrement** d'un nouveau document (nom proposé, option de suppression
  de la source), toujours compressé.

L'OCR Tesseract détecte la langue automatiquement (eng/fra par défaut, autres
langues chargées à la volée) et produit un PDF cherchable.

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
premier OCR, dans `%LOCALAPPDATA%\PDFManager\tessdata` (accessible en
écriture).

> Repli : si `tesseract\` reste vide, l'application utilise un Tesseract
> installé sur la machine (`C:\Program Files\Tesseract-OCR` ou PATH).

---

## 3. Générer l'exécutable autonome

Pré-requis de build : **Python 3.10+** (seulement pour fabriquer l'exe).

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

## 5. Structure

```
PDFManager_Tesseract/
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
