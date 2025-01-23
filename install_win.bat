@echo off
:: 安装 requirements.txt 中的依赖
pip install -U -r requirements.txt

:: 切换到上一级目录
cd ..

:: 安装 backtrader 包
pip install -U ./backtrader

:: 运行 backtrader 的测试用例，使用 4 个进程并行测试
pytest ./backtrader/tests -n 4

:: 暂停脚本，以便查看输出结果
pause