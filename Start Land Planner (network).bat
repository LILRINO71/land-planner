@echo off
rem Double-click to let partners, consultants and city staff sign in from their own computers.
rem It serves HTTPS on port 8777 and prints the address to give them. This computer must stay on.
rem For use on this computer only, use "Start Land Planner.bat" instead.
title Land Planner (network)
cd /d "%~dp0"

set "PY="
if exist "%~dp0runtime\python.exe" set "PY="%~dp0runtime\python.exe""
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if defined PY goto found
echo.
echo  Land Planner needs Python 3, which was not found on this computer.
echo  Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo  then double-click this file again.
echo.
pause
exit /b 1

:found

rem The first time, make this computer's own HTTPS certificate (Windows makes it; nothing is downloaded).
if not exist "%~dp0data\tls\cert.pem" (
  echo  Making this computer's HTTPS certificate...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make-cert.ps1"
  if errorlevel 1 (
    echo.
    echo  The certificate could not be made. The lines above say why.
    pause
    exit /b 1
  )
)

echo.
echo  Windows may ask whether Python may use the network: choose "Private networks" and Allow.
echo.
%PY% -m landplanner --host 0.0.0.0 --https %*
if errorlevel 1 (
  echo.
  echo  Land Planner stopped with a problem. The lines above say what went wrong.
  pause
)
