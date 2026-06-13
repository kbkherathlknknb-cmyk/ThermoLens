@echo off
title ThermoLens - Temperature Monitor
cd /d "%~dp0"

echo ========================================
echo   ThermoLens - Temperature Monitor
echo   Starting with admin privileges...
echo ========================================
echo.

start "" pythonw app.py
