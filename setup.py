"""Setup configuration for backtrader package."""

from setuptools import find_packages, setup

setup(
    name="backtrader",  # Project name
    version="1.0.0",  # Version number
    packages=find_packages(exclude=["strategies", "studies"]),
    # package_data={'bt_alpha': ['bt_alpha/utils/*', 'utils/*']},
    author="cloud",  # Author name
    author_email="yunjinqi@qq.com",  # Author email
    description="Python Algorithmic Trading Backtesting Framework",  # Project description
    long_description=open(
        "README.md", encoding="utf-8"
    ).read(),  # Long description (usually README file content)
    long_description_content_type="text/markdown",  # Long description content type
    url="https://gitee.com/yunjinqi/backtrader.git",  # Project URL
    install_requires=[
        # Use flexible numpy version for Python 3.8-3.13 compatibility
        "numpy>=1.20.0,<3.0.0",
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
            "ruff",
            "black",
            "isort",
            # Plotting dependencies for tests
            "plotly",
            "seaborn",
            "dash",
            "bokeh",
            "pyecharts",
        ],
        "plotting": [
            "plotly",
            "bokeh",
            "dash",
            "pyecharts",
        ],
    },  # List of project dependencies
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
