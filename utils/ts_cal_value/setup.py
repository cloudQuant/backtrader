import numpy as np
import Cython.Compiler.Options
from setuptools import setup, Extension
from Cython.Build import cythonize
from backtrader.utils import (set_extra_link_args,
                              set_compile_args,
                              set_cpp_version,
                              set_optimize_option)

Cython.Compiler.Options.annotate = True

ext = Extension(
    "calculation_by_cython", sources=["cal_by_cython.pyx"],
    include_dirs=[np.get_include()],
    language='c++',
    extra_compile_args=[
        set_optimize_option(2),
        # set_compile_args('openmp'),
        # set_compile_args('lpthread'),
        set_cpp_version('c++11')
    ],
    extra_link_args=[
        set_extra_link_args('lgomp'),
    ]
)

setup(name="my_cython_module", ext_modules=cythonize([ext]))
