@echo off
cd /d "%~dp0"
where git >nul 2>nul || (echo Git not found. & pause & exit /b 1)
git add -A
git commit -m "fix: TXF code match + TWSE referer/retry"
git pull --rebase origin main
git push origin main
echo.
echo ============================================
echo  If you see "main -> main" above = SUCCESS
echo  If errors, screenshot and send to Claude
echo ============================================
pause
