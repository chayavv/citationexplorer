@echo off
setlocal

echo ============================================================
echo  Citation Explorer — Build Script
echo ============================================================
echo.

:: Activate the citations conda environment
:: Adjust the path below to match your Anaconda installation
call "%USERPROFILE%\anaconda3\Scripts\activate.bat" citations
if errorlevel 1 (
    :: Try common alternative locations
    call "%USERPROFILE%\Anaconda3\Scripts\activate.bat" citations
    if errorlevel 1 (
        echo ERROR: Could not activate conda env "citations"
        echo Make sure Anaconda is installed and the "citations" env exists.
        echo Run:  conda create -n citations python=3.11
        echo Then: pip install -r requirements.txt
        pause & exit /b 1
    )
)

:: Ensure PyInstaller is installed
echo [1/3] Checking PyInstaller...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

:: Clean previous build artifacts
echo [2/3] Cleaning previous build...
if exist build   rmdir /s /q build
if exist dist    rmdir /s /q dist

:: Run the build
echo [3/3] Building CitationExplorer.exe (this takes 2-5 minutes)...
echo.
pyinstaller citation_explorer.spec --clean

if errorlevel 1 (
    echo.
    echo BUILD FAILED. Check the output above for errors.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  SUCCESS!
echo  Output: dist\CitationExplorer.exe
echo.
echo  Share just that single .exe file.
echo  The .history.txt file will be created next to it on first run.
echo ============================================================
echo.

:: Open the dist folder
explorer dist

pause
