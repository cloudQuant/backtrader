@echo off
set "TEMP=D:\temp\iteration41-g1-r9-prestarted-inert-custodian-20260927\.tmp"
set "TMP=D:\temp\iteration41-g1-r9-prestarted-inert-custodian-20260927\.tmp"
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >NUL
cl /nologo /std:c++17 /EHsc /O2 /W4 /Fe:r9_custodian.exe r9_custodian.cpp
exit /b %ERRORLEVEL%
