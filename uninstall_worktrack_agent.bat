@echo off
title WorkTrack Agent Uninstaller
echo Removing WorkTrack Monitoring Agent from auto-start...
schtasks /delete /tn "WorkTrackMonitoringAgent" /f >nul 2>&1
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP%\WorkTrackAgent.vbs" del /f "%STARTUP%\WorkTrackAgent.vbs"
echo Stopping any running agent processes...
taskkill /f /im pythonw.exe >nul 2>&1
echo Done. WorkTrack Agent has been removed from auto-start.
pause
