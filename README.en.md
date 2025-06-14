# backtrader

#### Introduction
Building the most user-friendly quantitative research and trading tool based on backtrader (mainly for mid-to-low frequency; will later rewrite in C++ to support high-frequency trading).  
1. The current version is the `master` branch, aligned with the official mainstream backtrader. It only includes minor additional features and bug fixes without functional improvements. It can run strategies from my CSDN column. This version is for bug fixes only.  
2. The latest version is the `dev` branch, mainly focused on implementing new features. It introduces some new functions and attempts to rewrite the underlying code in C++ to support tick-level testing. Once the `dev` branch is stable, it will be merged into the `master` branch.

#### Installation Guide
```bash
# Install Python 3.11. Python 3.11 offers performance improvements, and many packages now support it. Below are some Anaconda mirrors for reference:
# Windows: https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Windows-x86_64.exe
# Mac (M-series): https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-MacOSX-arm64.sh
# Ubuntu: https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Linux-x86_64.sh

# Clone the project
git clone https://gitee.com/yunjinqi/backtrader.git
# Install dependencies
pip install -r ./backtrader/requirements.txt
# Compile Cython files and install (for macOS and Ubuntu). Note: One file can only be compiled on Windows; ignore errors for that file.
cd ./backtrader/backtrader && python -W ignore compile_cython_numba_files.py && cd .. && cd .. && pip install -U ./backtrader/
# Compile Cython files and install (for Windows)
cd ./backtrader/backtrader; python -W ignore compile_cython_numba_files.py; cd ..; cd ..; pip install -U ./backtrader/
# Run tests
pytest ./backtrader/tests -n 4
```

#### Usage Instructions

1. [Refer to the official documentation and forum](https://www.backtrader.com/)
2. [Refer to my paid CSDN column](https://blog.csdn.net/qq_26948675/category_10220116.html)
3. Instructions for `ts` and `cs`: https://yunjinqi.blog.csdn.net/article/details/130507409
4. There are many backtrader learning resources online; feel free to search for them.

#### Changelog

Tracking changes to backtrader since 2022:
- [x] **2025-01-25** Removed references to `__future__`; future versions will only support Python 3.
- [x] **2024-03-15** Created a `dev` branch for developing new features, with updates primarily focused on this branch moving forward.
- [x] **2024-03-14** Fixed issues with compiling Cython files.
- [x] **2023-05-05** Implemented `ts` code for writing simple time-series-based strategies, significantly improving backtesting efficiency.
- [x] **2023-03-03** Fixed minor bugs in `cs.py`, `cal_performance.py`, and other files, improving runtime efficiency.
- [x] **2022-12-18** Modified parts of the `ts` and `cs` backtesting framework to avoid certain bugs.
- [x] **2022-12-13** Adjusted formatting in `sharpe.py` for better PEP8 compliance and removed the assignment of `self.ratio`.
- [x] **2022-12-05** Added a pandas-based vectorized single-factor backtesting class. It now allows inheriting specific classes to write alpha and signal strategies for simple backtesting.
- [x] **2022-12-01** Corrected the spelling error in `plot` for `drowdown`, changing it to `drawdown`.
- [x] **2022-11-21** Modified the `getsize` function in `comminfo.py`, removing rounding to integers during order placement. If integer rounding is required, control it within the strategy.
- [x] **2022-11-08** Added a `name` attribute to `data`, enabling `data.name = data._name`, which standardizes calls when writing strategies.



