import sys
import socket
import time
import urllib.request
from setuptools import setup, find_packages, Extension
import os

# Conditionally import numpy
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("WARNING: NumPy not available - some features may be limited")
    # Create dummy np module with empty include_dir attribute
    class DummyNp:
        def __init__(self):
            self.include_dir = []
    np = DummyNp()

def check_internet_connection(timeout=3):
    """Check if internet connection is available using Baidu"""
    try:
        # Try to connect to Baidu
        urllib.request.urlopen('https://www.baidu.com', timeout=timeout)
        return True
    except:
        return False

def is_pip_install():
    """Check if we're being run through pip install"""
    return 'pip' in sys.argv[0] or 'pip-script.py' in sys.argv[0]

def try_download_url(url, timeout=10):
    """Try to download from a URL with timeout"""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except:
        return False

def get_empyrical_url():
    """Get the best available empyrical package URL"""
    github_url = "https://github.com/cloudQuant/empyrical.git"
    gitee_url = "https://gitee.com/yunjinqi/empyrical.git"
    
    # Try GitHub first
    if try_download_url(f"https://github.com/cloudQuant/empyrical"):
        return f"git+{github_url}"
    # Try Gitee if GitHub fails
    elif try_download_url("https://gitee.com/yunjinqi/empyrical"):
        return f"git+{gitee_url}"
    # Return GitHub as fallback
    return f"git+{github_url}"

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

extensions = []

def read_requirements():
    """Read requirements from requirements.txt file"""
    # If running through pip and offline, return minimal requirements
    if is_pip_install() and not check_internet_connection():
        print("\nOffline pip install detected - installation may fail.")
        print("Please use 'python install_offline.py' for offline installation.")
        return []
        
    # Check if internet is available for normal operation
    online_mode = check_internet_connection()
    
    if not online_mode:
        print("\nOffline mode - using minimal dependencies")
        return []
        
    try:
        with open('requirements.txt', 'r', encoding='utf-8') as f:
            requirements = []
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Handle empyrical package specially
                    if 'empyrical' in line:
                        requirements.append(get_empyrical_url())
                    else:
                        requirements.append(line)
            return requirements
    except FileNotFoundError:
        return []

def read_long_description():
    """Read long description from README.md"""
    try:
        with open('README.md', encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Enhanced backtrader library with Cython optimizations"

# Print installation mode message
online_mode = check_internet_connection()
pip_install = is_pip_install()

if pip_install and not online_mode:
    print("\nWARNING: Offline pip install detected!")
    print("This may fail. Please use 'python install_offline.py' instead.")
    setup_kwargs = {
        'install_requires': [],
        'setup_requires': ['setuptools>=42', 'wheel', 'numpy'],
        'python_requires': '>=3.8',
    }
elif online_mode:
    print("\nInstalling in ONLINE mode - will install all dependencies")
    setup_kwargs = {
        'install_requires': read_requirements(),
        'setup_requires': ['setuptools>=42', 'wheel', 'numpy'],
        'python_requires': '>=3.8',
    }
else:
    print("\nInstalling in OFFLINE mode - using minimal dependencies")
    print("Note: Only core functionality will be available. Install additional dependencies when internet is available.")
    setup_kwargs = {
        'install_requires': ['setuptools>=42', 'wheel', 'numpy'],
        'setup_requires': [],
    }

setup(
    name='backtrader',  # 项目的名称
    version='0.2.0',  # 版本号
    packages=find_packages(exclude=['strategies', 'studies', 'tests']),
    package_data={
        'backtrader': ['**/*.py', '**/*.pyx', '**/*.pxd', '**/*.hpp', '**/*.cpp', '**/*.yaml', '**/*.json'],
    },
    include_package_data=True,
    author='cloudQuant',  # 作者名字
    author_email='yunjinqi@qq.com',  # 作者邮箱
    description='Enhanced backtrader library with Cython optimizations',  # 项目描述
    long_description=read_long_description(),  # 项目长描述（一般是 README 文件内容）
    long_description_content_type='text/markdown',  # 长描述的内容类型
    url='https://gitee.com/yunjinqi/backtrader.git',  # 项目的 URL
    ext_modules=extensions,  # 添加扩展模块
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
    **setup_kwargs  # 动态添加依赖相关的参数
)