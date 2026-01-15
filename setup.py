"""Setup configuration for backtrader package.

This module configures the build process for the backtrader quantitative trading
framework, including C/Cython extension modules and package dependencies.
"""

import sys

# import numpy as np  # Commented out top-level import to avoid build-time dependency
from setuptools import Extension, find_packages, setup


def get_numpy_include():
    """Get numpy include directory for compilation.

    This function performs lazy import of numpy to avoid build-time dependency
    issues when numpy is not yet installed in the build environment.

    Returns:
        str: Path to numpy include directory, or empty string if numpy not available.
    """
    try:
        import numpy as np

        return np.get_include()
    except ImportError:
        return ""


def set_optimize_option(optimize_arg: int) -> str:
    """Set optimization flag for different platforms.

    Args:
        optimize_arg: Optimization level (typically 0-3).

    Returns:
        str: Platform-specific optimization flag.
    """
    if sys.platform == "win32":
        return f"/O{optimize_arg}"
    elif sys.platform == "linux":
        return f"-O{optimize_arg}"
    elif sys.platform == "darwin":
        return f"-O{optimize_arg}"
    else:
        return f"-O{optimize_arg}"


def set_compile_args(compile_arg: str) -> str:
    """Set compilation argument flag for different platforms.

    Args:
        compile_arg: Compilation argument to format.

    Returns:
        str: Platform-specific compilation flag.
    """
    if sys.platform == "win32":
        return f"/{compile_arg}"
    elif sys.platform == "linux":
        return f"-f{compile_arg}"
    elif sys.platform == "darwin":
        return f"-O{compile_arg}"
    else:
        return f"-O{compile_arg}"


def set_extra_link_args(link_arg: str) -> str:
    """Set linker argument flag for different platforms.

    Args:
        link_arg: Linker argument to format.

    Returns:
        str: Platform-specific linker flag.
    """
    if sys.platform == "win32":
        return f"/{link_arg}"
    elif sys.platform == "linux":
        return f"-{link_arg}"
    elif sys.platform == "darwin":
        return f"-D{link_arg}"
    else:
        return f"-{link_arg}"


def set_cpp_version(cpp_version: str) -> str:
    """Set C++ version standard flag for different platforms.

    Args:
        cpp_version: C++ version string (e.g., 'c++11', 'c++14').

    Returns:
        str: Platform-specific C++ version flag.
    """
    if sys.platform == "win32":
        return f"-std:{cpp_version}"
    elif sys.platform == "linux":
        return f"-std={cpp_version}"
    elif sys.platform == "darwin":
        return f"-std={cpp_version}"
    else:
        return f"-std={cpp_version}"


# # Define extension modules for Cython/C++ compilation
# extensions = [
#     Extension(
#         name='backtrader.utils.cal_performance_indicators.cal_metrics',  # Module name
#         sources=['backtrader/utils/cal_performance_indicators/performance_pointer.pyx'],  # Source file list
#         include_dirs=[get_numpy_include(), 'backtrader/utils/cal_performance_indicators'],  # Use function instead of np.get_include()
#         language='c++',
#         extra_compile_args=[
#             set_optimize_option(2),
#             # set_compile_args('openmp'),
#             # set_compile_args('lpthread'),
#             set_cpp_version('c++11'),
#             # "-march=native"
#         ],
#         extra_link_args=[
#             set_extra_link_args('lgomp'),
#         ]
#     ),
#     Extension(
#         name='backtrader.utils.cs_cal_value.cal_total_value_cython',  # Module name
#         sources=['backtrader/utils/cs_cal_value/cal_by_cython.pyx'],  # Source file list
#         include_dirs=[get_numpy_include(), 'backtrader/utils/cs_cal_value'],  # Use function instead of np.get_include()
#         language='c++',
#         extra_compile_args=[
#             set_optimize_option(2),
#             # set_compile_args('openmp'),
#             # set_compile_args('lpthread'),
#             set_cpp_version('c++11'),
#             # "-march=native"
#         ],
#         extra_link_args=[
#             set_extra_link_args('lgomp'),
#         ]
#     ),
#     Extension(
#         name='backtrader.utils.cs_long_short_signals.cal_long_short_signals',  # Module name
#         sources=['backtrader/utils/cs_long_short_signals/cal_by_cython.pyx'],  # Source file list
#         include_dirs=[get_numpy_include(), "backtrader/utils/cs_long_short_signals"],  # Use function instead of np.get_include()
#         language='c++',
#         extra_compile_args=[
#             set_optimize_option(2),
#             # set_compile_args('openmp'),
#             # set_compile_args('lpthread'),
#             set_cpp_version('c++11'),
#             # "-march=native"
#         ],
#         extra_link_args=[
#             set_extra_link_args('lgomp'),
#         ]
#     ),
#     Extension(
#         name='backtrader.utils.ts_cal_value.cal_value_by_cython',  # Module name
#         sources=['backtrader/utils/ts_cal_value/cal_by_cython.pyx'],  # Source file list
#         include_dirs=[get_numpy_include(), 'backtrader/utils/ts_cal_value'],  # Use function instead of np.get_include()
#         language='c++',
#         extra_compile_args=[
#             set_optimize_option(2),
#             # set_compile_args('openmp'),
#             # set_compile_args('lpthread'),
#             set_cpp_version('c++11'),
#             # "-march=native"
#         ],
#         extra_link_args=[
#             set_extra_link_args('lgomp'),
#         ]
#     ),
#
#     # Add other extension modules
# ]

extensions = []

setup(
    name="backtrader",  # Project name
    version="1.0.0",  # Version number
    packages=find_packages(exclude=["strategies", "studies"]),
    # package_data={'bt_alpha': ['bt_alpha/utils/*', 'utils/*']},
    author="cloud",  # Author name
    author_email="yunjinqi@qq.com",  # Author email
    description="the cpp and cython version of backtrader",  # Project description
    long_description=open(
        "README.md", encoding="utf-8"
    ).read(),  # Long description (usually README file content)
    long_description_content_type="text/markdown",  # Long description content type
    url="https://gitee.com/yunjinqi/backtrader.git",  # Project URL
    install_requires=[
        "numpy>=1.20.0",
        "pytz",
        "pandas",
        "matplotlib",
    ],
    extras_require={
        "dev": [
            "pytest",
            "pytest-xdist",
            "pytest-html",
            "pytest-timeout",
            "ruff",
            "black",
            "isort",
        ],
        "plotting": [
            "plotly",
            "bokeh",
        ],
    },  # List of project dependencies
    ext_modules=extensions,  # Add extension modules
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        # Add other classifiers as needed
    ],  # Project classifiers list
)
