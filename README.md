# PDF Manager

Application de bureau autonome pour **gérer, fusionner, découper, optimiser et
OCRiser des PDF**. Le moteur OCR **Tesseract** est embarqué dans l'exécutable :
l'utilisateur final n'installe rien.

**Exécution sans installation et sans dépendance tierce** : l'exécutable se lance
directement par double-clic, ne nécessite aucune installation et ne dépend
d'aucune application ou logiciel tiers pour fonctionner (Tesseract et toutes les
bibliothèques requises sont embarqués).

---

## 1. Fonctionnalités

### Bibliothèque (écran principal)

- **Ajout de PDF** par glisser-déposer ou via le bouton « Ajouter des PDF ».
- **Ouverture depuis l'explorateur Windows** : clic droit sur un PDF →
  **« Ouvrir avec »** → `PDFManager.exe` (voir §5). Le document est ajouté à la
  bibliothèque et affiché aussitôt dans la visionneuse. Fonctionne aussi en
  déposant un PDF sur `PDFManager.exe`, ou en ligne de commande :
  `PDFManager.exe "C:\chemin\document.pdf"`.
- **Vignettes** de la première page de chaque document.
- **Sélection multiple numérotée** : un `1` apparaît sur le premier document
  sélectionné, puis `2`, `3`… ; recliquer sur un document le désélectionne et
  renumérote automatiquement les suivants.
- **Tout sélectionner / désélectionner** (bouton bascule).
- **Fusion (merge)** des documents sélectionnés dans l'ordre de sélection.
- **OCR sur la sélection** : applique l'OCR à tous les documents sélectionnés
  (produit un PDF cherchable et compressé par document).
- **Optimisation de la sélection** (bouton « Optimiser », ou clic droit sur une
  vignette) : contrôle, réparation, nettoyage et compression en un seul passage
  (voir §1 « Optimisation »).
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
- **Suppression** d'une ou plusieurs pages sélectionnées : bouton corbeille ou
  touche **`Suppr`** (une confirmation est demandée ; supprimer *toutes* les
  pages est refusé).
- **Réorganisation** des pages par glisser-déposer (mode vignettes).

#### Annotation

Les outils d'annotation sont réunis dans un **bloc unique** de la barre
d'outils (mode continu) : ils s'excluent mutuellement et se quittent par
**`Échap`**.

- **Reprise d'une annotation** (flèche) : **cliquer** un texte, un tracé ou un
  surlignage le **sélectionne** (cadre et poignées) ;
  - **glisser** le **déplace** ;
  - **double-clic** ouvre ses attributs (couleur, épaisseur, remplissage pour
    un tracé ; contenu et mise en forme pour un texte) ;
  - **`Suppr`** efface **cette seule** annotation, sans toucher aux autres.

  Le double-clic et le clic droit fonctionnent aussi **sans activer l'outil**.

- **Sélection de texte** (curseur `I`), dans les PDF contenant du texte :
  glisser sur le document sélectionne le texte **au fil de la lecture** (comme
  Acrobat), puis :
  - **`Ctrl+C`** (ou le menu du bouton, ou le clic droit) **copie** le texte
    dans le presse-papiers de Windows ;
  - **« Surligner le texte sélectionné »** pose un vrai surlignage sur la
    sélection.

  Sur un PDF **image**, la sélection est vide et l'application le signale :
  lancez l'**OCR**, ou utilisez le **marqueur** ci-dessous.

