@echo off
rem Double-click to install (or update) Land Planner on this computer. No administrator rights are needed.
rem It runs install.ps1 from this project's GitHub page, which downloads the latest release.
title Install Land Planner
echo.
echo  Installing Land Planner. This takes about a minute.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $f = Join-Path $env:TEMP 'install-land-planner.ps1'; try { Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/LILRINO71/land-planner/main/install.ps1' -OutFile $f; & $f } catch { Write-Host ''; Write-Host ('  Could not install: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
  echo.
  echo  Land Planner was not installed. Check the internet connection and try again.
  echo.
  pause
  exit /b 1
)
echo  Done. You can close this window.
timeout /t 6 >nul
