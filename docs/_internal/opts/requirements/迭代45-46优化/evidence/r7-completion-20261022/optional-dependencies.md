# R7 可选依赖边界

默认 `import backtrader.research` 原先会经根包的 PyFolio、CryptoHFTData、OLS 和 contrib 线性回归叶子模块提前加载 pandas。将这些叶子的 pandas/NumPy 导入移至真正使用函数；OLS 还移除触发类定义期导入的 `packages/frompackages` 冗余声明，保留现有函数内 statsmodels 懒导入。公共类与计算语句不变，没有修改 clock、minperiod 或引擎推进。

依赖探针同时覆盖默认和 `BACKTRADER_LIGHT_IMPORT=1`，分别阻断 pandas、fincore、二者，并检查 research/全 101 registry 可导入；真正构造面板、评价或报告时缺依赖返回 typed `DependencyError(code="DEPENDENCY_UNAVAILABLE")`。NumPy 是本仓声明依赖，不在无依赖探针承诺内。

独立命令：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest tests/unit/test_factor_optional_dependencies.py tests/unit/test_factor_report.py tests/unit/analyzers/test_analyzer_pyfolio.py tests/unit/analyzers/test_pyfolio_master_compatibility.py tests/unit/feeds/test_cryptohftdata.py tests/unit/indicators/test_ind_ols.py tests/functional/strategies/trend_following/test_0318_1287_linear_reg_slope_v2.py -q
```

34 passed，14.90 秒，见 `optional-dependencies-regression.txt`。首次命令误写不存在的 `test_ols.py` 在收集前退出，记录在 `optional-dependencies-command-error.txt`，不计为执行通过。
