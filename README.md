# backtrader

#### 介绍
使用cython\numba\numpy提高backtrader的回测效率



#### 安装教程
如果使用的是anaconda创建的虚拟环境，可以参考下面的方法
1.  cd ./anaconda3/envs/backtrader_cython/lib/python3.7/site-packages/
2.  git clone https://gitee.com/quant-yunjinqi/backtrader.git




#### 使用说明

使用方法参考backtrader系列教程：https://blog.csdn.net/qq_26948675/category_10220116.html

#### 相关改动

记录从2022年之后对backtrader的改动

- [x]    2022-12-1  修改plot中drowdown的拼写错误，改为drawdown
- [x]    2022-11-21 修改了comminfo.py中的getsize函数，把下单的时候取整数给去掉了，如果要下整数，在策略里面自己取整去控制
- [x]    2022-11-8 给data增加了name属性，使得data.name = data._name,方便写策略的时候规范调用
