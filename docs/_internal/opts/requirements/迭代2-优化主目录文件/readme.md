### 背景

现在 backtrader 项目的主目录文件过多，需要进行优化

### 任务

1. _bmad, .benchmarks, .claude, .cursor, .idea, .mypy_cache, .pytest_cache, .ruff_cache,  .vscode,  assets 这些文件夹内容是不需要的，后续就不需要同步了，并且考虑从仓库中删除了
2. .pre-commit-config.yaml, .pylintrc, .readthedocs-zh.yaml, .readthedocs.yaml,bandit-report.json, conftest.py,fix_readme.py,optimize_code.sh 这些文件是否还需要，如果不需要就删除了，如果需要，是否可以移动到适合的位置？
