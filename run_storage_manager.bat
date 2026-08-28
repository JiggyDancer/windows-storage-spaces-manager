@echo off
:: Check for administrator privileges
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Running with administrative privileges...
    goto :check_uv
) else (
    echo Requesting administrative privileges...
    goto :elevate
)

:elevate
:: Relaunch the batch file with admin rights
powershell -Command "Start-Process '%~f0' -Verb RunAs"
exit /b

:check_uv
:: Change directory to the script's location
cd /d "%~dp0"

:: Check if 'uv' is available in the system PATH
where uv >nul 2>&1
if %errorLevel% == 0 (
    echo Found uv. Syncing dependencies...
    uv add customtkinter
    echo Launching application with uv...
    uv run python gui_main.py
) else (
    echo UV not found. Falling back to standard pip...

    :: Check if customtkinter is installed via pip
    python -c "import customtkinter" 2>nul
    if %errorLevel% neq 0 (
        echo Installing dependencies using pip...
        python -m pip install customtkinter
    )

    echo Launching application...
    python gui_main.py
)

:: Keep the window open if the application closes or errors out
if %errorLevel% neq 0 (
    echo.
    echo An error occurred. Please check the output above.
    pause
)