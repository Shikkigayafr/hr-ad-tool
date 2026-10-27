@echo off
rem Double-click launcher: collects inventory of THIS PC (read-only) into the "out" folder next to the script.
rem To write to a network share, edit OUTPUT below, e.g. set OUTPUT=\\server\inventory$
rem Run as Administrator to also collect TPM / Secure Boot data (optional).
set OUTPUT=%~dp0out
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Collect-Inventory.ps1" -OutputPath "%OUTPUT%"
echo.
pause
