@echo off
REM ===================================================================
REM  build.bat - Generation de l'executable autonome (variante Tesseract)
REM  Pre-requis : copier Tesseract-OCR dans le dossier tesseract\
REM  Sortie     : dist\PDFManager\PDFManager.exe
REM ===================================================================
setlocal
cd /d "%~dp0"

set "OUTDIR=%CD%\dist"
set "WORKDIR=%TEMP%\GPDF_build"
REM PyInstaller genere d'abord dans un dossier LOCAL (hors OneDrive) : ecrire
REM directement dans dist\ (synchronise) peut produire un exe incomplet
REM (ex. base_library.zip manquant -> "Failed to start embedded python
REM interpreter!"). La sortie est ensuite copiee vers dist\ via robocopy.
set "STAGEDIR=%TEMP%\GPDF_dist"

REM Ferme une eventuelle instance en cours (sinon le .exe est verrouille)
taskkill /IM PDFManager.exe /F >nul 2>&1

if not exist "tesseract\tesseract.exe" goto no_tess
if not exist "tessdata" mkdir "tessdata"

REM --- Anglais (requis) ---
if not exist "tessdata\eng.traineddata" if exist "tesseract\tessdata\eng.traineddata" copy /Y "tesseract\tessdata\eng.traineddata" "tessdata\eng.traineddata" >nul
if not exist "tessdata\eng.traineddata" if exist "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" copy /Y "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" "tessdata\eng.traineddata" >nul
if not exist "tessdata\eng.traineddata" powershell -NoProfile -Command "try { Invoke-WebRequest -UserAgent 'Mozilla/5.0' -Uri 'https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata_fast@main/eng.traineddata' -OutFile 'tessdata\eng.traineddata' } catch {}"

REM --- Francais (recommande) ---
if not exist "tessdata\fra.traineddata" if exist "tesseract\tessdata\fra.traineddata" copy /Y "tesseract\tessdata\fra.traineddata" "tessdata\fra.traineddata" >nul
if not exist "tessdata\fra.traineddata" if exist "C:\Program Files\Tesseract-OCR\tessdata\fra.traineddata" copy /Y "C:\Program Files\Tesseract-OCR\tessdata\fra.traineddata" "tessdata\fra.traineddata" >nul
if not exist "tessdata\fra.traineddata" powershell -NoProfile -Command "try { Invoke-WebRequest -UserAgent 'Mozilla/5.0' -Uri 'https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata_fast@main/fra.traineddata' -OutFile 'tessdata\fra.traineddata' } catch {}"

echo.
echo [1/4] Creation d'un environnement Python isole neuf...
REM On repart TOUJOURS d'un .venv propre : un venv copie/deplace a des
REM lanceurs (pip.exe, etc.) avec des chemins absolus casses.
if exist ".venv" rmdir /S /Q ".venv"
if exist ".venv" timeout /t 1 >nul
if exist ".venv" rmdir /S /Q ".venv"
python -m venv .venv
if errorlevel 1 goto no_python
call ".venv\Scripts\activate.bat"

echo.
echo [2/4] Installation des dependances...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto err_deps

echo.
echo [3/4] Generation de l'executable avec PyInstaller (dossier local)...
if exist "%STAGEDIR%\PDFManager" rmdir /S /Q "%STAGEDIR%\PDFManager" >nul 2>&1
pyinstaller "%CD%\run.py" --name PDFManager --onedir --windowed --noconfirm --clean --icon "%CD%\assets\app_icon.ico" --distpath "%STAGEDIR%" --workpath "%WORKDIR%" --specpath "%WORKDIR%" --add-data "%CD%\tesseract;tesseract" --add-data "%CD%\tessdata;tessdata" --add-data "%CD%\assets;assets" --collect-all PySide6 --collect-submodules fitz
if errorlevel 1 goto err_build

REM Verification du fichier critique avant copie.
if not exist "%STAGEDIR%\PDFManager\_internal\base_library.zip" goto err_incomplete

echo.
echo [4/4] Copie vers dist\PDFManager (robocopy, avec re-essais)...
robocopy "%STAGEDIR%\PDFManager" "%OUTDIR%\PDFManager" /MIR /R:5 /W:2 /NFL /NDL /NJH >nul
REM robocopy : code retour inferieur a 8 = succes.
if errorlevel 8 goto err_copy
if not exist "%OUTDIR%\PDFManager\_internal\base_library.zip" goto err_copy

echo.
echo Termine.
echo Executable : %OUTDIR%\PDFManager\PDFManager.exe
echo Lancement par double-clic, sans installation.
echo.
pause
exit /b 0

:no_tess
echo ERREUR : tesseract\tesseract.exe introuvable.
echo Copiez le contenu de Tesseract-OCR dans le dossier tesseract\ puis relancez.
echo Voir tesseract\PLACEZ_TESSERACT_ICI.txt
pause
exit /b 1

:no_python
echo ERREUR : Python introuvable. Installez Python 3.10+ et relancez.
pause
exit /b 1

:err_deps
echo ERREUR lors de l'installation des dependances.
pause
exit /b 1

:err_build
echo ERREUR lors de la generation PyInstaller.
echo Astuce : fermez l'application si elle est ouverte, puis relancez build.bat.
pause
exit /b 1

:err_incomplete
echo ERREUR : sortie PyInstaller incomplete (base_library.zip manquant).
echo Relancez build.bat ; si cela persiste, verifiez l'antivirus.
pause
exit /b 1

:err_copy
echo ERREUR lors de la copie vers dist\PDFManager.
echo Fermez l'application si elle est ouverte, mettez OneDrive en pause,
echo puis relancez build.bat.
pause
exit /b 1
