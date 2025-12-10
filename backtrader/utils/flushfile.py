#!/usr/bin/env python

import sys


# 这个类按照字面意思来看，应该是输出的时候刷新，让输出立即显示，但是看这个类的使用，好像并没有起到这个作用
# 只有在btrun文件中import这个文件，import backtrader.utils.flushfile，import的时候会直接判断这个系统
# 是不是win32,如果是win32就用flushfile创建两个实例，初始化的时候使用sys.stdout，sys.stderr这两个方法
# 实际上看起来，并没有起到什么作用。就跟py3的文件一样，可能是为了起到兼容的作用，但是现在谁还用python2呀，几乎很少了
# 所以整个框架看起来冗余了不少的函数和类
class flushfile:
    def __init__(self, f):
        self.f = f

    def write(self, x):
        self.f.write(x)
        self.f.flush()

    def flush(self):
        self.f.flush()


if sys.platform == "win32":
    sys.stdout = flushfile(sys.stdout)
    sys.stderr = flushfile(sys.stderr)


# 没有用到的类，看类型的话，应该是输出的
class StdOutDevNull:
    def __init__(self):
        self.stdout = sys.stdout
        sys.stdout = self

    def write(self, x):
        pass

    def flush(self):
        pass

    def stop(self):
        sys.stdout = self.stdout
