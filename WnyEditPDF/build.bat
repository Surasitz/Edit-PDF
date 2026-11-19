@echo off
rem Build WnyEditPDF.exe: the PdfCraft engine (Rust) first when its sources are
rem here, then the app (Python) with the engine bundled inside, so the result is
rem a single file that runs anywhere.
setlocal
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

set "PY=py"
if exist "..\.venv\Scripts\python.exe" set "PY=..\.venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

set "ENGINE="

echo [1/4] Building the PdfCraft engine (Rust)...
if not exist "..\pdfcraft\Cargo.toml" goto :engine_prebuilt
where cargo >nul 2>nul
if errorlevel 1 (
    echo   cargo not found - install Rust from https://rustup.rs and the
    echo   Visual Studio Build Tools ^(C++ workload^), then run this again.
    goto :engine_prebuilt
)
pushd ..\pdfcraft
cargo build --release -p pdfcraft-cli
if errorlevel 1 (
    popd
    echo Engine build failed.
    exit /b 1
)
popd
set "ENGINE=..\pdfcraft\target\release\pdfcraft-cli.exe"
goto :engine_done

:engine_prebuilt
rem No Rust sources: fall back to the engine binary kept in engine\
if exist "engine\pdfcraft-cli.exe" (
    echo   ..\pdfcraft not found - using the prebuilt engine\pdfcraft-cli.exe
    set "ENGINE=engine\pdfcraft-cli.exe"
) else (
    echo   WARNING: no engine found. The document tools ^(digital signatures,
    echo   PDF/A, compare, sanitize^) will be unavailable in this build.
)

:engine_done

echo [2/4] Installing Python dependencies...
"%PY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

echo [3/4] Building WnyEditPDF.exe...
set "ENGINE_ARG="
if defined ENGINE set "ENGINE_ARG=--add-binary "%ENGINE%;engine""
rem Two icons go into the .exe, in this order: the application logo (index 0,
rem shown for the program itself) and the document icon (index 1, what Explorer
rem puts on .pdf files - registered as "<exe>",1 by wnyeditpdf\fileassoc.py).
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name WnyEditPDF ^
    --icon wnyeditpdf/assets/logo.ico ^
    --icon wnyeditpdf/assets/pdf-doc.ico ^
    --add-data "fonts;fonts" ^
    --add-data "wnyeditpdf/assets;wnyeditpdf/assets" ^
    %ENGINE_ARG% ^
    --hidden-import qrcode ^
    --hidden-import fontTools ^
    --hidden-import PyQt6.QtNetwork ^
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
