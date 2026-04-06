@echo off
REM ──────────────────────────────────────────────────────────────────
REM  build.bat — Build the HomeStead Converter Windows installer
REM
REM  This script:
REM    1. Activates the Python venv
REM    2. Runs PyInstaller to bundle the app + all dependencies
REM    3. Runs Inno Setup to create the installer .exe
REM
REM  Prerequisites:
REM    - Python 3.11 venv with all deps installed (marker-pdf/venv311)
REM    - Inno Setup installed (https://jrsoftware.org/isinfo.php)
REM    - Run from the windows-installer/ directory
REM
REM  Output: Output\HomeStead_Converter_Setup.exe
REM ──────────────────────────────────────────────────────────────────

echo.
echo ============================================
echo   HomeStead Converter — Build Script
echo ============================================
echo.

REM ── Check we're in the right directory ─────────────────────────────
if not exist "main.py" (
    echo ERROR: Run this script from the windows-installer directory.
    echo   cd windows-installer
    echo   build.bat
    exit /b 1
)

REM ── Activate the venv ────────────────────────────────────────────
echo [1/3] Activating Python venv...
if exist "..\marker-pdf\venv311\Scripts\activate.bat" (
    call ..\marker-pdf\venv311\Scripts\activate.bat
) else (
    echo ERROR: Could not find marker-pdf\venv311
    echo Please create it first:
    echo   cd ..\marker-pdf
    echo   python -m venv venv311
    echo   venv311\Scripts\activate
    echo   pip install -r requirements.txt
    exit /b 1
)

REM ── Verify PyInstaller is available ────────────────────────────────
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller>=6.0
)

REM ── Run PyInstaller ────────────────────────────────────────────
echo.
echo [2/3] Running PyInstaller (this takes several minutes)...
echo.
pyinstaller homestead_converter.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. Check the output above.
    exit /b 1
)

echo.
echo PyInstaller complete. Output in dist\HomeStead Converter\
echo.

REM ── Run Inno Setup (if installed) ──────────────────────────────────
echo [3/3] Building installer with Inno Setup...

REM Try common Inno Setup install locations
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
)

if "%ISCC%"=="" (
    echo.
    echo NOTE: Inno Setup not found.
    echo.
    echo The PyInstaller build is complete — you can distribute the
    echo folder at: dist\HomeStead Converter\
    echo.
    echo To create a proper installer .exe:
    echo   1. Download Inno Setup from https://jrsoftware.org/isinfo.php
    echo   2. Open installer.iss in Inno Setup Compiler
    echo   3. Click Build → Compile
    echo.
    echo Or re-run this script after installing Inno Setup.
    exit /b 0
)

"%ISCC%" installer.iss
if errorlevel 1 (
    echo.
    echo ERROR: Inno Setup compilation failed.
    exit /b 1
)

echo.
echo ============================================
echo   BUILD COMPLETE
echo ============================================
echo.
echo Installer: Output\HomeStead_Converter_Setup.exe
echo.
echo You can distribute this single file. Users double-click
echo it to install the app with Start Menu shortcut and all.
echo.
