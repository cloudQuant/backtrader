# backtrader

#### 介绍
基于backtrader打造最好用的量化投研工具(中低频为主,后续改写成cpp版本后支持高频交易)
1. 当前版本是master版本，和官方主流的backtrader对齐，仅增加了部分功能，修改了部分bug, 没有功能上的改进，可以运行我csdn专栏专栏里面的策略。这个版本仅用于修复bug。
2. 最新版本是dev分支，主要是为了实现一些新的功能，会新增加一些功能，尝试把底层代码改成c++，支持tick级别的测试等，等dev完善之后，后续会逐步合并到master分支。
#### 安装教程
```markdown
# 安装python3.11, python3.11有性能上的提升，并且很多包都已经支持，下面是anaconda的一些镜像，仅供参考
# win：https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Windows-x86_64.exe
# mac m系列: https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-MacOSX-arm64.sh
# ubuntu:https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Linux-x86_64.sh

# 克隆项目
git clone https://gitee.com/yunjinqi/backtrader.git
# 安装依赖项
pip install -r ./backtrader/requirements.txt
# 编译cython文件并进行安装, mac和 ubuntu下使用下面指令。有一个只能在windows上才能编译成功，会报错，忽略就好
cd ./backtrader/backtrader && python -W ignore compile_cython_numba_files.py && cd .. && cd .. && pip install -U ./backtrader/
# 编译cython文件并进行安装, windows下使用下面指令
cd ./backtrader/backtrader; python -W ignore compile_cython_numba_files.py; cd ..; cd ..; pip install -U ./backtrader/
# 运行测试
pytest ./backtrader/tests -n 4
```

#### 使用说明

1. [参考官方的文档和论坛](https://www.backtrader.com/)
2. [参考我在csdn的付费专栏](https://blog.csdn.net/qq_26948675/category_10220116.html)
3. ts和cs的使用说明：https://yunjinqi.blog.csdn.net/article/details/130507409
4. 网络上也有很多的backtrader的学习资源，大家可以百度


