@echo off
setlocal enabledelayedexpansion
title Sovereign RMM - Push to GitHub

echo.
echo ============================================================
echo   SOVEREIGN RMM - Push to GitHub
echo ============================================================
echo.

:: Everything runs from wherever this script lives
:: No need to move any files - the folder structure is already correct
set REPO_URL=https://github.com/tesladog/sovereign-rmm.git
set HERE=%~dp0

:: ── CHECK GIT ───────────────────────────────────────────────
echo [1/3] Checking for Git...
set "PATH=%PATH%;C:\Program Files\Git\cmd;C:\Program Files (x86)\Git\cmd"
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo     Git is not installed!
    echo     Please download and install it from:
    echo     https://git-scm.com/download/win
    echo     Then run this script again.
    echo.
    pause
    exit /b 1
)
echo     Git found!

:: ── VERIFY FILES ────────────────────────────────────────────
echo.
echo [2/3] Verifying files are present...
set MISSING=0

call :Check "backend\Dockerfile"
call :Check "backend\main.py"
call :Check "backend\models.py"
call :Check "backend\requirements.txt"
call :Check "backend\routes\auth.py"
call :Check "backend\routes\devices.py"
call :Check "backend\routes\tasks.py"
call :Check "backend\routes\policies.py"
call :Check "backend\routes\dashboard.py"
call :Check "frontend\Dockerfile"
call :Check "frontend\index.html"
call :Check "frontend\nginx.conf"
call :Check "agent\windows_agent.py"
call :Check "agent\android_agent.py"
call :Check "guacamole-init\init.sh"
call :Check "README.md"

if %MISSING% gtr 0 (
    echo.
    echo     %MISSING% file(s) missing. Something went wrong with the zip.
    pause
    exit /b 1
)
echo.
echo     All files present!

:: ── PUSH TO GITHUB ──────────────────────────────────────────
echo.
echo [3/3] Ready to push to GitHub.
echo.
echo     BEFORE YOU CONTINUE make sure you have:
echo     1. Created an empty repo at github.com named: sovereign-rmm
echo        ( https://github.com/new )
echo     2. A Personal Access Token ready to use as your password
echo        ( https://github.com/settings/tokens/new )
echo        Check the "repo" box then click Generate Token
echo.
echo     Press any key when ready...
pause >nul

cd /d "%HERE%"

:: Create .gitignore so secrets never go to GitHub
(
echo # Never commit these - they contain your passwords and server IP
echo .env
echo compose.yaml
echo.
echo __pycache__/
echo *.pyc
echo *.log
echo push_to_github.bat
) > .gitignore

git init
git branch -M main
git remote remove origin >nul 2>&1
git remote add origin %REPO_URL%
git config user.email "deploy@sovereign-rmm"
git config user.name "Sovereign RMM"
git add .
git commit -m "Initial Sovereign RMM deployment"

echo.
echo     Enter your GitHub username and Personal Access Token now...
echo     (Paste the token when it asks for your password - it won't show as you type)
echo.
git push -u origin main

if %errorlevel% neq 0 (
    echo.
    echo ============================================================
    echo   Push failed. Check these:
    echo     1. Repo exists at github.com/tesladog/sovereign-rmm
    echo     2. Repo is completely EMPTY (no README, no files)
    echo     3. You used a Personal Access Token not your password
    echo ============================================================
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   SUCCESS! Repo is live at:
echo   https://github.com/tesladog/sovereign-rmm
echo ============================================================
echo.
echo   Now at home, open Dockge and:
echo     1. New Stack - name it: sovereign-rmm
echo     2. Paste compose.yaml into the compose editor
echo     3. Paste .env into the env editor
echo     4. Set SERVER_IP to your server's local IP
echo     5. Change all CHANGE_THIS values in .env
echo     6. Hit Start!
echo.
pause
exit /b 0

:Check
if not exist "%HERE%%~1" (
    echo     MISSING: %~1
    set /a MISSING+=1
) else (
    echo     OK: %~1
)
goto :eof
