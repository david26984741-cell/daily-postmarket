@echo off
cd /d "%~dp0"
where git >nul 2>nul || (echo Git not found. Install from https://git-scm.com/download/win then double-click again. & pause & exit /b 1)
rmdir /s /q .git 2>nul
git init
git config user.email "david26984741@gmail.com"
git config user.name "david26984741-cell"
git add -A
git commit -m "initial commit"
git branch -M main
git remote remove origin 2>nul
git remote add origin https://github.com/david26984741-cell/daily-postmarket.git
git push -u origin main
echo.
echo ============================================
echo  If you see "Writing objects: 100%%" above = SUCCESS
echo  If you see red errors, screenshot and send to Claude
echo ============================================
pause
