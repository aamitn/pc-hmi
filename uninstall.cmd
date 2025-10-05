@echo off
setlocal

:: ===============================================================
:: 0. KILL RUNNING PROCESS
:: ===============================================================

echo.
echo --- 0. Terminating running processes ---

tasklist /FI "IMAGENAME eq pc-hmi.exe" 2>NUL | find /I "pc-hmi.exe" >NUL
if %ERRORLEVEL%==0 (
    echo Found running pc-hmi.exe, terminating...
    taskkill /F /IM pc-hmi.exe >nul 2>&1
    if %ERRORLEVEL%==0 (
        echo pc-hmi.exe terminated successfully.
    ) else (
        echo Failed to terminate pc-hmi.exe. Close it manually and rerun uninstall.
        pause
        exit /b
    )
) else (
    echo pc-hmi.exe is not running.
)

:: ===============================================================
:: 1. CHECK ADMIN
:: ===============================================================

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

:: Shortcut locations
set "START_MENU_DIR=%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "DESKTOP_DIR=%USERPROFILE%\Desktop"

set "INSTALLED_EXE_PATH=%TARGET_DIR%\%EXE_FILENAME%"

:: ===============================================================
:: 2. DELETE SHORTCUTS
:: ===============================================================

echo.
echo --- 2. Removing shortcuts ---

set "SHORTCUTS=%START_MENU_DIR%\%APP_NAME%.lnk;%STARTUP_DIR%\%APP_NAME%.lnk;%DESKTOP_DIR%\%APP_NAME%.lnk"

for %%S in (%SHORTCUTS:;= %) do (
    if exist "%%S" (
        echo Deleting shortcut: "%%S"
        del /F "%%S"
    )
)

:: ===============================================================
:: 3. DELETE EXECUTABLE
:: ===============================================================

echo.
echo --- 3. Removing executable ---

if exist "%INSTALLED_EXE_PATH%" (
    echo Deleting: "%INSTALLED_EXE_PATH%"
    del /F "%INSTALLED_EXE_PATH%"
) else (
    echo Executable not found, skipping.
)

:: ===============================================================
:: 4. REMOVE INSTALLATION DIRECTORY
:: ===============================================================

echo.
echo --- 4. Removing installation folder ---

if exist "%TARGET_DIR%" (
    echo Removing all files in "%TARGET_DIR%"...
    attrib -H -S "%TARGET_DIR%\*" /S /D >nul 2>&1
    del /F /Q "%TARGET_DIR%\*" >nul 2>&1

    echo Removing all subdirectories...
    for /D %%D in ("%TARGET_DIR%\*") do rd /S /Q "%%D"

    rmdir /S /Q "%TARGET_DIR%"
    if not exist "%TARGET_DIR%" (
        echo Installation folder deleted successfully.
    ) else (
        echo Failed to remove installation folder, some files may be in use.
    )
)

:: ===============================================================
:: DONE
:: ===============================================================

echo.
echo ===============================================================
echo %APP_NAME% has been uninstalled.
echo ===============================================================
pause

endlocal
