@echo off
REM Sync script to push to GitHub repository

echo Syncing with GitHub repository...

REM Add GitHub remote if it doesn't exist
git remote add github https://github.com/cloudQuant/backtrader.git 2>nul

REM Get current branch
for /f "tokens=*" %%i in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%i

REM Push to GitHub
echo Pushing branch %BRANCH% to GitHub...
git push github %BRANCH% --force

REM Push tags
echo Pushing tags to GitHub...
git push github --tags --force

echo Sync completed!
pause