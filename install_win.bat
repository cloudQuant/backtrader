@echo off
SETLOCAL

:: 切换到上一级目录
echo Switching to the parent directory...
cd ..
:: 检查 pyfolio 0.9.6 版本是否已经安装
pip show pyfolio | findstr "Version: 0.9.6"
IF %ERRORLEVEL% NEQ 0 (
    echo pyfolio 0.9.6 not found. Checking if pyfolio directory exists...

    :: 检查当前目录是否存在 pyfolio 文件夹
    IF NOT EXIST pyfolio (
        echo pyfolio directory does not exist. Cloning pyfolio from Gitee...
        git clone https://gitee.com/yunjinqi/pyfolio
        IF %ERRORLEVEL% NEQ 0 (
            echo Failed to clone pyfolio repository. Exiting...
            exit /b 1
        )
    ) ELSE (
        echo pyfolio directory already exists. Skipping git clone.
    )

    :: 运行 pyfolio 文件夹下的 install_win.bat 安装 pyfolio
    echo Running install_win.bat for pyfolio...
    call .\pyfolio\install_win.bat
    IF %ERRORLEVEL% NEQ 0 (
        echo Failed to run install_win.bat for pyfolio. Exiting...
        exit /b 1
    )
) ELSE (
    echo pyfolio 0.9.6 is already installed.
)

:: 设置路径变量
SET BACKTRADER_PATH=./backtrader
SET BUILD_DIR=build
SET EGG_INFO_DIR=backtrader.egg-info
SET BENCHMARKS_DIR=.benchmarks

:: 安装 requirements.txt 中的依赖
echo Installing dependencies from requirements.txt...
pip install -U -r ./backtrader/requirements.txt
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to install dependencies. Please check the requirements.txt file.
    exit /b 1
)


IF %ERRORLEVEL% NEQ 0 (
    echo Failed to switch directory.
    exit /b 1
)

:: 安装 backtrader 包
echo Installing the backtrader package...
pip install -U --no-build-isolation  %BACKTRADER_PATH%
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to install the backtrader package.
    exit /b 1
)

:: 删除中间构建和 egg-info 目录
echo Deleting intermediate files...
cd backtrader
IF EXIST %BUILD_DIR% (
    rmdir /s /q %BUILD_DIR%
    echo Deleted %BUILD_DIR% directory.
)
IF EXIST %EGG_INFO_DIR% (
    rmdir /s /q %EGG_INFO_DIR%
    echo Deleted %EGG_INFO_DIR% directory.
)

:: 运行 backtrader 测试用例，使用 4 个进程并行测试
echo Running backtrader tests...
:: pytest tests -n 4
:: pytest --ignore=tests/crypto_tests tests -n 8
:: python tests/crypto_tests/test_binance_ma.py
:: python tests/crypto_tests/test_base_funding_rate.py
:: python tests/crypto_tests/test_data_strategy.py
python tests\crypto_tests\test_data_ma.py"

IF %ERRORLEVEL% NEQ 0 (
    echo Test cases failed.
    exit /b 1
)

:: 删除 pytest 生成的 .benchmarks 目录
IF EXIST %BENCHMARKS_DIR% (
    rmdir /s /q %BENCHMARKS_DIR%
    echo Deleted %BENCHMARKS_DIR% directory.
)

:: 删除所有 .log 文件
echo Deleting all .log files...
del /s /q *.log
echo All .log files deleted.

:: 脚本完成
echo Script execution completed!

:: 暂停以查看输出
:: pause


