@echo off
setlocal
set "ROOT=D:\temp\iteration41-unified-offline-wheelhouse-20260927-v2\ctp-build-unique\b\source\source-a"
set "OUT=D:\temp\i41outb"
set "TEMP=D:\temp\i41svb"
set "TMP=D:\temp\i41svb"
set "STATUS=D:\temp\iteration41-unified-offline-wheelhouse-20260927-v2\ctp-build-unique\b\build-status.txt"
set "LOG=D:\temp\iteration41-unified-offline-wheelhouse-20260927-v2\ctp-build-unique\b\build.log"
set "PYTHONPATH=D:\temp\iteration41-g4-lifecycle-r2-repro-probe-20260927\native-guard"
set "G4_CTP_NATIVE_GUARD_LOG=D:\temp\iteration41-unified-offline-wheelhouse-20260927-v2\ctp-build-unique\b\native-import-blocked.jsonl"
> "%STATUS%" echo run_id=unified-g4r2-settlement-unique-b
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x86_amd64 > "D:\temp\iteration41-unified-offline-wheelhouse-20260927-v2\ctp-build-unique\b\vcvarsall.log" 2>&1
if errorlevel 1 (>> "%STATUS%" echo vcvarsall_exit=nonzero & exit /b 21)
>> "%STATUS%" echo vcvarsall_exit=0
where cl.exe > "D:\temp\iteration41-unified-offline-wheelhouse-20260927-v2\ctp-build-unique\b\tool-paths.txt" 2>&1
if errorlevel 1 (>> "%STATUS%" echo where_cl_exit=nonzero & exit /b 22)
where link.exe >> "D:\temp\iteration41-unified-offline-wheelhouse-20260927-v2\ctp-build-unique\b\tool-paths.txt" 2>&1
if errorlevel 1 (>> "%STATUS%" echo where_link_exit=nonzero & exit /b 23)
set "SOURCE_DATE_EPOCH=1790420787"
set "PYTHONHASHSEED=0"
set "PYTHONUTF8=1"
set "TZ=UTC"
set "PIP_NO_INDEX=1"
set "PIP_CONFIG_FILE=NUL"
set "CL=/Brepro"
set "LINK=/Brepro"
"C:\Anaconda3\python.exe" -m pip wheel --no-deps --no-build-isolation --no-cache-dir --no-index --wheel-dir "%OUT%" "%ROOT%" > "%LOG%" 2>&1
if errorlevel 1 (>> "%STATUS%" echo pip_wheel_exit=nonzero & exit /b 31)
>> "%STATUS%" echo pip_wheel_exit=0
exit /b 0
