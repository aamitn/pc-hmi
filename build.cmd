@echo off
REM Change directory to the script's location (requested by user)
cd /d "%~dp0"

REM System Dashboard Build Script for Windows
REM This script builds the executable using PyInstaller

echo ====================================
echo System Dashboard Builder
echo ====================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8 or higher
    pause
    exit /b 1
)

echo [1/5] Checking PyInstaller installation...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)

echo [2/5] Cleaning previous build files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist pc-hmi.spec del /q pc-hmi.spec

echo [3/5] Checking for settings.ini...
if not exist settings.ini (
    echo WARNING: settings.ini not found, will be created at runtime
)

echo [4/5] Building executable...
pyinstaller --onefile ^
            --windowed ^
            --name="pc-hmi" ^
            --add-data="settings.ini;." ^
            --hidden-import=pynvml ^
            --hidden-import=GPUtil ^
            --hidden-import=pyamdgpuinfo ^
            --hidden-import=pyadl ^
            --hidden-import=wmi ^
            --hidden-import=cpuinfo ^
            --collect-all=PyQt6 ^
            hmi.py

if errorlevel 1 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

echo [5/5] Build complete!
echo.
echo Executable location: dist\pc-hmi.exe
echo.

REM Optional: Copy settings.ini to dist folder
if exist settings.ini (
    copy /y settings.ini dist\settings.ini >nul
    echo settings.ini copied to dist folder
)

echo.
echo ====================================
echo Build completed successfully!
echo ====================================
echo.
echo You can find your executable in the 'dist' folder
echo.

pause