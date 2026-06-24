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
echo [3/4] Nettoyage de l'ancienne sortie dist\PDFManager...
if exist "%OUTDIR%\PDFManager" rmdir /S /Q "%OUTDIR%\PDFManager" >nul 2>&1
if exist "%OUTDIR%\PDFManager" timeout /t 1 >nul
if exist "%OUTDIR%\PDFManager" rmdir /S /Q "%OUTDIR%\PDFManager" >nul 2>&1

echo.
echo [4/4] Generation de l'executable avec PyInstaller...
pyinstaller "%CD%\run.py" --name PDFManager --onedir --windowed --noconfirm --clean --distpath "%OUTDIR%" --workpath "%WORKDIR%" --specpath "%WORKDIR%" --add-data "%CD%\tesseract;tesseract" --add-data "%CD%\tessdata;tessdata" --collect-all PySide6 --collect-submodules fitz
if errorlevel 1 goto err_build

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
echo Astuce : fermez l'application si elle est ouverte, mettez OneDrive en pause,
echo puis relancez build.bat.
pause
exit /b 1
