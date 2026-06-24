@echo off
REM ===================================================================
REM  lancer_sans_build.bat
REM  Lance l'application directement (sans generer d'exe) pour tester.
REM  Necessite un Tesseract portable dans tesseract\ (ou installe sur le PC).
REM ===================================================================
setlocal
cd /d "%~dp0"

REM Un .venv copie/deplace contient des chemins absolus casses -> on le recree.
if exist ".venv\Scripts\python.exe" goto _chk_venv
goto _make_venv
:_chk_venv
".venv\Scripts\pip.exe" --version >nul 2>&1
if errorlevel 1 echo Environnement .venv invalide (deplace) : recreation... & rmdir /S /Q ".venv"

:_make_venv
if exist ".venv\Scripts\activate.bat" goto _run
echo Installation de l'environnement (premiere fois)...
python -m venv .venv
if errorlevel 1 goto _no_python
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
goto _start

:_run
call ".venv\Scripts\activate.bat"

:_start
python run.py
exit /b 0

:_no_python
echo ERREUR : Python introuvable. Installez Python 3.10+ et relancez.
pause
exit /b 1
