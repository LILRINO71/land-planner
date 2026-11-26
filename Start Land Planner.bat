@echo off
rem Double-click to start Land Planner. It runs on this computer only and opens in your browser.
title Land Planner
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m landplanner %*
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python -m landplanner %*
  goto done
)
echo.
echo  Land Planner needs Python 3, which was not found on this computer.
echo  Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo  then double-click this file again.
echo.
pause
exit /b 1

:done
if errorlevel 1 (
  echo.
  echo  Land Planner stopped with a problem. The lines above say what went wrong.
  pause
)
