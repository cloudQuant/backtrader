@echo off
REM =============================================================================
REM Enhanced Test Runner Script for Backtrader (Windows)
REM =============================================================================
REM Description: Run pytest with parallel execution, timeout, and colored output
REM Usage: run_tests.bat [options]
REM Options:
REM   -n NUM    Number of parallel workers (default: 8)
REM   -t SEC    Timeout per test in seconds (default: 45)
REM   -p PATH   Test path (default: tests)
REM   -k EXPR   Only run tests matching expression
REM   -v        Verbose output
REM   -h        Show this help
REM =============================================================================

setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

REM Default configuration
set WORKERS=8
set TIMEOUT=45
set TEST_PATH=tests
set VERBOSE=
set FILTER=
set LOG_FILE=test_results.log

REM Parse command line arguments
:parse_args
if "%~1"=="" goto :done_args
if "%~1"=="-n" (
    set WORKERS=%~2
    shift
    shift
    goto :parse_args
)
if "%~1"=="-t" (
    set TIMEOUT=%~2
    shift
    shift
    goto :parse_args
)
if "%~1"=="-p" (
    set TEST_PATH=%~2
    shift
    shift
    goto :parse_args
)
if "%~1"=="-k" (
    set FILTER=-k %~2
    shift
    shift
    goto :parse_args
)
if "%~1"=="-v" (
    set VERBOSE=-v
    shift
    goto :parse_args
)
if "%~1"=="-h" (
    echo Usage: run_tests.bat [options]
    echo Options:
    echo   -n NUM    Number of parallel workers (default: 8)
    echo   -t SEC    Timeout per test in seconds (default: 45)
    echo   -p PATH   Test path (default: tests)
    echo   -k EXPR   Only run tests matching expression
    echo   -v        Verbose output
    echo   -h        Show this help
    exit /b 0
)
shift
goto :parse_args
:done_args

REM Clean up old temp directories that may cause permission issues
REM Use cmd for cleanup (more reliable on Windows)
rd /s /q .pytest_tmp 2>nul
rd /s /q .pytest_cache 2>nul
rd /s /q "%TEMP%\pytest-of-%USERNAME%" 2>nul

REM Generate unique basetemp directory name to avoid conflicts
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "[int](Get-Date -UFormat %%s)"`) do set TIMESTAMP=%%i
set BASETEMP=.pytest_tmp_%TIMESTAMP%

REM Get start time
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"`) do set START_TIME=%%i
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "[int](Get-Date -UFormat %%s)"`) do set START_SEC=%%i

REM Print header
echo ============================================================
echo Backtrader Test Runner
echo ============================================================
echo Test Path:    %TEST_PATH%
echo Workers:      %WORKERS%
echo Timeout:      %TIMEOUT%s per test
echo Filter:       %FILTER%
echo ============================================================

REM Log header
echo ============================================ > %LOG_FILE%
echo Test Run Started at: %START_TIME% >> %LOG_FILE%
echo Workers: %WORKERS%, Timeout: %TIMEOUT%s >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%

REM Run pytest
echo.
echo Running tests...
echo.

python -m pytest %TEST_PATH% -n %WORKERS% --timeout=%TIMEOUT% --timeout-method=thread --tb=short --disable-warnings -q --basetemp=%BASETEMP% %VERBOSE% %FILTER% 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%LOG_FILE%' -Append"

REM Clean up the temp directory after tests
rd /s /q %BASETEMP% 2>nul

set PYTEST_EXIT_CODE=%errorlevel%

REM Get end time and calculate duration
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"`) do set END_TIME=%%i
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "[int](Get-Date -UFormat %%s)"`) do set END_SEC=%%i
set /a DURATION=%END_SEC%-%START_SEC%

REM Extract statistics using PowerShell
for /f "usebackq" %%i in (`powershell -NoProfile -Command "$c = Get-Content '%LOG_FILE%' -Raw; if ($c -match '(\d+) passed') { $matches[1] } else { '0' }"`) do set PASSED_COUNT=%%i
for /f "usebackq" %%i in (`powershell -NoProfile -Command "$c = Get-Content '%LOG_FILE%' -Raw; if ($c -match '(\d+) failed') { $matches[1] } else { '0' }"`) do set FAILED_COUNT=%%i
for /f "usebackq" %%i in (`powershell -NoProfile -Command "(Get-Content '%LOG_FILE%' | Select-String 'Timeout >' | Measure-Object).Count"`) do set TIMEOUT_COUNT=%%i

REM Print summary
echo.
echo ============================================================
echo Test Summary
echo ============================================================
echo Duration:     %DURATION%s
echo Exit Code:    %PYTEST_EXIT_CODE%
echo ------------------------------------------------------------
echo Passed:       %PASSED_COUNT%
echo Failed:       %FAILED_COUNT%
echo Timeout:      %TIMEOUT_COUNT%
echo ------------------------------------------------------------

if %PYTEST_EXIT_CODE%==0 (
    echo Status:       ALL TESTS PASSED
) else if %PYTEST_EXIT_CODE%==1 (
    echo Status:       SOME TESTS FAILED
) else if %PYTEST_EXIT_CODE%==2 (
    echo Status:       TEST EXECUTION INTERRUPTED
) else if %PYTEST_EXIT_CODE%==5 (
    echo Status:       NO TESTS COLLECTED
) else (
    echo Status:       ERROR (code: %PYTEST_EXIT_CODE%)
)

REM Show failed tests if any
if %FAILED_COUNT% gtr 0 (
    echo.
    echo ============================================================
    echo Failed Tests:
    echo ============================================================
    powershell -NoProfile -Command "Get-Content '%LOG_FILE%' | Select-String 'FAILED.*::' | ForEach-Object { '  ' + $_.Line }"
)

REM Show timeout tests if any
if %TIMEOUT_COUNT% gtr 0 (
    echo.
    echo ============================================================
    echo Timeout Tests (^>%TIMEOUT%s):
    echo ============================================================
    powershell -NoProfile -Command "Get-Content '%LOG_FILE%' | Select-String 'Timeout >' -Context 5,0 | ForEach-Object { $_.Context.PreContext | Select-String '::test_' } | ForEach-Object { '  ' + $_.Line } | Sort-Object -Unique"
)

echo ============================================================
echo Log file: %LOG_FILE%
echo ============================================================

REM Append summary to log
echo. >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%
echo Test Run Ended at: %END_TIME% >> %LOG_FILE%
echo Duration: %DURATION%s >> %LOG_FILE%
echo Passed: %PASSED_COUNT%, Failed: %FAILED_COUNT%, Timeout: %TIMEOUT_COUNT% >> %LOG_FILE%
echo ============================================ >> %LOG_FILE%

exit /b %PYTEST_EXIT_CODE%
