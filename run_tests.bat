@echo off
REM Windows batch script to install package and run pytest
REM Output is logged to test_results.log

setlocal enabledelayedexpansion

REM Set console to UTF-8 for display
chcp 65001 >nul 2>&1

set LOG_FILE=test_results.log
set PYTHON_IOENCODING=utf-8

REM Get timestamp using PowerShell (more reliable)
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"`) do set TIMESTAMP=%%i

echo ============================================ > %LOG_FILE%
echo Test Run Started at: %TIMESTAMP% >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%
echo. >> %LOG_FILE%

echo Installing package...
echo [INSTALL] pip install -U . >> %LOG_FILE%
echo. >> %LOG_FILE%

REM Install package
pip install -U . >> %LOG_FILE% 2>&1
if !errorlevel! neq 0 (
    echo ERROR: Package installation failed! >> %LOG_FILE%
    echo ERROR: Package installation failed!
    exit /b 1
)

echo. >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%
echo Running pytest tests -n 12 >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%
echo. >> %LOG_FILE%

echo Running tests...

REM Run pytest directly
pytest tests -n 12 -v --tb=short >> %LOG_FILE% 2>&1
set PYTEST_EXIT_CODE=!errorlevel!

echo. >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%
echo Test Summary >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%

REM Use PowerShell to extract failed count (more reliable)
for /f "usebackq" %%i in (`powershell -NoProfile -Command "$line = Get-Content '%LOG_FILE%' -Encoding UTF8 | Select-String ' failed.*passed' | Select-Object -Last 1; if ($line -match '(\d+) failed') { $matches[1] } else { '0' }"`) do set FAILED_COUNT=%%i

REM Extract failed test names using PowerShell
powershell -NoProfile -Command "$tests = Get-Content '%LOG_FILE%' -Encoding UTF8 | Select-String 'FAILED tests.*::' | ForEach-Object { if ($_.Line -match 'FAILED\s+(tests\S+)') { $matches[1] } } | Sort-Object -Unique; if ($tests) { 'Failed Test Cases:'; '-------------------'; $tests }" > failed_tests.tmp

echo. >> %LOG_FILE%
echo Total Failed Tests: %FAILED_COUNT% >> %LOG_FILE%
echo. >> %LOG_FILE%

if %FAILED_COUNT% gtr 0 (
    type failed_tests.tmp >> %LOG_FILE%
    echo. >> %LOG_FILE%
)

REM Clean up temp file
if exist failed_tests.tmp del failed_tests.tmp

REM Get end timestamp
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"`) do set END_TIMESTAMP=%%i

echo ============================================ >> %LOG_FILE%
echo Test Run Ended at: %END_TIMESTAMP% >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%

REM Output results to console
echo.
echo ============================================
echo Test Execution Complete
echo ============================================
echo Log file: %LOG_FILE%
echo Failed Tests: %FAILED_COUNT%
echo.

if %FAILED_COUNT% gtr 0 (
    powershell -NoProfile -Command "$tests = Get-Content '%LOG_FILE%' -Encoding UTF8 | Select-String 'FAILED tests.*::' | ForEach-Object { if ($_.Line -match 'FAILED\s+(tests\S+)') { $matches[1] } } | Sort-Object -Unique; if ($tests) { 'Failed Test Cases:'; '-------------------'; $tests }"
    echo.
)

REM Exit with pytest exit code
exit /b %PYTEST_EXIT_CODE%
