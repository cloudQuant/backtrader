@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
if errorlevel 1 exit /b %errorlevel%
set DISTUTILS_USE_SDK=1
set MSSdk=1
set PYTHONUTF8=1
set PYTHONPATH=
"C:\anaconda3\python.exe" -m pip wheel --no-deps --no-build-isolation --wheel-dir "D:\temp\i51-ctp-nojoin-wheel-20261027-r1\wheelhouse" "D:\temp\i51-ctp-nojoin-wheel-20261027-r1\source"
exit /b %errorlevel%
