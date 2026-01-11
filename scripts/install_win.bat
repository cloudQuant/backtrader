@echo off
:: 切换到上一级目录
echo Switching to the parent directory...
cd ..

:: 设置路径变量
SET PACKAGE_NAME=backtrader
SET BACKTRADER_PATH=./%PACKAGE_NAME%
SET BUILD_DIR=build
SET EGG_INFO_DIR=%PACKAGE_NAME%.egg-info
SET BENCHMARKS_DIR=.benchmarks

:: 安装 requirements.txt 中的依赖
echo Installing dependencies from requirements.txt...
:: pip install -U -r ./%PACKAGE_NAME%/requirements.txt
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to install dependencies. Please check the requirements.txt file.
    exit /b 1
)

:: 安装指定的包
echo Installing the %PACKAGE_NAME% package...
pip install -U --no-build-isolation  %BACKTRADER_PATH%
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to install the %PACKAGE_NAME% package.
    exit /b 1
)

:: 删除中间构建和 egg-info 目录
echo Deleting intermediate files...
cd %PACKAGE_NAME%
IF EXIST %BUILD_DIR% (
    rmdir /s /q %BUILD_DIR%
    echo Deleted %BUILD_DIR% directory.
)
IF EXIST %EGG_INFO_DIR% (
    rmdir /s /q %EGG_INFO_DIR%
    echo Deleted %EGG_INFO_DIR% directory.
)

:: 运行 %PACKAGE_NAME% 测试用例，使用 4 个进程并行测试
echo Running %PACKAGE_NAME% tests...
:: pytest tests -n 4
cd tests
pytest --ignore=crypto_tests . -n 8 --timeout=30
:: python tests/crypto_tests/test_binance_ma.py
:: python tests/crypto_tests/test_base_funding_rate.py
:: python tests/crypto_tests/test_data_strategy.py
:: python tests\crypto_tests\test_data_ma.py"
cd ..
IF %ERRORLEVEL% NEQ 0 (
    echo Test cases failed.
    exit /b 1
)

:: 删除 pytest 生成的 .benchmarks 目录
IF EXIST %BENCHMARKS_DIR% (
    rmdir /s /q %BENCHMARKS_DIR%
    echo Deleted %BENCHMARKS_DIR% directory.
)

:: Delete all .log files
echo Deleting all .log files...
del /s /q *.log
echo All .log files deleted.

:: Delete the "logs" folder and its contents if it exists
echo Deleting logs folder if it exists...
rd /s /q logs
echo logs folder deleted if it existed.
echo All .log files deleted.

:: 脚本完成
echo Script execution completed!

:: 暂停以查看输出
:: pause



