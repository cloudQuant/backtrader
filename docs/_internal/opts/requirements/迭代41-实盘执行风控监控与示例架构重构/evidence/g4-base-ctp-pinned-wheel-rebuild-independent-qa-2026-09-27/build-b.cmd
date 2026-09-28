@echo off
setlocal DisableDelayedExpansion
set "ROOT=D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927"
set "BUILD=%1"
set "PYTHON=D:\c41sdkf_audit\install-venv\Scripts\python.exe"
set "VSCMD=C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
set "TEMP=%ROOT%\build-b\tmp"
set "TMP=%ROOT%\build-b\tmp"
set "PIP_CACHE_DIR=%ROOT%\build-b\pip-cache"
set "PIP_NO_INDEX=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_NO_CACHE_DIR=1"
set "PIP_CONFIG_FILE=NUL"
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "GIT_TERMINAL_PROMPT=0"
set "PYTHONPATH=%ROOT%\guard"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
call "%VSCMD%" -arch=x64 -host_arch=x64 -no_logo > "%ROOT%\logs\build-b-vsdevcmd.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
where cl.exe > "%ROOT%\logs\build-b-where-cl.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
where link.exe > "%ROOT%\logs\build-b-where-link.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
set "G4_QA_GUARD_LOG=%ROOT%\logs\build-b-guard.jsonl"
pushd "%ROOT%\build-b\src\base"
"%PYTHON%" -m pip wheel --no-index --no-deps --no-build-isolation --no-cache-dir --wheel-dir "%ROOT%\build-b\wheelhouse" . > "%ROOT%\logs\build-b-base-build.log" 2>&1
set "BASE_EXIT=%ERRORLEVEL%"
popd
if not "%BASE_EXIT%"=="0" exit /b %BASE_EXIT%
pushd "%ROOT%\build-b\src\ctp"
"%PYTHON%" -m pip wheel --no-index --no-deps --no-build-isolation --no-cache-dir --wheel-dir "%ROOT%\build-b\wheelhouse" . > "%ROOT%\logs\build-b-ctp-build.log" 2>&1
set "CTP_EXIT=%ERRORLEVEL%"
popd
if not "%CTP_EXIT%"=="0" exit /b %CTP_EXIT%
echo BASE_EXIT=%BASE_EXIT% CTP_EXIT=%CTP_EXIT%
exit /b 0
