from setuptools import setup, Extension
from Cython.Build import cythonize

import Cython.Compiler.Options
Cython.Compiler.Options.annotate=True

import numpy as np
import sys
from backtrader.utils import (set_extra_link_args,
                              set_compile_args,
                              set_cpp_version,
                              set_optimize_option)


ext = Extension(
    "my_corr", sources=["my_corr.pyx"],
    include_dirs=[np.get_include()],
    language='c',
    extra_compile_args=[
                set_optimize_option(2),
                # set_compile_args('openmp'),
                # set_compile_args('lpthread'),
                # set_cpp_version('c++17')
    ],
    extra_link_args=[
        set_extra_link_args('lgomp'),
    ]
)

setup(name="my_corr", ext_modules=cythonize([ext]))