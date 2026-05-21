# PandasData 与 PandasDirectData 用法对比

`PandasData` 和 `PandasDirectData` 都定义在：

```text
backtrader/feeds/pandafeed.py
```

它们都用于把 `pandas.DataFrame` 接入 Backtrader 的数据源系统，最终都会填充标准 lines：

- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `openinterest`

## 共同点

- **数据源都是 DataFrame**

  两者都通过 `dataname=df` 传入 Pandas DataFrame。

- **接入 Cerebro 的方式类似**

  ```python
  data = bt.feeds.PandasData(dataname=df)
  cerebro.adddata(data)
  ```

  或：

  ```python
  data = bt.feeds.PandasDirectData(dataname=df)
  cerebro.adddata(data)
  ```

- **策略中的使用方式一致**

  添加到 Cerebro 后，策略里都可以用同样的方式访问数据：

  ```python
  self.data.close[0]
  self.data.open[0]
  self.data.datetime.datetime(0)
  ```

- **都需要可转换的 datetime**

  两者最终都会把时间转换成 Backtrader 内部使用的 float date number。

## 核心区别

| 对比项 | `PandasData` | `PandasDirectData` |
|---|---|---|
| 读取方式 | 按 DataFrame 列名或列位置读取 | 用 `DataFrame.itertuples()` 逐行读取 |
| 默认 datetime | 默认来自 DataFrame index | 默认来自 `itertuples()` 的第 0 个元素，也就是 DataFrame index |
| 列映射 | 支持列名、列序号、自动识别 | 只支持 tuple 位置索引 |
| 自动匹配列名 | 支持，默认忽略大小写 | 不支持 |
| 自定义列名 | 很方便 | 必须手动计算 tuple 位置 |
| 对普通用户友好度 | 更高 | 更底层，更依赖 DataFrame 结构 |
| 当前项目实现 | 有 `to_numpy(copy=False)` 和 datetime 预计算优化 | 简单使用 `itertuples()` 迭代 |

## PandasData 的用法

### datetime 在 index 中

如果 DataFrame 使用 `DatetimeIndex`，并且列名是标准 OHLCV 名称：

```text
index(datetime) | open | high | low | close | volume | openinterest
```

可以直接使用：

```python
data = bt.feeds.PandasData(dataname=df)
```

这是最常见、也最推荐的用法。

### datetime 在普通列中

如果 DataFrame 是：

```text
date | open | high | low | close | volume
```

可以指定 datetime 列：

```python
data = bt.feeds.PandasData(
    dataname=df,
    datetime="date",
)
```

### 自定义列名

如果 DataFrame 的列名不是标准名称，例如：

```text
Open | High | Low | Close | Vol | OI
```

可以手动映射：

```python
data = bt.feeds.PandasData(
    dataname=df,
    open="Open",
    high="High",
    low="Low",
    close="Close",
    volume="Vol",
    openinterest="OI",
)
```

### 参数含义

`PandasData` 的参数更灵活。

对于 `datetime`：

- **`None`**：使用 DataFrame index 作为时间。
- **`-1`**：自动查找名为 `datetime` 的列。
- **字符串**：使用指定列名，例如 `datetime="date"`。
- **整数**：使用指定 DataFrame 列位置，例如 `datetime=0`。

对于 `open`、`high`、`low`、`close`、`volume`、`openinterest`：

- **`-1`**：自动按列名匹配，例如 `open` 可以匹配 `open` 或 `Open`。
- **`None`**：表示该字段不存在。
- **字符串**：指定列名。
- **整数**：指定 DataFrame 列位置。

## PandasDirectData 的用法

`PandasDirectData` 使用：

```python
df.itertuples()
```

`itertuples()` 默认会把 DataFrame index 放在 tuple 的第 0 个位置。

如果 DataFrame 是：

```text
index(datetime) | open | high | low | close | volume | openinterest
```

那么每一行 tuple 类似：

```python
(Index, open, high, low, close, volume, openinterest)
```

默认参数正好是：

```python
datetime=0
open=1
high=2
low=3
close=4
volume=5
openinterest=6
```

因此可以直接使用：

```python
data = bt.feeds.PandasDirectData(dataname=df)
```

### datetime 是普通列时的注意点

如果 DataFrame 是：

```text
RangeIndex | datetime | open | high | low | close | volume | openinterest
```

`itertuples()` 产生的 tuple 是：

```python
(Index, datetime, open, high, low, close, volume, openinterest)
```

此时需要手动指定位置：

```python
data = bt.feeds.PandasDirectData(
    dataname=df,
    datetime=1,
    open=2,
    high=3,
    low=4,
    close=5,
    volume=6,
    openinterest=7,
)
```

这里最容易踩坑的是：

- `PandasData(datetime=0)` 表示 DataFrame 的第 0 个列。
- `PandasDirectData(datetime=1)` 才表示 `itertuples()` 里的第 1 个元素，也就是 DataFrame 的第 0 个列。
- 因为 `itertuples()` 的第 0 个元素默认是 DataFrame index。

## 什么时候用哪个

### 推荐优先使用 PandasData

`PandasData` 适合大多数场景：

- **列名标准或接近标准**
- **datetime 在 index 或某个列里**
- **需要按列名映射**
- **列名大小写不统一**
- **希望代码可读性更好**
- **不想手动计算 tuple 位置**

示例：

```python
data = bt.feeds.PandasData(
    dataname=df,
    datetime="date",
    open="Open",
    high="High",
    low="Low",
    close="Close",
    volume="Volume",
)
```

### PandasDirectData 适合结构非常固定的 DataFrame

`PandasDirectData` 适合：

- **DataFrame 列顺序完全固定**
- **清楚 `itertuples()` 的位置结构**
- **datetime 在 index 中**
- **想使用更直接的 tuple 读取方式**

标准结构下可以很短：

```python
data = bt.feeds.PandasDirectData(dataname=df)
```

但一旦 datetime 是普通列，就必须手动考虑 index 占位带来的偏移。

## 当前项目实现上的补充

`PandasData` 在当前项目中有额外优化：

- **预先把 DataFrame 转成 numpy array**
- **预先计算 datetime 数值**
- **加载时直接按数组索引取值**

因此它不仅更灵活，在当前实现中也是更偏主力的 Pandas 数据接入方式。

`PandasDirectData` 的实现更简单：

- **`start()` 中创建 `self._rows = df.itertuples()`**
- **`_load()` 中调用 `next(self._rows)`**
- **然后按整数位置从 tuple 中取值**

## 简短结论

- **`PandasData` 是推荐默认选择**：支持列名、自动匹配、datetime index 或 datetime column、自定义映射，使用更安全。
- **`PandasDirectData` 是位置驱动的轻量版本**：依赖 `itertuples()` 的 tuple 位置，DataFrame 结构必须非常明确。
- **最大区别在映射方式**：

  ```text
  PandasData       -> DataFrame 列名 / 列位置
  PandasDirectData -> itertuples() 产生的 tuple 位置
  ```

- **最容易踩坑的是 datetime 列**：

  如果 datetime 在 index 中，两者默认都好用。

  如果 datetime 在普通列中：

  - `PandasData` 用 `datetime="date"` 或 `datetime=0`。
  - `PandasDirectData` 要考虑 index 占了 tuple 第 0 位，通常要写 `datetime=1`、`open=2`、`high=3` 等。
