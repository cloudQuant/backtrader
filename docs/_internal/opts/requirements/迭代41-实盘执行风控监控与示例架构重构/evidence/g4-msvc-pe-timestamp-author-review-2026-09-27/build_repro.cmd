@echo off
setlocal DisableDelayedExpansion
set "ROOT=D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927"
set "LABEL=%1"
set "SRC=%ROOT%\source-%LABEL%"
set "OUT=%ROOT%\wheelhouse-%LABEL%"
set "LOG=%ROOT%\logs\build-%LABEL%.log"
set "PYTHON=%ROOT%\build-tool-venv\Scripts\python.exe"
set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
set "TEMP=%ROOT%\temp-%LABEL%"
set "TMP=%ROOT%\temp-%LABEL%"
set "PIP_CACHE_DIR=%ROOT%\pip-cache-%LABEL%"
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
set "G4_QA_GUARD_LOG=%ROOT%\logs\guard-%LABEL%.jsonl"
set "SOURCE_DATE_EPOCH=1790261514"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%OUT%" mkdir "%OUT%"
call "%VCVARS%" > "%ROOT%\logs\vcvars64-%LABEL%.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
set "CL=/Brepro"
set "LINK=/Brepro"
where cl.exe > "%ROOT%\logs\where-cl-%LABEL%.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
where link.exe > "%ROOT%\logs\where-link-%LABEL%.log" 2>&1
if errorlevel 1 exit /b %ERRORLEVEL%
cl /Bv > "%ROOT%\logs\cl-version-%LABEL%.log" 2>&1
pushd "%SRC%"
"%PYTHON%" -m pip wheel -v --no-index --no-deps --no-build-isolation --no-cache-dir --wheel-dir "%OUT%" . > "%LOG%" 2>&1
set "BUILD_EXIT=%ERRORLEVEL%"
popd
echo BUILD_EXIT=%BUILD_EXIT%
exit /b %BUILD_EXIT%

