@echo off
REM ===================================================================
REM  telecharger_langues.bat
REM  Telecharge les modeles eng + fra dans  tesseract\tessdata\
REM  (utile si le francais n'a pas ete coche lors de l'installation de
REM   Tesseract). A lancer apres avoir rempli le dossier tesseract\.
REM ===================================================================
setlocal
cd /d "%~dp0"

if not exist "tesseract\tessdata" (
    echo ERREUR : tesseract\tessdata introuvable.
    echo Copiez d'abord le contenu de Tesseract-OCR dans tesseract\ ^(voir
    echo tesseract\PLACEZ_TESSERACT_ICI.txt^).
    pause
    exit /b 1
)

echo Telechargement de eng.traineddata...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata' -OutFile 'tesseract\tessdata\eng.traineddata'"

echo Telechargement de fra.traineddata...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/fra.traineddata' -OutFile 'tesseract\tessdata\fra.traineddata'"

echo.
echo Termine. Contenu de tesseract\tessdata :
dir /b tesseract\tessdata
pause
