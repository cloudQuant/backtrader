"""Setup configuration for backtrader package."""

from pathlib import Path

from setuptools import find_packages, setup


BASE_DIR = Path(__file__).resolve().parent
ABOUT = {}
exec((BASE_DIR / "backtrader" / "version.py").read_text(encoding="utf-8"), ABOUT)
README = (BASE_DIR / "README.md").read_text(encoding="utf-8")

setup(
    name="backtrader",  # Project name
    version=ABOUT["__version__"],  # Version number
    packages=find_packages(exclude=["strategies", "studies"]),
    # package_data={'bt_alpha': ['bt_alpha/utils/*', 'utils/*']},
    author="cloud",  # Author name
    author_email="yunjinqi@qq.com",  # Author email
    description="Python Algorithmic Trading Backtesting Framework",  # Project description
    long_description=README,  # Long description (usually README file content)
    long_description_content_type="text/markdown",  # Long description content type
    url="https://github.com/cloudQuant/backtrader",  # Project URL
    install_requires=[
        # numpy: pin <2.0 on Python <3.13 because the strategy regression tests
        # assert exact order/trade counts calibrated on numpy 1.x (numpy 2.x
        # alters reduction/sort/dtype numerics that drift a few counts). Python
        # 3.13 has no numpy 1.x wheels (1.26.x source builds segfault on
        # win/py3.13), so 3.13 uses numpy>=2.1 which has 3.13 wheels and on which
        # the regression suite also passes.
        "numpy>=1.20.0,<2.0.0; python_version < '3.13'",
        "numpy>=2.1.0; python_version >= '3.13'",
        "pytz>=2021.1",
        "pandas>=1.3.0",
        "matplotlib>=3.3.0",
        "scipy>=1.5.0",
        "statsmodels>=0.12.0",
    ],
    extras_require={
        "dev": [
            "pytest",
            "pytest-xdist",
            "pytest-html",
            "pytest-timeout",
            "pytest-asyncio",
            "ruff",
            "black",
            "isort",
            # Plotting dependencies for tests
            "plotly",
            "seaborn",
            "dash",
            "bokeh",
            "pyecharts",
            "mysql-connector-python",
            "python-dotenv",
            "websockets",
            "aiohttp",
        ],
        "plotting": [
            "plotly",
            "bokeh",
            "dash",
            "pyecharts",
        ],
    },  # List of project dependencies
    python_requires=">=3.8",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],  # Project classifiers list
)
