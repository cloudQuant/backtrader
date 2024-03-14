import numpy as np
import sys
import Cython.Compiler.Options as Cco
from backtrader.utils import (set_extra_link_args,
                              set_compile_args,
                              set_cpp_version,
                              set_optimize_option)
from setuptools import setup, Extension
from Cython.Build import cythonize

Cco.annotate = True

# -O3 -march=native
ext = Extension(
    "calculation_by_cython", sources=["cal_by_cython.pyx"],
    include_dirs=[np.get_include()],
    language='c++',
    extra_compile_args=[
                set_optimize_option(2),
                # set_compile_args('openmp'),
                # set_compile_args('lpthread'),
                set_cpp_version('c++17'),
                # "-march=native"
    ],
    extra_link_args=[
        set_extra_link_args('lgomp'),
    ]
)

setup(name="cal_return_sharpe_drawdown", ext_modules=cythonize([ext]))
