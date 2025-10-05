#!/bin/bash
#
# System Dashboard Build Script for Unix/Linux/macOS
# This script builds the executable using PyInstaller
#
# Set -e makes the script exit immediately if a command exits with a non-zero status (error)
# However, we handle errors explicitly, so we'll leave it off for controlled flow.

echo "===================================="
echo "System Dashboard Builder"
echo "===================================="
echo

# --- [0/5] Change directory to the script's location ---
# This ensures all file paths (like hmi.py, settings.ini) are relative to the script location.
cd "$(dirname "$0")"

# --- Function to handle script exit and pause ---
# The original script uses 'pause' on error. We mimic this behaviour.
exit_on_error() {
    local exit_code=$1
    local message=$2
    if [ "$exit_code" -ne 0 ]; then
        echo "ERROR: $message"
        read -r -p "Press Enter to continue..."
        exit "$exit_code"
    fi
}

# --- [1/5] Checking Python installation (using python3 as preferred) ---
PYTHON_CMD=""
PIP_CMD=""

if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
    PIP_CMD="pip3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
    PIP_CMD="pip"
else
    echo "ERROR: Python is not installed or not in PATH"
    echo "Please install Python 3.8 or higher"
    read -r -p "Press Enter to continue..."
    exit 1
fi

echo "Using Python command: $PYTHON_CMD"

# --- [1/5] Checking PyInstaller installation ---
echo "[1/5] Checking PyInstaller installation..."
if ! $PIP_CMD show pyinstaller &>/dev/null; then
    echo "PyInstaller not found. Installing..."
    $PIP_CMD install pyinstaller
    exit_on_error $? "Failed to install PyInstaller. Check your pip/python installation or permissions."
fi

# --- [2/5] Cleaning previous build files ---
echo "[2/5] Cleaning previous build files..."
# Remove 'build' and 'dist' directories recursively and quietly
if [ -d build ]; then
    rm -rf build
fi
if [ -d dist ]; then
    rm -rf dist
fi
# Remove the spec file if it exists
if [ -f pc-hmi.spec ]; then
    rm -f pc-hmi.spec
fi

# --- [3/5] Checking for settings.ini ---
echo "[3/5] Checking for settings.ini..."
if [ ! -f settings.ini ]; then
    echo "WARNING: settings.ini not found, will be created at runtime"
fi

# --- [4/5] Building executable ---
echo "[4/5] Building executable..."
# Note the use of backslashes (\) for line continuation in Bash
$PYTHON_CMD -m PyInstaller --onefile \
            --windowed \
            --name="pc-hmi" \
            --add-data="settings.ini:." \
            --hidden-import=pynvml \
            --hidden-import=GPUtil \
            --hidden-import=pyamdgpuinfo \
            --hidden-import=pyadl \
            --hidden-import=wmi \
            --hidden-import=cpuinfo \
            --collect-all=PyQt6 \
            hmi.py

exit_on_error $? "Build failed. Check the PyInstaller output above for details."

# --- [5/5] Finalizing and Copying files ---
echo "[5/5] Build complete!"
echo

# Optional: Copy settings.ini to dist folder
if [ -f settings.ini ]; then
    cp settings.ini dist/settings.ini
    echo "settings.ini copied to dist folder"
fi

echo
echo "===================================="
echo "Build completed successfully!"
echo "===================================="
echo "Executable location: dist/pc-hmi"
echo "You can find your executable in the 'dist' folder"
echo
read -r -p "Press Enter to exit..."
exit 0
