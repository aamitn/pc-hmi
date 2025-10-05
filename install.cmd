@echo off
setlocal

:: Check if running as admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: ===============================================================
:: CONFIGURATION
:: ===============================================================

set "APP_NAME=PC-HMI System Dashboard"
set "EXE_FILENAME=pc-hmi.exe"
set "TARGET_DIR=%ProgramData%\PC-HMI"

:: Start Menu and Startup folders
set "START_MENU_DIR=%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

:: ===============================================================
:: 1. FIND EXECUTABLE
:: ===============================================================

echo.
echo --- 1. Locating Executable ---

if exist "%~dp0%EXE_FILENAME%" (
    set "SOURCE_PATH=%~dp0%EXE_FILENAME%"
    echo Found executable in the root directory.
) else if exist "%~dp0dist\%EXE_FILENAME%" (
    set "SOURCE_PATH=%~dp0dist\%EXE_FILENAME%"
    echo Found executable in 'dist' folder.
) else (
    echo.
    echo ERROR: The executable "%EXE_FILENAME%" was not found in:
    echo - "%~dp0%EXE_FILENAME%"
    echo - "%~dp0dist\%EXE_FILENAME%"
    echo Installation failed.
    goto :FAIL
)

:: ===============================================================
:: 2. INSTALLATION (COPY FILES)
:: ===============================================================

echo.
echo --- 2. Installing %APP_NAME% to %TARGET_DIR% ---

if not exist "%TARGET_DIR%" (
    echo Creating installation directory: "%TARGET_DIR%"
    mkdir "%TARGET_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create installation directory. Run as Administrator.
        goto :FAIL
    )
)

copy /Y "%SOURCE_PATH%" "%TARGET_DIR%" >nul
if errorlevel 1 (
    echo ERROR: Failed to copy executable.
    goto :FAIL
)
echo Executable copied successfully.

set "INSTALLED_EXE_PATH=%TARGET_DIR%\%EXE_FILENAME%"

:: ===============================================================
:: 3. CREATE SHORTCUTS
:: ===============================================================

echo.
echo --- 3. Creating Start Menu, Startup, and Desktop Shortcuts ---

:: Define Desktop folder
set "DESKTOP_DIR=%USERPROFILE%\Desktop"

:: Function to create shortcut
set "SHORTCUT_TARGET=%INSTALLED_EXE_PATH%"
set "SHORTCUT_WORKDIR=%TARGET_DIR%"

:: Start Menu Shortcut
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%START_MENU_DIR%\%APP_NAME%.lnk'); $Shortcut.TargetPath = '%SHORTCUT_TARGET%'; $Shortcut.WorkingDirectory = '%SHORTCUT_WORKDIR%'; $Shortcut.Save()"

:: Startup Shortcut
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTUP_DIR%\%APP_NAME%.lnk'); $Shortcut.TargetPath = '%SHORTCUT_TARGET%'; $Shortcut.WorkingDirectory = '%SHORTCUT_WORKDIR%'; $Shortcut.Save()"

:: Desktop Shortcut
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%DESKTOP_DIR%\%APP_NAME%.lnk'); $Shortcut.TargetPath = '%SHORTCUT_TARGET%'; $Shortcut.WorkingDirectory = '%SHORTCUT_WORKDIR%'; $Shortcut.Save()"

echo Shortcuts created in Start Menu, Startup folder, and Desktop.


:: ===============================================================
:: SUCCESS
:: ===============================================================

echo.
echo ===============================================================
echo %APP_NAME% Installation Complete!
echo Executable installed to "%TARGET_DIR%"
echo Start Menu shortcut and autostart created.
echo ===============================================================
goto :END

:FAIL
echo.
echo Installation failed.
pause
goto :END

:END
endlocal
