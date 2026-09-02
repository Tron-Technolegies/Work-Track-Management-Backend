@echo off
title WorkTrack Agent Installer
echo ============================================================
echo   WorkTrack Desktop Monitoring Agent - Setup & Auto-Start
echo ============================================================
echo.

set "AGENT_DIR=%~dp0"
set "AGENT_DIR=%AGENT_DIR:~0,-1%"
set "VBS_PATH=%AGENT_DIR%\worktrack_agent_silent.vbs"
set "TASK_NAME=WorkTrackMonitoringAgent"

if exist "%AGENT_DIR%\venv\Scripts\python.exe" (
    set "PYTHON_EXE=%AGENT_DIR%\venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo [1/3] Checking employee session...
%PYTHON_EXE% -c "import desktop_agent; a = desktop_agent.WorkTrackAgent(); exit(0 if a.load_session() and a.verify_token() else 1)" >nul 2>&1

if errorlevel 1 (
    echo.
    echo Please log in with your WorkTrack Employee credentials:
    echo --------------------------------------------------------
    set /p EMP_EMAIL="Employee Email: "
    set /p EMP_PASS="Employee Password: "
    echo.
    echo Authenticating with WorkTrack server...
    %PYTHON_EXE% desktop_agent.py --email "%EMP_EMAIL%" --password "%EMP_PASS%" --login-only
    if errorlevel 1 (
        echo [ERROR] Authentication failed. Please verify your credentials.
        pause
        exit /b 1
    )
) else (
    echo [OK] Existing employee session found and verified.
)

echo.
echo [2/3] Registering auto-start on Windows login...
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "wscript.exe \"%VBS_PATH%\"" ^
  /sc onlogon ^
  /rl highest ^
  /f ^
  /delay 0000:10 >nul 2>&1

if errorlevel 1 (
    echo [WARN] Task Scheduler registration failed. Falling back to Windows Startup folder...
    set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    copy /y "%VBS_PATH%" "%STARTUP%\WorkTrackAgent.vbs" >nul
    echo [OK] Copied to Startup folder: %STARTUP%\WorkTrackAgent.vbs
) else (
    echo [OK] Registered in Windows Task Scheduler (%TASK_NAME%).
)

echo.
echo [3/3] Starting WorkTrack Background Agent...
wscript.exe "%VBS_PATH%"
echo [OK] Agent is now running silently in the background.

echo.
echo ============================================================
echo   SETUP COMPLETE!
echo.
echo   - The agent will now run silently whenever you log in.
echo   - When you Clock In on the web app, screenshots, apps,
echo     and website tracking will start AUTOMATICALLY.
echo   - When you Clock Out, all monitoring stops AUTOMATICALLY.
echo ============================================================
echo.
pause
