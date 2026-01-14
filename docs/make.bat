@ECHO OFF
pushd %~dp0

REM Command file for Sphinx documentation

if "%SPHINXBUILD%" == "" (
	set SPHINXBUILD=sphinx-build
)
set SOURCEDIR=source
set BUILDDIR=_build

if "%1" == "" goto help
if "%1" == "help" goto help
if "%1" == "html" goto html
if "%1" == "html-zh" goto html-zh
if "%1" == "html-all" goto html-all
if "%1" == "clean" goto clean
if "%1" == "apidoc" goto apidoc
goto default

:help
echo Backtrader Documentation Build System
echo.
echo Available targets:
echo   html        Build English HTML documentation
echo   html-zh     Build Chinese HTML documentation
echo   html-all    Build both English and Chinese documentation
echo   clean       Remove build directory
echo   apidoc      Generate API documentation from source code
goto end

:html
echo Building English documentation...
%SPHINXBUILD% -b html %SOURCEDIR% %BUILDDIR%\html\en
echo.
echo English documentation built at %BUILDDIR%\html\en\index.html
goto end

:html-zh
echo Building Chinese documentation...
%SPHINXBUILD% -b html %SOURCEDIR% %BUILDDIR%\html\zh -D language=zh_CN
echo.
echo Chinese documentation built at %BUILDDIR%\html\zh\index.html
goto end

:html-all
call :html
call :html-zh
echo.
echo All documentation built successfully!
goto end

:clean
rmdir /s /q %BUILDDIR% 2>NUL
echo Build directory cleaned.
goto end

:apidoc
echo Generating API documentation...
sphinx-apidoc -f -o %SOURCEDIR%\api ..\backtrader --separate
echo.
echo API documentation generated at %SOURCEDIR%\api
goto end

:default
%SPHINXBUILD% -b %1 %SOURCEDIR% %BUILDDIR%\%1

:end
popd
