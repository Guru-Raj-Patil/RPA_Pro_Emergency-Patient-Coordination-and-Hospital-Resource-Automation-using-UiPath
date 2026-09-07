@echo off
title Emergency Coordination Console
cd /d "%~dp0"
echo Starting the Emergency Coordination Console...
echo A browser tab will open at http://localhost:8000
echo Close this window (or press Ctrl+C) to stop.
echo.
python console_server.py
if errorlevel 1 (
  echo.
  echo Could not start. Make sure Python 3 is installed and on PATH.
  pause
)
