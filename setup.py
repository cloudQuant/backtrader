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
    packages=find_packages(
        exclude=[
            "strategies",
            "studies",
            "studies.*",
            "examples",
            "examples.*",
            "tests",
            "tests.*",
            "scripts",
            "scripts.*",
            "docs",
            "docs.*",
        ]
    ),
    # Keep the tracked, credential-free account configuration template available
    # to installed consumers.  The real account_config.yaml is intentionally
    # ignored and is never included in a distribution.
    package_data={
        "backtrader": ["configs/account_config_example.yaml"],
        # Immutable, credential-free data belongs only to the packaged
        # Iteration 41 acceptance fixtures: two fake-provider L2 configs plus
        # one local-backtest config and its tiny historical CSV.  They are not
        # operator config and do not relax the ignored config.yaml rule for
        # examples or live runtimes.
        "backtrader_runtime": [
            "_iteration41_l2_fixture/runtimes/managed_013_3/config.yaml",
            "_iteration41_l2_fixture/runtimes/mechanical_p1b/config.yaml",
            "_iteration41_backtest_fixture/data/bars.csv",
            "_iteration41_backtest_fixture/runtimes/local_backtest/config.yaml",
        ],
    },
    author="cloudQuant",  # Author name (retained from master)
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
        # schema-v4 config.yaml is a required runtime contract for the
        # configuration-first launcher, so its safe YAML parser is not a dev-only
        # dependency.
        "PyYAML>=5.4",
    ],
    extras_require={
        "dev": [
            "pytest>=8.2,<9",
            "pytest-cov",
            "pytest-xdist",
            "pytest-html",
            "pytest-timeout",
            "pytest-asyncio>=0.24,<1",
            "ruff",
            "black",
            "isort",
            # Plotting dependencies for tests
            "plotly",
            "seaborn",
            "dash",
            "bokeh",
            "pyecharts",
            "scikit-learn",
            "hmmlearn>=0.3.3",
            "mysql-connector-python",
            "python-dotenv",
            "psutil",
            "PyYAML",
            "python-docx>=0.8.11",
            "websockets",
            "aiohttp",
            "cryptography>=3.4",
        ],
        "plotting": [
            "plotly",
            "bokeh",
            "dash",
            "pyecharts",
        ],
        "cryptohftdata": ["cryptohftdata>=0.4.0,<1.0.0"],
        "live": ["cryptography>=3.4"],
        # Public OKX shadow observation was verified with this isolated
        # CCXT/aiohttp pair on CPython 3.11; it grants no account or write route.
        "okx-public-shadow": ["ccxt==4.5.83", "aiohttp==3.14.3"],
    },  # List of project dependencies
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "bt-runtime=backtrader_runtime.cli:main",
        ],
    },
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