- **Cases à cocher** : sur un **formulaire PDF**, un clic sur une case la
  **coche / décoche** réellement (l'état est enregistré dans le document) ; sur
  une case **imprimée** (PDF scanné, sans champ de formulaire), le clic pose
  une **coche dessinée** — glisser permet de l'ajuster à la taille de la case.
  Cette coche est un tracé ordinaire : déplaçable et effaçable comme les autres.

- **Surlignage** (comme Acrobat), deux modes au choix dans la flèche du bouton
  surligneur :
  - **Sélection** : glisser sur du **texte** surligne chaque mot ; glisser sur
    une **image / zone sans texte** pose un aplat teinté.
  - **Marqueur** : trait de surligneur **à main levée**, qui suit la souris —
    il ne dépend d'aucune couche de texte et fonctionne donc aussi sur un
    **PDF image** (page scannée), comme le marqueur d'Acrobat. Épaisseur du
    trait réglable (fin / moyen / épais).

  Couleur au choix (jaune, vert, bleu, rose) ; effacement des surlignages
  (sélection ou tout le document) depuis le même menu.

- **Texte** (bouton `T`) : **cliquer** sur la page pour poser un texte ;
  saisie sur plusieurs lignes, avec **police** (Helvetica, Times, Courier, gras
  ou italique), **corps**, **couleur** et **fond blanc opaque** (pour masquer ce
  qu'il y a dessous). Le texte reste **modifiable** : **double-clic** dessus (à
  tout moment, même sans outil actif) rouvre la saisie avec sa mise en forme,
  et l'outil texte permet de le **déplacer** par glisser. Le menu du bouton
  efface les textes ajoutés (sélection ou tout le document).

- **Dessin** : main levée, **ligne droite**, **flèche**, **rectangle** ou
  **ellipse**, avec **couleur**, **épaisseur** et **remplissage** au choix dans
  le menu du bouton, qui permet aussi d'effacer les dessins.

- **Clic droit sur une page** (mode continu) : modifier, sélectionner (pour la
  déplacer) ou supprimer l'annotation sous le curseur ; copier ou surligner le
  texte sélectionné ; effacer les surlignages / dessins / textes de cette page.
  **Échap** lève la sélection en cours, puis quitte l'outil.

  Toutes ces annotations sont de **vraies annotations PDF** : elles sont
  conservées à l'enregistrement, relues par n'importe quel lecteur PDF, et
  restent modifiables lors d'une prochaine ouverture du document.

#### Pages

- **Copier / couper / coller de pages** : `Ctrl+C` / `Ctrl+X` / `Ctrl+V` (ou
  clic droit sur une vignette : copier, couper, coller **avant** ou **après**
  la page). Le collage fonctionne dans le **même document** ou dans **un autre
  document ouvert** (onglets) ; sans sélection, les pages sont collées à la fin.
- **Enregistrement** d'un nouveau document :
  - nom proposé automatiquement à partir du premier document ;
  - option de **suppression du document source** ;
  - le document enregistré est **toujours compressé**.

### Optimisation

Le bouton **« Optimiser »** traite les documents sélectionnés en un seul
passage. Chaque étape est réglable dans la boîte de dialogue :

1. **Contrôle** — diagnostic d'intégrité : structure endommagée, pages
   illisibles, document chiffré, absence de couche de texte, scripts
   JavaScript, fichiers joints. Le **contrôle approfondi** (optionnel) rend
   chaque page en miniature : c'est plus lent, mais c'est le seul moyen de
   repérer une page dont le contenu est corrompu.
2. **Réparation** — quand le contrôle a trouvé quelque chose : la table des
   objets est reconstruite, et le document est réassemblé page par page si des
   pages sont illisibles. Les pages irrécupérables sont écartées et **citées
   par leur numéro** dans le rapport.
3. **Nettoyage** — au choix : métadonnées (y compris XMP), scripts JavaScript,
   vignettes incorporées, flux de contenu des pages (cochés par défaut) ;
   fichiers joints, texte masqué, liens hypertexte, champs de formulaire et
   annotations (décochés — ce sont des données que l'on peut vouloir garder).
4. **Compression** — cinq niveaux, d'« aucune » à « maximale ». Les trois
   premiers sont **sans perte** (déduplication des objets, recompression des
   flux, réduction des polices au strict nécessaire). Les deux derniers
   ré-échantillonnent les images à 110 ou 96 ppp : le texte reste intact, les
   photos et les scans perdent en finesse.

Deux garde-fous : si le résultat est **plus gros** que l'original, c'est
l'original qui est conservé ; un document **protégé par mot de passe** est
signalé et laissé intact. Le résultat remplace les fichiers d'origine ou crée
des copies suffixées `_optimise`, au choix.

#### Le rapport

Un **rapport** final donne, par document, un état et une explication — c'est
lui qui dit si le traitement est allé jusqu'au bout :

| État | Signification |
|---|---|
| **✓ Terminé** | Le fichier a été écrit ; la taille avant/après et le gain sont indiqués |
| **= Inchangé** | Le traitement est allé au bout, mais **l'original a été conservé tel quel** — les raisons sont listées : rien à réparer, rien à retirer, aucun gain à la recompression |
| **✕ Échec** | Le traitement s'est arrêté ; l'étape et la cause sont indiquées (mot de passe, fichier illisible, fichier verrouillé par un autre programme…) |
| **⊘ Annulé** | Le document n'a pas été atteint avant l'annulation |

Dans tous les cas, **le fichier d'origine n'est modifié que dans l'état
« Terminé »**. Chaque ligne se déplie sur le parcours détaillé
(`Étapes : les 5 ont été exécutées`, ou `arrêt à « contrôle » (1 sur 5)`), les
constats du contrôle et la liste de ce qui a été fait. Tout document
sélectionné figure au rapport, y compris ceux qui n'ont pas été traités.

> **Un document qui ne change pas n'est pas un échec.** Un PDF déjà produit ou
> optimisé par l'application est déjà compressé et dépourvu de métadonnées : il
> ressort en « Inchangé », et le rapport dit précisément pourquoi.

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

## 5. Associer les PDF à PDF Manager (« Ouvrir avec »)

L'exécutable accepte un chemin de PDF en argument : il apparaît donc dans le
menu **« Ouvrir avec »** de Windows dès qu'on le lui a désigné une fois.

1. Clic droit sur un fichier PDF → **Ouvrir avec** → **Choisir une autre
   application**.
2. **Plus d'applications** → **Rechercher une autre application sur ce PC**.
3. Sélectionnez `dist\PDFManager\PDFManager.exe`.
4. Cochez éventuellement *Toujours utiliser cette application* pour en faire le
   lecteur PDF par défaut.

> Chaque « Ouvrir avec » démarre une nouvelle instance de l'application ; évitez
> d'éditer et d'enregistrer le même document depuis deux fenêtres à la fois.

---

## 6. Structure du projet

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
   ├─ library.py    Bibliothèque + sélection + fusion + OCR + optimisation
   ├─ viewer.py     Visionneuse + outils d'annotation (reprise, sélection de
   │                texte, surligneur, texte, dessin, cases à cocher)
   ├─ pdf_ops.py    Opérations PDF (rendu, fusion, découpe, compression,
   │                annotations, sélection de texte, cases à cocher)
   ├─ optimize.py   Contrôle, réparation, nettoyage et compression
   ├─ ocr.py        OCR Tesseract (langues writable, couche texte maison)
   └─ flowlayout.py Galerie
```

---

## 7. Développement

Application développée avec **Claude Opus 4.8** (Anthropic).

