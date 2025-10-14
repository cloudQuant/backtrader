# Backtrader 安装指南

## 重要提示

本项目对 backtrader 进行了多项修复和增强。为确保使用项目中修复后的版本，请按照以下步骤正确安装。

## 问题场景

如果您遇到以下错误：

```
TypeError: 'int' object is not subscriptable
File "D:\anaconda3\Lib\site-packages\backtrader\..."
```

这说明您正在使用 **pip安装在site-packages中的旧版本**，而不是项目本地修复后的版本。

## 安装方法

### 方法一：开发模式安装（推荐）

这是最推荐的方式，会创建一个链接指向项目目录，任何对项目的修改都会立即生效：

```bash
# 在项目根目录下执行
pip install -e . --no-deps

# 或者如果需要同时更新依赖
pip install -e .
```

**优点**：
- 修改代码立即生效，无需重新安装
- 适合开发和调试
- 使用项目最新的修复

### 方法二：直接安装

从项目目录直接安装：

```bash
# 卸载旧版本
pip uninstall backtrader -y

# 安装项目版本
cd F:\source_code\backtrader
pip install .
```

### 方法三：从源码运行（不推荐）

在每个脚本中设置PYTHONPATH：

```python
import sys
sys.path.insert(0, 'F:/source_code/backtrader')
import backtrader as bt
```

**缺点**：
- 需要在每个文件中添加
- 容易遗漏
- 不够优雅

## 验证安装

安装后，运行以下命令验证使用的是正确的版本：

```bash
python -c "import backtrader; print(f'backtrader location: {backtrader.__file__}'); print(f'backtrader version: {backtrader.__version__}')"
```

**正确的输出应该是**：
```
backtrader location: F:\source_code\backtrader\backtrader\__init__.py
backtrader version: 1.9.76.123
```

**错误的输出**（使用了site-packages中的旧版本）：
```
backtrader location: D:\anaconda3\Lib\site-packages\backtrader\__init__.py
backtrader version: 1.9.76.123
```

## 常见问题

### Q1: 为什么需要使用项目本地版本？

**A**: 本项目对原版backtrader进行了多项重要修复：

1. **ExtendPandasFeed 列索引修复**：
   - 修复了DataFrame使用set_index后列索引错位的问题
   - 修复了stdstats=True时的IndexError错误

2. **indicators 模块优化**：
   - 添加了完整的__all__导出列表
   - 解决了PyCharm中的"Unresolved reference"警告

3. **文档完善**：
   - 详细的使用说明
   - 修复记录和最佳实践

### Q2: 开发模式安装后能否移动项目？

**A**: 不能。开发模式（`pip install -e .`）创建的是符号链接，如果移动项目目录，需要重新安装：

```bash
# 先卸载
pip uninstall backtrader

# 在新位置重新安装
pip install -e .
```

### Q3: 如何在虚拟环境中使用？

**A**: 推荐使用虚拟环境：

```bash
# 创建虚拟环境
conda create -n backtrader python=3.11
conda activate backtrader

# 安装依赖
pip install -r requirements.txt

# 安装项目
pip install -e .
```

### Q4: 多个项目如何共享？

**A**: 有两种方式：

1. **每个项目使用独立虚拟环境**（推荐）：
```bash
# 项目A
conda create -n project_a python=3.11
conda activate project_a
cd /path/to/backtrader
pip install -e .

# 项目B
conda create -n project_b python=3.11
conda activate project_b
cd /path/to/backtrader
pip install -e .
```

2. **共享一个虚拟环境**：
```bash
# 创建共享环境
conda create -n trading python=3.11
conda activate trading
cd /path/to/backtrader
pip install -e .
```

## 卸载

如果需要卸载项目版本并恢复使用PyPI版本：

```bash
# 卸载项目版本
pip uninstall backtrader

# 安装PyPI版本（如果需要）
pip install backtrader
```

**注意**：PyPI版本没有本项目的修复和增强功能。

## 依赖管理

### 安装所有依赖

```bash
pip install -r requirements.txt
```

### 仅安装运行时依赖

```bash
pip install -e . --no-deps
pip install matplotlib pandas numpy plotly python-dateutil pytz
```

### 安装测试依赖

```bash
pip install pytest pytest-xdist pytest-cov pytest-sugar
```

## 开发工作流

### 日常开发

```bash
# 1. 激活环境
conda activate backtrader

# 2. 修改代码（无需重新安装）
# 编辑 backtrader/ 下的文件

# 3. 运行测试
pytest tests/

# 4. 运行策略
python strategies/your_strategy.py
```

### 更新依赖

```bash
# 更新requirements.txt中的包
pip install -U -r requirements.txt

# 重新安装项目（如果有新依赖）
pip install -e .
```

## 项目特定修复

### ExtendPandasFeed 使用

确保使用修复后的版本：

```python
import backtrader as bt
import pandas as pd

class ExtendPandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),  # ✅ 修复：datetime是索引
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
        ('custom_field', 5),  # 扩展字段
    )
    lines = ('custom_field',)

# DataFrame准备
df = pd.read_csv('data.csv')
df = df.set_index('datetime')  # ✅ 修复后支持set_index

# 使用数据源
cerebro = bt.Cerebro(stdstats=True)  # ✅ 修复后可以使用stdstats=True
feed = ExtendPandasFeed(dataname=df)
cerebro.adddata(feed)
cerebro.run()
```

## 故障排除

### 问题1：仍然使用旧版本

**症状**：
```python
import backtrader
print(backtrader.__file__)
# 输出：D:\anaconda3\Lib\site-packages\backtrader\__init__.py
```

**解决**：
```bash
# 强制卸载
pip uninstall backtrader -y
pip uninstall backtrader -y  # 再次执行确保完全卸载

# 重新安装
pip install -e .

# 验证
python -c "import backtrader; print(backtrader.__file__)"
```

### 问题2：ImportError

**症状**：
```
ImportError: cannot import name 'XXX' from 'backtrader'
```

**解决**：
```bash
# 清理Python缓存
find . -type d -name "__pycache__" -exec rm -rf {} +
# Windows PowerShell:
Get-ChildItem -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force

# 重新安装
pip install -e . --force-reinstall
```

### 问题3：测试失败

**症状**：
```
pytest tests/ 报错
```

**解决**：
```bash
# 确保使用项目版本
pip install -e .

# 安装测试依赖
pip install pytest pytest-xdist pytest-cov

# 运行测试
pytest tests/
```

## 最佳实践

1. **总是使用虚拟环境**：避免与系统Python冲突
2. **开发模式安装**：`pip install -e .` 方便开发
3. **定期验证**：确保使用正确的版本
4. **记录环境**：导出依赖列表 `pip freeze > requirements.lock`
5. **测试先行**：修改代码后运行测试

## 相关文档

- [EXTENDED_FEED_FIX.md](EXTENDED_FEED_FIX.md) - ExtendPandasFeed修复说明
- [CHANGELOG.md](CHANGELOG.md) - 更新日志
- [CLAUDE.md](../CLAUDE.md) - 开发者文档
- [README.md](../README.md) - 项目文档

---

**更新日期**：2024-10-14  
**适用版本**：backtrader 1.9.76.123

