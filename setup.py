import sys
import numpy as np
from setuptools import setup, find_packages, Extension


def set_optimize_option(optimize_arg: int) -> str:
    if sys.platform == 'win32':
        return f'/O{optimize_arg}'
    elif sys.platform == 'linux':
        return f'-O{optimize_arg}'
    elif sys.platform == 'darwin':
        return f'-O{optimize_arg}'
    else:
        return f'-O{optimize_arg}'


def set_compile_args(compile_arg: str) -> str:
    if sys.platform == 'win32':
        return f'/{compile_arg}'
    elif sys.platform == 'linux':
        return f'-f{compile_arg}'
    elif sys.platform == 'darwin':
        return f'-O{compile_arg}'
    else:
        return f'-O{compile_arg}'


def set_extra_link_args(link_arg: str) -> str:
    if sys.platform == 'win32':
        return f'/{link_arg}'
    elif sys.platform == 'linux':
        return f'-{link_arg}'
    elif sys.platform == 'darwin':
        return f'-D{link_arg}'
    else:
        return f'-{link_arg}'


def set_cpp_version(cpp_version: str) -> str:
    if sys.platform == 'win32':
        return f'-std:{cpp_version}'
    elif sys.platform == 'linux':
        return f'-std={cpp_version}'
    elif sys.platform == 'darwin':
        return f'-std={cpp_version}'
    else:
        return f'-std={cpp_version}'


# # 定义扩展模块
# extensions = [
#     Extension(
#         name='backtrader.utils.cal_performance_indicators.cal_metrics',  # 模块名称
#         sources=['backtrader/utils/cal_performance_indicators/performance_pointer.pyx'],  # 源文件列表
#         include_dirs=[np.get_include(), 'backtrader/utils/cal_performance_indicators'],
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
#         name='backtrader.utils.cs_cal_value.cal_total_value_cython',  # 模块名称
#         sources=['backtrader/utils/cs_cal_value/cal_by_cython.pyx'],  # 源文件列表
#         include_dirs=[np.get_include(), 'backtrader/utils/cs_cal_value'],
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
#         name='backtrader.utils.cs_long_short_signals.cal_long_short_signals',  # 模块名称
#         sources=['backtrader/utils/cs_long_short_signals/cal_by_cython.pyx'],  # 源文件列表
#         include_dirs=[np.get_include(), "backtrader/utils/cs_long_short_signals"],
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
#         name='backtrader.utils.ts_cal_value.cal_value_by_cython',  # 模块名称
#         sources=['backtrader/utils/ts_cal_value/cal_by_cython.pyx'],  # 源文件列表
#         include_dirs=[np.get_include(), 'backtrader/utils/ts_cal_value'],
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
#     # 添加其他扩展模块
# ]

extensions = []

# Read requirements from requirements.txt
def read_requirements():
    """Read requirements from requirements.txt file"""
    try:
        with open('requirements.txt', 'r', encoding='utf-8') as f:
            requirements = []
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    requirements.append(line)
            return requirements
    except FileNotFoundError:
        # Fallback minimal requirements
        return [
            'matplotlib',
            'pandas',
            'numpy>=1.26.4',
            'python-dateutil',
            'pytz',
            'cython',
            'setuptools'
        ]

# Read long description safely
def read_long_description():
    """Read long description from README.md"""
    try:
        with open('README.md', encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Enhanced backtrader library with Cython optimizations"

setup(
    name='backtrader',  # 项目的名称
    version='0.1.0',  # 版本号
    packages=find_packages(exclude=['strategies', 'studies', 'tests']),
    package_data={
        'backtrader': ['**/*.pyx', '**/*.pxd', '**/*.hpp', '**/*.cpp'],
    },
    author='cloudQuant',  # 作者名字
    author_email='yunjinqi@qq.com',  # 作者邮箱
    description='Enhanced backtrader library with Cython optimizations',  # 项目描述
    long_description=read_long_description(),  # 项目长描述（一般是 README 文件内容）
    long_description_content_type='text/markdown',  # 长描述的内容类型
    url='https://gitee.com/yunjinqi/backtrader.git',  # 项目的 URL
    install_requires=read_requirements(),  # 项目所需的依赖项列表
    ext_modules=extensions,  # 添加扩展模块
    python_requires='>=3.8',  # 最低Python版本要求
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Financial and Insurance Industry',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Topic :: Office/Business :: Financial :: Investment',
    ],  # 项目的分类器列表
    zip_safe=False,  # 不使用zip安全模式，因为有Cython扩展
)