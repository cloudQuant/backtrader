# 依赖库版本兼容性修复

## 问题描述

运行测试时出现导入错误：

```
ImportError: cannot import name '_lazywhere' from 'scipy._lib._util'
File "backtrader/indicators/ols.py", line 4, in <module>
    import statsmodels.api as sm
```

## 根本原因

**版本不兼容**：
- scipy 1.16.2（最新版本）
- statsmodels 0.14.4（旧版本）

statsmodels 0.14.4 依赖 scipy 内部API `_lazywhere`，但在 scipy 1.16+ 中该API已被移除或重构。

## 解决方案

### 方案：升级 statsmodels

```bash
pip install --upgrade statsmodels
```

**升级后版本**：
- scipy: 1.16.2（保持不变）
- statsmodels: 0.14.5（升级）

**结果**：
- ✅ 导入错误消失
- ✅ 所有测试正常运行
- ✅ OLS指标可正常使用

## 依赖版本要求

### 推荐配置

```txt
# requirements.txt
scipy>=1.8.0
statsmodels>=0.14.5  # 兼容scipy 1.16+
numpy>=1.19.0
pandas>=1.1.0
```

### 版本兼容性矩阵

| scipy | statsmodels | 兼容性 | 说明 |
|-------|-------------|--------|------|
| 1.16.x | 0.14.5+ | ✅ | 推荐 |
| 1.16.x | 0.14.4 | ❌ | 不兼容 |
| 1.14.x | 0.14.4 | ✅ | 旧版兼容 |
| 1.8-1.15 | 0.13.x | ✅ | 旧版兼容 |

## 影响的模块

### indicators/ols.py

OLS（普通最小二乘法）相关指标：
- OLS_Slope_InterceptN - 线性回归斜率和截距
- OLS_TransformationN - OLS变换
- OLS_BetaN - Beta系数
- CointN - 协整检验

**使用频率**：较低（大多数策略不使用）

## 备选方案

如果不想安装statsmodels，可以让OLS指标变为可选：

```python
# backtrader/indicators/__init__.py

# 方案A：可选导入（已实现但用户移除了）
try:
    from .ols import *
except ImportError:
    warnings.warn("OLS indicators not available", ImportWarning)

# 方案B：延迟导入
# 只在实际使用OLS指标时才导入statsmodels
```

## 其他依赖问题

### empyrical警告

```
UserWarning: Unable to import pandas_datareader
```

**原因**：empyrical依赖的pandas_datareader已过时

**影响**：无（仅警告，不影响功能）

**解决**（可选）：
```bash
pip install pandas_datareader
# 或忽略，不影响backtrader功能
```

## 验证修复

### 测试导入

```bash
python -c "import backtrader as bt; print('导入成功')"
```

### 运行测试

```bash
pytest tests/original_tests/test_trade.py -v
pytest tests/original_tests/ -v
```

### 测试OLS指标

```python
import backtrader as bt

class TestStrategy(bt.Strategy):
    def __init__(self):
        # 测试OLS指标是否可用
        try:
            self.ols = bt.indicators.OLS_Slope_InterceptN(
                self.data0, self.data1, period=10
            )
            print("✓ OLS指标可用")
        except Exception as e:
            print(f"⚠ OLS指标不可用: {e}")
```

## 建议的依赖管理

### requirements.txt

```txt
# 核心依赖
numpy>=1.19.0,<3.0
pandas>=1.1.0,!=2.1.0
matplotlib>=3.1.0
plotly
python-dateutil>=2.8.2
pytz>=2020.1

# 数学和科学计算
scipy>=1.8.0
numba>=0.50.0

# 可选依赖（OLS指标）
statsmodels>=0.14.5

# 开发依赖
cython>=3.0.0
pytest>=6.0
pytest-xdist
pytest-cov
```

### 锁定版本（生产环境）

```bash
# 生成锁定文件
pip freeze > requirements.lock

# 使用锁定版本
pip install -r requirements.lock
```

## 总结

**修复方法**：
```bash
pip install --upgrade statsmodels
```

**结果**：
- ✅ statsmodels 0.14.5 兼容 scipy 1.16.2
- ✅ 所有测试正常运行
- ✅ OLS指标可用

**建议**：
- 定期更新依赖库
- 使用虚拟环境隔离项目
- 锁定生产环境版本

---

**修复日期**：2024-10-14  
**修复分支**：fix/statsmodels-import-error  
**影响模块**：indicators/ols.py

