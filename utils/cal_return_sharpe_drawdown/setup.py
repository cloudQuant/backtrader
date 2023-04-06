from setuptools import setup, Extension
from Cython.Build import cythonize

import Cython.Compiler.Options
Cython.Compiler.Options.annotate=True

import numpy as np
import sys

def setg_optimize_option(arg:str) ->str:
    if sys.platform=='win32':
        return f'/O{arg}'
    elif sys.platform=='linux':
        return f'-O{arg}'
    #if
#def

def set_compile_args(arg:str) -> str:
    if sys.platform=='win32':
        return f'/{arg}'
    elif sys.platform=='linux':
        return f'-f{arg}'
    #if
#def

def set_extra_link_args(arg:str) -> str:
    if sys.platform=='win32':
        return f'/{arg}'
    elif sys.platform=='linux':
        return f'-{arg}'
    #if
#def

def set_cpp_version(ver:str) -> str:
    if sys.platform=='win32':
        return f'-std:{ver}'
    elif sys.platform=='linux':
        return f'-std={ver}'
    #if
#def

#-O3 -march=native
ext = Extension(
    "cal_return_sharpe_drawdown", sources=["cal_return_sharpe_drawdown.pyx"],
    include_dirs=[np.get_include()],
    language='c++',
    extra_compile_args=[
                setg_optimize_option(2),
                set_compile_args('openmp'),
                # set_compile_args('lpthread'),
                set_cpp_version('c++17'),
                # "-march=native"
    ],
    extra_link_args=[
        set_extra_link_args('lgomp'),
    ]
)

setup(name="cal_return_sharpe_drawdown", ext_modules=cythonize([ext]))