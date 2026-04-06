@echo off
REM  build.bat — Build the Affinity-PDF-Markdown Converter (Windows)
REM
REM  Prerequisites:
REM    - Python 3.11 venv with deps installed (marker-pdf/venv311)
REM    - Inno Setup installed (https://jrsoftware.org/isinfo.php) [optional]
REM    - Run from the windows-installer/ directory
REM
REM  Output: Output\Affinity-PDF-Markdown-Converter_Setup.exe

echo.
echo ================================================
echo   Affinity-PDF-Markdown Converter — Build Script
echo ================================================
echo.

if not exist "main.py" (
    echo ERROR: Run this script from the windows-installer directory.
    exit /b 1
)

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

pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller>=6.0
)

echo.
echo [2/3] Running PyInstaller (this takes several minutes)...
echo.
pyinstaller affinity_converter_win.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. Check the output above.
    exit /b 1
)

echo.
echo PyInstaller complete. Output in dist\Affinity-PDF-Markdown Converter\
echo.

echo [3/3] Building installer with Inno Setup...

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
    echo The PyInstaller build is complete. You can distribute:
    echo   dist\Affinity-PDF-Markdown Converter\
    echo.
    echo To create a proper installer, install Inno Setup from
    echo https://jrsoftware.org/isinfo.php and re-run this script.
    exit /b 0
)

"%ISCC%" installer.iss
if errorlevel 1 (
    echo.
    echo ERROR: Inno Setup compilation failed.
    exit /b 1
)

echo.
echo ================================================
echo   BUILD COMPLETE
echo ================================================
echo.
echo Installer: Output\Affinity-PDF-Markdown-Converter_Setup.exe
echo.
