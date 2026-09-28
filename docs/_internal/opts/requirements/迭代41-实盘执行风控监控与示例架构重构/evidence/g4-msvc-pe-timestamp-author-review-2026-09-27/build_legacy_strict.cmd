@echo off
setlocal DisableDelayedExpansion
set "ROOT=D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927"
set "LABEL=c"
set "SRC=%ROOT%\source-c"
set "OUT=%ROOT%\wheelhouse-c"
set "LOG=%ROOT%\logs\build-c-legacy-strict.log"
set "PYTHON=%ROOT%\build-tool-venv-65\Scripts\python.exe"
set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
set "TEMP=%ROOT%\temp-c"
set "TMP=%ROOT%\temp-c"
set "PIP_CACHE_DIR=%ROOT%\pip-cache-c"
set "PIP_NO_INDEX=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_NO_CACHE_DIR=1"
set "PIP_CONFIG_FILE=NUL"
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "PYTHONHASHSEED=0"
set "PYTHONHOME="
set "PYTHONPATH=%ROOT%\guard"
set "G4_QA_GUARD_LOG=%ROOT%\logs\guard-c.jsonl"
set "CL="
set "LINK="
set "SOURCE_DATE_EPOCH="
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%OUT%" mkdir "%OUT%"
call "%VCVARS%" > "%ROOT%\logs\vcvars64-c.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
where cl.exe > "%ROOT%\logs\where-cl-c.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
where link.exe > "%ROOT%\logs\where-link-c.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
"%PYTHON%" -m pip --version > "%ROOT%\logs\pip-version-c.log" 2>&1
pushd "%SRC%"
"%PYTHON%" -m pip wheel -v --no-index --no-deps --no-build-isolation --no-cache-dir --wheel-dir "%OUT%" . > "%LOG%" 2>&1
set "BUILD_EXIT=%ERRORLEVEL%"
popd
echo BUILD_EXIT=%BUILD_EXIT%
exit /b %BUILD_EXIT%
