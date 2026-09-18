@echo off
chcp 65001 >nul
echo ================================================
echo   SnapCap - Build EXE + Installer
echo ================================================
echo.

:: This script lives in build\ (dev tooling, kept out of the project root
:: per the project's folder-hygiene standard) — the app source, assets, and
:: requirements.txt it references are all one level up.
cd /d "%~dp0.."

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ first.
    pause & exit /b 1
)

:: Install dependencies
echo [1/3] Installing Python dependencies...
pip install -r build\requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install requirements.
    pause & exit /b 1
)

:: Create icon
echo [2/3] Generating icon...
python build\create_icon.py >nul 2>&1

:: Build main EXE with PyInstaller (scratch output stays under build\, not
:: in the project root — see --distpath/--workspec below)
:: NOTE (found + fixed 2026-09-15, part of the --onefile->--onedir migration
:: build verification): PyInstaller resolves RELATIVE --icon/--add-data
:: sources against --specpath (build\), not the CWD — a bare "assets;assets"
:: here silently looked for build\assets (which doesn't exist) instead of
:: the project root's assets\, and the build failed the first time this
:: script was actually run end-to-end. %CD% is the project root at this
:: point (see `cd /d "%~dp0.."` above), so use absolute paths.
echo [3/3] Building main EXE with PyInstaller...
pyinstaller ^
    --name "SnapCap" ^
    --onedir ^
    --windowed ^
    --icon="%CD%\assets\icon.ico" ^
    --add-data "%CD%\assets;assets" ^
    --add-data "%CD%\version.json;." ^
    --distpath build\dist ^
    --workpath build\pyinstaller-work ^
    --specpath build ^
    --hidden-import=PyQt6.QtCore ^
    --hidden-import=PyQt6.QtGui ^
    --hidden-import=PyQt6.QtWidgets ^
    --hidden-import=PyQt6.sip ^
    --hidden-import=PIL._tkinter_finder ^
    --hidden-import=PIL.Image ^
    --hidden-import=mss ^
    --hidden-import=keyboard ^
    --hidden-import=pyperclip ^
    --hidden-import=anthropic ^
    --hidden-import=pytesseract ^
    --hidden-import=win32clipboard ^
    --hidden-import=win32event ^
    --hidden-import=win32api ^
    --hidden-import=win32crypt ^
    --hidden-import=winerror ^
    --hidden-import=psutil ^
    --hidden-import=i18n ^
    --hidden-import=onboarding_wizard ^
    --hidden-import=splash_screen ^
    --hidden-import=logger ^
    --collect-all=pytesseract ^
    --noconfirm ^
    main.py

if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause & exit /b 1
)

echo.
echo Building installer (bundles the app EXE, then removes the loose copy)...
python build\build_installer.py

echo.
echo ================================================
echo   Build complete!
echo   Single installer file: SnapCap-Setup-VERSION.exe (project root)
echo ================================================
pause
