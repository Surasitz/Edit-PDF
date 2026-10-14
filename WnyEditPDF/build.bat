@echo off
rem Build WnyEditPDF.exe: the PdfCraft engine (Rust) first, then the app (Python) with
rem the engine bundled inside, so the result is a single file that runs anywhere.
setlocal
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

set "PY=py"
if exist "..\.venv\Scripts\python.exe" set "PY=..\.venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

set "ENGINE=..\pdfcraft\target\release\pdfcraft-cli.exe"

echo [1/4] Building the PdfCraft engine (Rust)...
where cargo >nul 2>nul
if errorlevel 1 (
    echo   cargo not found - install Rust from https://rustup.rs and the
    echo   Visual Studio Build Tools ^(C++ workload^), then run this again.
    exit /b 1
)
pushd ..\pdfcraft
cargo build --release -p pdfcraft-cli
if errorlevel 1 (
    popd
    echo Engine build failed.
    exit /b 1
)
popd

echo [2/4] Installing Python dependencies...
"%PY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

echo [3/4] Building WnyEditPDF.exe...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name WnyEditPDF ^
    --icon wnyeditpdf/assets/logo.ico ^
    --add-data "fonts;fonts" ^
    --add-data "wnyeditpdf/assets;wnyeditpdf/assets" ^
    --add-binary "%ENGINE%;engine" ^
    --hidden-import qrcode ^
    --hidden-import fontTools ^
    main.py
if errorlevel 1 exit /b 1

echo [4/4] Checking output...
if exist dist\WnyEditPDF.exe (
    echo Build completed successfully.
    echo Output: dist\WnyEditPDF.exe
) else (
    echo Build failed or output was not generated.
    exit /b 1
)
