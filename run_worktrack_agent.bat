@echo off
title WorkTrack Desktop Monitoring Agent
echo ========================================================
echo        WorkTrack Desktop Monitoring Agent
echo ========================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

REM Check virtual environment or install requirements if missing
if exist venv\Scripts\python.exe (
    set PYTHON_CMD=venv\Scripts\python.exe
) else (
    set PYTHON_CMD=python
)

echo Starting WorkTrack Agent...
%PYTHON_CMD% desktop_agent.py %*

if errorlevel 1 (
    echo.
    echo [ERROR] Agent stopped with error.
    pause
)
