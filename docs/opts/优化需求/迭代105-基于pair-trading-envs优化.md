### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/pair-trading-envs
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### pair-trading-envs项目简介
pair-trading-envs是一个配对交易强化学习环境，具有以下核心特点：
- **配对交易**: 配对交易策略
- **RL环境**: OpenAI Gym环境
- **协整分析**: 协整关系检验
- **价差交易**: 价差交易模型
- **强化学习**: RL训练支持
- **环境封装**: 交易环境封装

### 重点借鉴方向
1. **RL环境**: 强化学习环境设计
2. **配对交易**: 配对交易实现
3. **Gym接口**: Gym接口实现
4. **状态空间**: 状态空间设计
5. **奖励函数**: 奖励函数设计
6. **价差建模**: 价差建模方法

---

# 分析与设计文档

## 一、框架对比分析

### 1.1 backtrader vs pair-trading-envs 对比

| 维度 | backtrader (原生) | pair-trading-envs |
|------|------------------|-------------------|
| **定位** | 通用回测框架 | 配对交易RL环境 |
| **多资产支持** | 单资产为主 | 配对双资产 |
| **策略类型** | 规则型策略 | RL智能体 + 规则策略 |
| **环境接口** | 无 | Gymnasium标准接口 |
| **状态空间** | 无显式定义 | Dict类型(持仓/区域/zscore) |
| **动作空间** | 无显式定义 | 离散(3)或连续[-1,1] |
| **奖励函数** | 无 | 动作正确性+净值变化 |
| **交易模式** | 单边交易 | 配对对冲交易 |
| **价差分析** | 需手动实现 | 内置zscore指标 |
| **仓位管理** | 简单 | 固定金额/自由金额 |
| **Kelly准则** | 无 | 内置Kelly Criterion |

### 1.2 可借鉴的核心优势

1. **RL环境封装**: 标准Gymnasium接口，支持主流RL算法(Stable-Baselines3、RLlib等)
2. **配对交易模式**: 统计套利交易，市场中性策略
3. **双模式仓位管理**: 固定金额模式(离散动作)和自由金额模式(连续动作)
4. **Zscore指标**: 基于移动平均和标准差的标准化价差
5. **分层奖励设计**: 动作奖励+净值变化+交易成本惩罚
6. **Kelly Criterion**: 基于历史胜率和赔率的仓位优化

---

## 二、需求规格文档

### 2.1 配对交易策略基类

**需求描述**: 创建配对交易策略基类，支持双资产对冲交易。

**功能要求**:
- 双数据源支持(data0, data1)
- 价差计算和zscore标准化
- 基于阈值的入场/出场信号
- Kelly Criterion仓位计算
- 对冲比率设置

**接口定义**:
```python
class PairTradingStrategy(bt.Strategy):
    params = (
        ('open_threshold', 1.6),    # 开仓阈值
        ('close_threshold', 0.4),   # 平仓阈值
        ('period', 30),             # zscore计算周期
        ('hedge_ratio', 1.0),       # 对冲比率
        ('use_kelly', True),        # 使用Kelly准则
        ('fixed_amount', None),     # 固定金额模式
    )
```

### 2.2 强化学习环境适配器

**需求描述**: 提供backtrader到Gymnasium环境的适配器。

**功能要求**:
- 标准Gymnasium接口(reset, step, render, close)
- 可配置的观察空间(离散/连续/混合)
- 可配置的动作空间(离散/连续)
- 奖励函数自定义
- 交易成本模拟

**接口定义**:
```python
class BacktraderGymEnv(gym.Env):
    def reset(self, seed=None) -> Tuple[Obs, Dict]
    def step(self, action) -> Tuple[Obs, float, bool, bool, Dict]
    def render(self) -> None
    def close(self) -> None
```

### 2.3 价差分析模块

**需求描述**: 提供多种价差计算和标准化方法。

**功能要求**:
- 简单价差: price0 - price1
- 比率价差: price0 / price1
- 对数价差: log(price0) - log(price1)
- OLS对冲比率
- Zscore标准化
- 协整检验

**接口定义**:
```python
class SpreadAnalyzer:
    def simple_spread(self, price0, price1) -> np.ndarray
    def ratio_spread(self, price0, price1) -> np.ndarray
    def log_spread(self, price0, price1) -> np.ndarray
    def ols_hedge_ratio(self, price0, price1) -> float
    def zscore(self, spread, period) -> np.ndarray
    def cointegration_test(self, price0, price1) -> Tuple[bool, float]
```

### 2.4 状态构建器

**需求描述**: 构建强化学习的状态表示。

**功能要求**:
- 市场状态: 价格、价差、zscore
- 仓位状态: 当前持仓、持仓比例
- 技术指标: RSI、MACD、ATR等
- 时间信息: 周期、时间特征

**接口定义**:
```python
class StateBuilder:
    def build_state(self, env) -> Dict[str, np.ndarray]
    def get_observation_space(self) -> spaces.Space
```

### 2.5 奖励函数模块

**需求描述**: 提供多种奖励函数设计。

**功能要求**:
- 净值变化奖励
- 动作正确性奖励(基于规则)
- Sharpe比率奖励
- 最大回撤惩罚
- 交易成本惩罚
- 风险调整收益

**接口定义**:
```python
class RewardFunction:
    def pnl_reward(self, prev_value, curr_value) -> float
    def sharpe_reward(self, returns) -> float
    def rule_based_reward(self, position, zone, action) -> float
    def risk_adjusted_reward(self, rewards, drawdown) -> float
```

### 2.6 配对选择工具

**需求描述**: 提供配对资产选择功能。

**功能要求**:
- 协整检验
- 相关性分析
- 行业匹配
- 流动性筛选

**接口定义**:
```python
class PairSelector:
    def find_cointegrated_pairs(self, prices, significance=0.05) -> List[Tuple]
    def correlation_filter(self, prices, min_corr=0.7) -> List[Tuple]
    def sector_filter(self, tickers, sector) -> List[Tuple]
```

---

## 三、详细设计文档

### 3.1 配对交易策略基类

```python
"""
backtrader/(pairtrading/)策略.py

配对交易策略基类实现
"""

import backtrader as bt
import numpy as np
import pandas as pd
from typing import Optional, Tuple


class ZScoreIndicator(bt.Indicator):
    """ZScore指标 - 标准化价差"""

    lines = ('zscore', 'spread', 'mean', 'std')
    params = (('period', 30),)

    def __init__(self):
        # 计算价差
        self.lines.spread = self.data0 - self.data1
        # 计算移动平均
        self.lines.mean = bt.indicators.SMA(self.lines.spread, period=self.p.period)
        # 计算标准差
        self.lines.std = bt.indicators.StandardDeviation(
            self.lines.spread, period=self.p.period
        )
        # 计算zscore
        self.lines.zscore = (self.lines.spread - self.lines.mean) / self.lines.std


class KellyCriterionIndicator(bt.Indicator):
    """Kelly Criterion指标"""

    lines = ('kelly_f',)
    params = (('period', 30),)

    def next(self):
        # 获取历史价差
        spreads = np.array([
            self.data0.price[-i] - self.data1.price[-i]
            for i in range(1, self.p.period + 1)
        ])

        if len(spreads) == 0:
            self.lines.kelly_f[0] = 0
            return

        # 计算胜率
        wins = spreads[spreads > 0]
        losses = spreads[spreads < 0]

        p = len(wins) / len(spreads) if len(spreads) > 0 else 0.5
        q = 1 - p

        # 计算平均盈亏比
        avg_win = wins.mean() if len(wins) > 0 else 1e-5
        avg_loss = -losses.mean() if len(losses) > 0 else 1e-5

        # Kelly公式: f = (p/a - q/b)
        # a: 平均亏损率, b: 平均盈利率
        f = (p / avg_loss - q / avg_win) if avg_loss > 0 else 0
        f = max(0, min(1, f))  # 限制在[0,1]区间

        self.lines.kelly_f[0] = f


class PairTradingStrategy(bt.Strategy):
    """配对交易策略基类

    交易逻辑:
    - 当zscore < -open_threshold: 做多leg0, 做空leg1
    - 当zscore > +open_threshold: 做空leg0, 做多leg1
    - 当|zscore| < close_threshold: 平仓
    """

    params = (
        ('open_threshold', 2.0),      # 开仓阈值
        ('close_threshold', 0.5),     # 平仓阈值
        ('period', 30),               # zscore计算周期
        ('hedge_ratio', 1.0),         # 对冲比率
        ('use_kelly', True),          # 使用Kelly准则
        ('kelly_period', 60),         # Kelly计算周期
        ('fixed_amount', None),       # 固定金额模式
        ('position_size', 0.95),      # 默认仓位比例
        ('stop_loss', None),          # 止损阈值(zscore)
        ('verbose', False),
    )

    # 仓位状态
    POS_SHORT_LEG0 = 0   # 做空leg0, 做多leg1
    POS_FLAT = 1         # 空仓
    POS_LONG_LEG0 = 2    # 做多leg0, 做空leg1

    def __init__(self):
        # 获取两个数据源
        self.data0 = self.datas[0]
        self.data1 = self.datas[1]

        # 计算zscore指标
        self.zscore_ind = ZScoreIndicator(
            self.data0, self.data1,
            period=self.p.period
        )
        self.zscore = self.zscore_ind.zscore

        # 计算Kelly准则(可选)
        if self.p.use_kelly:
            self.kelly = KellyCriterionIndicator(
                self.zscore_ind,
                period=self.p.kelly_period
            )

        # 初始化仓位状态
        self.position_state = self.POS_FLAT
        self.entry_zscore = None

    def _get_position_size(self) -> Tuple[float, float]:
        """计算仓位大小"""
        cash = self.broker.get_cash()

        if self.p.fixed_amount:
            # 固定金额模式
            size0 = self.p.fixed_amount / self.data0.close[0]
            size1 = self.p.fixed_amount / self.data1.close[0]
        else:
            # 比例模式
            kelly_f = self.kelly[0] if self.p.use_kelly else 1.0
            size0 = cash * self.p.position_size * kelly_f / self.data0.close[0]
            size1 = cash * self.p.position_size * kelly_f / self.data1.close[0]

        # 应用对冲比率
        return size0, size1 * self.p.hedge_ratio

    def _check_stop_loss(self) -> bool:
        """检查止损条件"""
        if self.p.stop_loss is None or self.entry_zscore is None:
            return False

        current_zscore = self.zscore[0]

        # 做多leg0, 做空leg1时，zscore继续下跌则止损
        if self.position_state == self.POS_LONG_LEG0:
            if current_zscore < self.entry_zscore - self.p.stop_loss:
                return True
        # 做空leg0, 做多leg1时，zscore继续上涨则止损
        elif self.position_state == self.POS_SHORT_LEG0:
            if current_zscore > self.entry_zscore + self.p.stop_loss:
                return True

        return False

    def next(self):
        current_zscore = self.zscore[0]

        # 检查止损
        if self._check_stop_loss():
            self._close_positions()
            if self.p.verbose:
                print(f'{self.datetime.date()} Stop Loss triggered at zscore={current_zscore:.2f}')
            return

        # 交易逻辑
        if abs(current_zscore) <= self.p.close_threshold:
            # 平仓区域
            if self.position_state != self.POS_FLAT:
                self._close_positions()

        elif current_zscore <= -self.p.open_threshold:
            # zscore过低，做多leg0，做空leg1
            if self.position_state != self.POS_LONG_LEG0:
                self._close_positions()
                self._open_long_leg0()
                self.entry_zscore = current_zscore

        elif current_zscore >= self.p.open_threshold:
            # zscore过高，做空leg0，做多leg1
            if self.position_state != self.POS_SHORT_LEG0:
                self._close_positions()
                self._open_short_leg0()
                self.entry_zscore = current_zscore

    def _open_long_leg0(self):
        """开仓: 做多leg0，做空leg1"""
        size0, size1 = self._get_position_size()

        self.buy(data=self.data0, size=size0)
        self.sell(data=self.data1, size=size1)

        self.position_state = self.POS_LONG_LEG0

        if self.p.verbose:
            print(f'{self.datetime.date()} OPEN LONG Leg0: zscore={self.zscore[0]:.2f}')

    def _open_short_leg0(self):
        """开仓: 做空leg0，做多leg1"""
        size0, size1 = self._get_position_size()

        self.sell(data=self.data0, size=size0)
        self.buy(data=self.data1, size=size1)

        self.position_state = self.POS_SHORT_LEG0

        if self.p.verbose:
            print(f'{self.datetime.date()} OPEN SHORT Leg0: zscore={self.zscore[0]:.2f}')

    def _close_positions(self):
        """平仓所有持仓"""
        if self.position_state == self.POS_FLAT:
            return

        self.close(data=self.data0)
        self.close(data=self.data1)

        if self.p.verbose:
            print(f'{self.datetime.date()} CLOSE: zscore={self.zscore[0]:.2f}, '
                  f'value={self.broker.get_value():.2f}')

        self.position_state = self.POS_FLAT
        self.entry_zscore = None

    def stop(self):
        """策略结束时调用"""
        self._close_positions()

        if self.p.verbose:
            print(f'\n=== Pair Trading Strategy Results ===')
            print(f'Open Threshold: {self.p.open_threshold}')
            print(f'Close Threshold: {self.p.close_threshold}')
            print(f'Period: {self.p.period}')
            print(f'Starting Cash: {self.broker.startingcash:.2f}')
            print(f'Final Value: {self.broker.getvalue():.2f}')
            print(f'Return: {(self.broker.getvalue()/self.broker.startingcash - 1)*100:.2f}%')
```

### 3.2 强化学习环境适配器

```python
"""
backtrader/RL/environment.py

强化学习环境适配器
"""

import backtrader as bt
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from typing import Dict, Tuple, Any, Optional, Callable
from collections import deque


class BacktraderEnv(gym.Env):
    """Backtrader强化学习环境适配器

    将backtrader策略转换为标准Gymnasium环境
    """

    metadata = {'render_modes': ['human']}

    def __init__(
        self,
        strategy_class,
        data_feeds: list,
        cash: float = 100000,
        commission: float = 0.001,
        observation_builder: Optional['ObservationBuilder'] = None,
        reward_function: Optional['RewardFunction'] = None,
        render_mode: Optional[str] = None,
    ):
        super().__init__()

        self.strategy_class = strategy_class
        self.data_feeds = data_feeds
        self.initial_cash = cash
        self.commission = commission
        self.observation_builder = observation_builder
        self.reward_function = reward_function
        self.render_mode = render_mode

        # 内部状态
        self.cerebro: Optional[bt.Cerebro] = None
        self.strategy: Optional[bt.Strategy] = None
        self.current_step = 0
        self.total_steps = 0

        # 历史记录
        self.networth_history = []

        # 初始化环境和空间
        self._setup_environment()
        self._define_spaces()

    def _setup_environment(self):
        """设置backtrader环境"""
        self.cerebro = bt.Cerebro()

        # 添加数据源
        for feed in self.data_feeds:
            self.cerebro.adddata(feed)

        # 设置初始资金
        self.cerebro.broker.setcash(self.initial_cash)

        # 设置佣金
        self.cerebro.broker.setcommission(commission=self.commission)

        # 添加策略
        self.cerebro.addstrategy(self.strategy_class)

        # 运行一次以获取总步数
        # 实际应用中需要更智能的方式
        self.total_steps = len(self.data_feeds[0])

    def _define_spaces(self):
        """定义观察空间和动作空间"""
        if self.observation_builder:
            self.observation_space = self.observation_builder.get_space()
        else:
            # 默认观察空间
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf,
                shape=(10,), dtype=np.float32
            )

        # 默认动作空间: 3个离散动作 (0: 卖出, 1: 持有, 2: 买入)
        self.action_space = spaces.Discrete(3)

    def reset(self, seed: Optional[int] = None) -> Tuple[Dict[str, np.ndarray], Dict]:
        """重置环境"""
        if seed is not None:
            np.random.seed(seed)

        # 重新创建cerebro
        self._setup_environment()

        # 重置状态
        self.current_step = 0
        self.networth_history = [self.initial_cash]

        # 运行到初始状态
        # 这里需要更复杂的逻辑来逐步执行
        observation = self._get_observation()

        return observation, {}

    def step(self, action: np.ndarray) -> Tuple[Dict, float, bool, bool, Dict]:
        """执行一步"""
        prev_value = self.broker.get_value()

        # 执行动作
        self._execute_action(action)

        # 推进时间
        self.current_step += 1

        # 获取新状态
        observation = self._get_observation()

        # 计算奖励
        curr_value = self.broker.get_value()
        reward = self._compute_reward(prev_value, curr_value, action)

        # 检查终止
        terminated = self.current_step >= self.total_steps - 1
        truncated = False

        # 记录历史
        self.networth_history.append(curr_value)

        info = {
            'networth': curr_value,
            'step': self.current_step,
        }

        return observation, reward, terminated, truncated, info

    def _get_observation(self) -> Dict[str, np.ndarray]:
        """获取当前观察"""
        if self.observation_builder:
            return self.observation_builder.build(self)

        # 默认观察
        return {
            'prices': np.array([
                self.data.close[0] for self.data in self.strategy.datas
            ], dtype=np.float32),
            'networth': np.array([self.broker.get_value()], dtype=np.float32),
        }

    def _execute_action(self, action: np.ndarray):
        """执行交易动作"""
        # 根据action执行交易
        # 这里需要与策略配合实现
        pass

    def _compute_reward(self, prev_value: float, curr_value: float,
                       action: np.ndarray) -> float:
        """计算奖励"""
        if self.reward_function:
            return self.reward_function.compute(self, prev_value, curr_value, action)

        # 默认奖励: 净值变化
        return (curr_value - prev_value) / prev_value

    def render(self):
        """渲染环境"""
        if self.render_mode == 'human':
            print(f'Step: {self.current_step}, '
                  f'Networth: {self.networth_history[-1]:.2f}')

    def close(self):
        """关闭环境"""
        self.cerebro = None
        self.strategy = None


class PairTradingEnv(gym.Env):
    """配对交易强化学习环境

    支持两种模式:
    1. 固定金额模式: 离散动作空间
    2. 自由金额模式: 连续动作空间
    """

    metadata = {'render_modes': ['human']}

    def __init__(
        self,
        df,  # 包含close0, close1, spread, zscore列的DataFrame
        mode: str = 'fixed',  # 'fixed' or 'free'
        tc: float = 0.0002,
        cash: float = 1.0,
        fixed_amt: float = 0.1,
        open_threshold: float = 1.6,
        close_threshold: float = 0.4,
        period: int = 30,
        render_mode: Optional[str] = None,
    ):
        super().__init__()

        self.df = df
        self.mode = mode
        self.tc = tc
        self.cash = cash
        self.fixed_amt = fixed_amt
        self.open_threshold = open_threshold
        self.close_threshold = close_threshold
        self.period = period
        self.render_mode = render_mode

        # 内部状态
        self.networth = cash
        self.holdings = np.array([0, 0], dtype=np.float32)  # [leg0, leg1]
        self.trade_step = period
        self.position = 1  # 0: short leg0, 1: flat, 2: long leg0

        # 定义空间
        self._define_spaces()

    def _define_spaces(self):
        """定义观察空间和动作空间"""
        # 观察空间
        self.observation_space = spaces.Dict({
            'zscore': spaces.Box(low=-np.inf, high=np.inf, shape=(1,), dtype=np.float32),
            'zone': spaces.Discrete(5),
        })

        if self.mode == 'fixed':
            # 固定金额模式: 离散动作 (0: short leg0, 1: close, 2: long leg0)
            self.action_space = spaces.Discrete(3)
            self.observation_space.spaces['position'] = spaces.Discrete(3)
        else:
            # 自由金额模式: 连续动作 [-1, 1]
            self.action_space = spaces.Box(low=-1, high=1, shape=(1,), dtype=np.float32)
            self.observation_space.spaces['holdings'] = spaces.Box(
                low=-1, high=1, shape=(1,), dtype=np.float32
            )

    def reset(self, seed: Optional[int] = None) -> Tuple[Dict, Dict]:
        """重置环境"""
        if seed is not None:
            np.random.seed(seed)

        self.networth = self.cash
        self.holdings = np.array([0, 0], dtype=np.float32)
        self.trade_step = self.period
        self.position = 1

        observation = self._get_observation()
        return observation, {}

    def _get_zone(self, zscore: float) -> int:
        """根据zscore确定区域"""
        if zscore > self.open_threshold:
            return 0
        elif zscore > self.close_threshold:
            return 1
        elif zscore < -self.open_threshold:
            return 4
        elif zscore < -self.close_threshold:
            return 3
        else:
            return 2

    def _get_observation(self) -> Dict[str, np.ndarray]:
        """获取当前观察"""
        row = self.df.iloc[self.trade_step]
        zscore = row['zscore']
        zone = self._get_zone(zscore)

        obs = {
            'zscore': np.array([zscore], dtype=np.float32),
            'zone': zone,
        }

        if self.mode == 'fixed':
            obs['position'] = self.position
        else:
            # 计算持仓比例
            price0 = row['close0']
            value0 = self.holdings[0] * price0
            perc = value0 / self.networth if self.networth > 0 else 0
            obs['holdings'] = np.array([perc], dtype=np.float32)

        return obs

    def step(self, action) -> Tuple[Dict, float, bool, bool, Dict]:
        """执行一步"""
        prev_networth = self.networth
        signal = self._get_observation()

        # 执行动作
        self._take_action(action)

        # 更新时间
        self.trade_step += 1

        # 计算净值
        self._update_networth()

        # 获取新观察
        observation = self._get_observation()

        # 计算奖励
        reward = self._compute_reward(signal, prev_networth)

        # 检查终止
        terminated = self.trade_step >= len(self.df)
        truncated = False

        info = {
            'networth': self.networth,
            'holdings': self.holdings.copy(),
        }

        return observation, reward, terminated, truncated, info

    def _take_action(self, action):
        """执行交易动作"""
        row = self.df.iloc[self.trade_step]
        price0 = row['close0']
        price1 = row['close1']

        if self.mode == 'fixed':
            self._take_action_fixed(action, price0, price1)
        else:
            self._take_action_free(action[0], price0, price1)

    def _take_action_fixed(self, action: int, price0: float, price1: float):
        """固定金额模式的动作执行"""
        # 先平仓
        if self.position != 1 and action != self.position:
            v0 = self.holdings[0] * price0
            v1 = self.holdings[1] * price1
            tc = (abs(v0) + abs(v1)) * self.tc
            self.cash += v0 + v1 - tc
            self.holdings = np.array([0, 0], dtype=np.float32)

        # 开新仓
        if action == 0 and self.position != 0:  # short leg0, long leg1
            units0 = self.fixed_amt / price0
            units1 = self.fixed_amt / price1
            self.holdings = np.array([
                -units0 * (1 - self.tc),
                units1 * (1 - self.tc)
            ], dtype=np.float32)
            self.cash -= self.fixed_amt * 2 * (1 - self.tc)

        elif action == 2 and self.position != 2:  # long leg0, short leg1
            units0 = self.fixed_amt / price0
            units1 = self.fixed_amt / price1
            self.holdings = np.array([
                units0 * (1 - self.tc),
                -units1 * (1 - self.tc)
            ], dtype=np.float32)
            self.cash -= self.fixed_amt * 2 * (1 - self.tc)

        self.position = action

    def _take_action_free(self, action: float, price0: float, price1: float):
        """自由金额模式的动作执行"""
        # 计算目标单位
        target_units0 = action * self.networth / price0
        target_units1 = -action * self.networth / price1

        # 计算交易量
        delta0 = target_units0 - self.holdings[0]
        delta1 = target_units1 - self.holdings[1]

        # 计算交易成本
        tc_cost = (abs(delta0 * price0) + abs(delta1 * price1)) * self.tc

        # 执行交易
        self.cash -= (delta0 * price0 + delta1 * price1 + tc_cost)
        self.holdings = np.array([target_units0, target_units1], dtype=np.float32)

    def _update_networth(self):
        """更新净值"""
        row = self.df.iloc[self.trade_step]
        price0 = row['close0']
        price1 = row['close1']

        self.networth = self.cash + self.holdings[0] * price0 + self.holdings[1] * price1

    def _compute_reward(self, signal: Dict, prev_networth: float) -> float:
        """计算奖励"""
        # 净值变化奖励
        pnl_reward = (self.networth - prev_networth) * 100

        # 动作正确性奖励(可选)
        action_reward = 0

        return pnl_reward + action_reward

    def render(self):
        """渲染环境"""
        if self.render_mode == 'human':
            obs = self._get_observation()
            print(f'Step: {self.trade_step}, '
                  f'Zscore: {obs["zscore"][0]:.2f}, '
                  f'Zone: {obs["zone"]}, '
                  f'Networth: {self.networth:.4f}')

    def close(self):
        """关闭环境"""
        if self.render_mode == 'human':
            print(f'Final Networth: {self.networth:.4f}')
```

### 3.3 价差分析模块

```python
"""
backtrader/pairtrading/spread.py

价差分析模块
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional, Union
from statsmodels.tsa.stattools import coint
from scipy import stats
from sklearn.linear_model import LinearRegression


class SpreadAnalyzer:
    """价差分析器

    提供多种价差计算和标准化方法
    """

    def __init__(self, price0: pd.Series, price1: pd.Series):
        """
        Args:
            price0: 第一个资产价格序列
            price1: 第二个资产价格序列
        """
        self.price0 = price0
        self.price1 = price1
        self._validate_prices()

    def _validate_prices(self):
        """验证价格数据"""
        if len(self.price0) != len(self.price1):
            raise ValueError("价格序列长度不一致")
        if (self.price0 <= 0).any() or (self.price1 <= 0).any():
            raise ValueError("价格必须为正数")

    def simple_spread(self) -> pd.Series:
        """简单价差: price0 - price1"""
        return self.price0 - self.price1

    def ratio_spread(self) -> pd.Series:
        """比率价差: price0 / price1"""
        return self.price0 / self.price1

    def log_spread(self) -> pd.Series:
        """对数价差: log(price0) - log(price1)"""
        return np.log(self.price0) - np.log(self.price1)

    def ols_hedge_ratio(
        self,
        window: Optional[int] = None
    ) -> Union[float, pd.Series]:
        """OLS对冲比率

        Args:
            window: 滚动窗口大小，None表示使用全样本

        Returns:
            对冲比率(滚动则返回Series)
        """
        if window is None:
            # 全样本OLS
            X = self.price1.values.reshape(-1, 1)
            y = self.price0.values
            model = LinearRegression(fit_intercept=True).fit(X, y)
            return model.coef_[0]
        else:
            # 滚动OLS
            hedge_ratios = []
            for i in range(window, len(self.price0) + 1):
                X = self.price1.iloc[i-window:i].values.reshape(-1, 1)
                y = self.price0.iloc[i-window:i].values
                model = LinearRegression(fit_intercept=True).fit(X, y)
                hedge_ratios.append(model.coef_[0])

            # 前面用NaN填充
            full_series = pd.Series([np.nan] * (window - 1) + hedge_ratios)
            full_series.index = self.price0.index
            return full_series

    def ols_spread(self, hedge_ratio: Optional[float] = None) -> pd.Series:
        """OLS价差: price0 - hedge_ratio * price1

        Args:
            hedge_ratio: 对冲比率，None则自动计算
        """
        if hedge_ratio is None:
            hedge_ratio = self.ols_hedge_ratio()
        return self.price0 - hedge_ratio * self.price1

    def zscore(
        self,
        spread: Optional[pd.Series] = None,
        period: int = 30,
        rolling: bool = True
    ) -> pd.Series:
        """Zscore标准化

        Args:
            spread: 价差序列，None则使用简单价差
            period: 计算周期
            rolling: 是否使用滚动窗口

        Returns:
            标准化后的zscore序列
        """
        if spread is None:
            spread = self.simple_spread()

        if rolling:
            mean = spread.rolling(window=period).mean()
            std = spread.rolling(window=period).std()
        else:
            mean = spread.expanding().mean()
            std = spread.expanding().std()

        return (spread - mean) / std

    def cointegration_test(
        self,
        trend: str = 'c',
        maxlag: int = 1
    ) -> Tuple[bool, float, float]:
        """协整检验

        Args:
            trend: 趋势类型 ('c': 常数, 'ct': 常数+趋势)
            maxlag: 最大滞后阶数

        Returns:
            (是否协整, t统计量, p值)
        """
        # 使用Engle-Granger两步法
        score, pvalue, _ = coint(
            self.price0,
            self.price1,
            trend=trend,
            maxlag=maxlag
        )

        # p值 < 0.05 则认为存在协整关系
        is_cointegrated = pvalue < 0.05

        return is_cointegrated, score, pvalue

    def correlation(
        self,
        method: str = 'pearson',
        period: Optional[int] = None
    ) -> Union[float, pd.Series]:
        """相关性分析

        Args:
            method: 相关性方法 ('pearson', 'spearman', 'kendall')
            period: 滚动窗口，None表示全样本

        Returns:
            相关系数
        """
        if period is None:
            return self.price0.corr(self.price1, method=method)
        else:
            return self.price0.rolling(period).corr(self.price1)

    def half_life(self, spread: Optional[pd.Series] = None) -> float:
        """计算价差均值回归的半衰期

        使用Ornstein-Uhlenbeck过程估计
        """
        if spread is None:
            spread = self.simple_spread()

        # 计算一阶差分
        lagged_spread = spread.shift(1).dropna()
        delta_spread = spread.diff().dropna()

        # 对齐数据
        lagged_spread = lagged_spread.iloc[1:]
        delta_spread = delta_spread.iloc[1:]

        # 回归: delta_spread = -lambda * lagged_spread + epsilon
        X = lagged_spread.values.reshape(-1, 1)
        y = delta_spread.values
        model = LinearRegression(fit_intercept=False).fit(X, y)

        # lambda = -coef
        lambda_val = -model.coef_[0]

        # 半衰期 = ln(2) / lambda
        if lambda_val > 0:
            half_life = np.log(2) / lambda_val
        else:
            half_life = np.inf

        return half_life

    def hurst_exponent(self, spread: Optional[pd.Series] = None) -> float:
        """计算Hurst指数

        H < 0.5: 均值回归
        H = 0.5: 随机游走
        H > 0.5: 趋势跟踪
        """
        if spread is None:
            spread = self.simple_spread()

        # 计算不同时间间隔的R/S
        max_lag = int(len(spread) / 2)
        lags = range(2, max_lag)

        tau = [np.std(np.subtract(spread.values[lag:], spread.values[:-lag]))
               for lag in lags]

        # 回归 log(R/S) vs log(lag)
        reg = np.polyfit(np.log(lags), np.log(tau), 1)
        hurst = reg[0]

        return hurst


class SpreadCalculator(bt.Indicator):
    """Backtrader价差指标"""

    lines = ('spread',)
    params = (
        ('hedge_ratio', 1.0),
        ('spread_type', 'simple'),  # 'simple', 'ratio', 'log'
    )

    def __init__(self):
        if self.p.spread_type == 'simple':
            self.lines.spread = self.data0 - self.p.hedge_ratio * self.data1
        elif self.p.spread_type == 'ratio':
            self.lines.spread = self.data0 / (self.data1 * self.p.hedge_ratio)
        elif self.p.spread_type == 'log':
            self.lines.spread = bt.If(
                self.data0 > 0,
                bt.math.log(self.data0) - bt.math.log(self.data1) * self.p.hedge_ratio,
                0
            )


class ZScore(bt.Indicator):
    """Backtrader ZScore指标"""

    lines = ('zscore', 'spread', 'mean', 'std')
    params = (('period', 30),)

    def __init__(self):
        # 计算价差
        self.l.spread = self.data0

        # 计算统计量
        self.l.mean = bt.indicators.SMA(self.l.spread, period=self.p.period)
        self.l.std = bt.indicators.StandardDeviation(
            self.l.spread, period=self.p.period
        )

        # 计算zscore
        self.l.zscore = (self.l.spread - self.l.mean) / (self.l.std + 1e-10)
```

### 3.4 状态构建器

```python
"""
backtrader/RL/observers.py

状态构建器和观察空间定义
"""

import numpy as np
import gymnasium as gym
from gymnasium import spaces
from typing import Dict, List, Optional, Any
from backtrader import indicator
import backtrader as bt


class ObservationBuilder:
    """观察构建器基类"""

    def __init__(self):
        self._space = None

    def build(self, env) -> Dict[str, np.ndarray]:
        """构建观察向量

        Args:
            env: RL环境实例

        Returns:
            观察字典
        """
        raise NotImplementedError

    def get_space(self) -> spaces.Space:
        """获取观察空间"""
        if self._space is None:
            raise ValueError("Observation space not defined")
        return self._space


class PairTradingObservationBuilder(ObservationBuilder):
    """配对交易观察构建器"""

    def __init__(
        self,
        include_position: bool = True,
        include_zscore: bool = True,
        include_zone: bool = True,
        include_prices: bool = False,
        include_indicators: bool = False,
        indicator_params: Optional[Dict] = None,
    ):
        super().__init__()

        self.include_position = include_position
        self.include_zscore = include_zscore
        self.include_zone = include_zone
        self.include_prices = include_prices
        self.include_indicators = include_indicators
        self.indicator_params = indicator_params or {}

        self._define_space()

    def _define_space(self):
        """定义观察空间"""
        space_dict = {}

        if self.include_position:
            space_dict['position'] = spaces.Discrete(3)

        if self.include_zscore:
            space_dict['zscore'] = spaces.Box(
                low=-np.inf, high=np.inf, shape=(1,), dtype=np.float32
            )

        if self.include_zone:
            space_dict['zone'] = spaces.Discrete(5)

        if self.include_prices:
            # 价格归一化到[0, 1]
            space_dict['prices'] = spaces.Box(
                low=0, high=1, shape=(2,), dtype=np.float32
            )

        if self.include_indicators:
            # 技术指标
            n_indicators = len(self.indicator_params.get('list', []))
            space_dict['indicators'] = spaces.Box(
                low=-np.inf, high=np.inf, shape=(n_indicators,), dtype=np.float32
            )

        self._space = spaces.Dict(space_dict)

    def build(self, env) -> Dict[str, np.ndarray]:
        """构建观察"""
        obs = {}

        if self.include_position:
            obs['position'] = env.position

        if self.include_zscore:
            row = env.df.iloc[env.trade_step]
            obs['zscore'] = np.array([row['zscore']], dtype=np.float32)

        if self.include_zone:
            row = env.df.iloc[env.trade_step]
            zscore = row['zscore']
            obs['zone'] = self._get_zone(zscore)

        if self.include_prices:
            row = env.df.iloc[env.trade_step]
            # 归一化价格(使用历史最大最小值)
            obs['prices'] = np.array([
                row['close0'], row['close1']
            ], dtype=np.float32)

        if self.include_indicators:
            obs['indicators'] = self._compute_indicators(env)

        return obs

    def _get_zone(self, zscore: float) -> int:
        """根据zscore确定区域"""
        open_th = 1.6  # 默认值
        close_th = 0.4

        if zscore > open_th:
            return 0
        elif zscore > close_th:
            return 1
        elif zscore < -open_th:
            return 4
        elif zscore < -close_th:
            return 3
        else:
            return 2

    def _compute_indicators(self, env) -> np.ndarray:
        """计算技术指标"""
        # 这里可以添加各种技术指标
        # RSI, MACD, ATR等
        return np.array([], dtype=np.float32)


class MultiAssetObservationBuilder(ObservationBuilder):
    """多资产观察构建器"""

    def __init__(
        self,
        n_assets: int,
        lookback: int = 20,
        features: Optional[List[str]] = None,
    ):
        """
        Args:
            n_assets: 资产数量
            lookback: 回看窗口
            features: 特征列表 (['returns', 'volume', 'rsi', ...])
        """
        super().__init__()

        self.n_assets = n_assets
        self.lookback = lookback
        self.features = features or ['returns', 'volume']

        self._define_space()

    def _define_space(self):
        """定义观察空间"""
        # (n_assets, lookback, n_features)
        self._space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(self.n_assets, self.lookback, len(self.features)),
            dtype=np.float32
        )

    def build(self, env) -> np.ndarray:
        """构建观察矩阵"""
        # 这里需要从环境获取历史数据
        # 返回 shape: (n_assets, lookback, n_features)
        return np.zeros((
            self.n_assets,
            self.lookback,
            len(self.features)
        ), dtype=np.float32)


class StateNormalizer:
    """状态归一化器"""

    def __init__(self, method: str = 'minmax'):
        """
        Args:
            method: 归一化方法 ('minmax', 'zscore', 'robust')
        """
        self.method = method
        self.stats = {}

    def fit(self, data: np.ndarray):
        """拟合归一化参数"""
        if self.method == 'minmax':
            self.stats['min'] = data.min(axis=0)
            self.stats['max'] = data.max(axis=0)
        elif self.method == 'zscore':
            self.stats['mean'] = data.mean(axis=0)
            self.stats['std'] = data.std(axis=0)
        elif self.method == 'robust':
            self.stats['median'] = np.median(data, axis=0)
            self.stats['q75'] = np.percentile(data, 75, axis=0)
            self.stats['q25'] = np.percentile(data, 25, axis=0)

    def transform(self, data: np.ndarray) -> np.ndarray:
        """转换数据"""
        if self.method == 'minmax':
            return (data - self.stats['min']) / (
                self.stats['max'] - self.stats['min'] + 1e-10
            )
        elif self.method == 'zscore':
            return (data - self.stats['mean']) / (self.stats['std'] + 1e-10)
        elif self.method == 'robust':
            iqr = self.stats['q75'] - self.stats['q25']
            return (data - self.stats['median']) / (iqr + 1e-10)

        return data

    def fit_transform(self, data: np.ndarray) -> np.ndarray:
        """拟合并转换"""
        self.fit(data)
        return self.transform(data)
```

### 3.5 奖励函数模块

```python
"""
backtrader/RL/rewards.py

奖励函数模块
"""

import numpy as np
from typing import Dict, Optional, Callable
from collections import deque


class RewardFunction:
    """奖励函数基类"""

    def compute(
        self,
        env,
        prev_value: float,
        curr_value: float,
        action: np.ndarray,
    ) -> float:
        """计算奖励

        Args:
            env: RL环境
            prev_value: 前一时刻净值
            curr_value: 当前净值
            action: 执行的动作

        Returns:
            奖励值
        """
        raise NotImplementedError


class PnLReward(RewardFunction):
    """简单盈亏奖励"""

    def __init__(self, scale: float = 100.0):
        """
        Args:
            scale: 奖励缩放因子
        """
        self.scale = scale

    def compute(
        self,
        env,
        prev_value: float,
        curr_value: float,
        action: np.ndarray,
    ) -> float:
        """计算盈亏奖励"""
        pnl = (curr_value - prev_value) / prev_value
        return pnl * self.scale


class SharpeReward(RewardFunction):
    """Sharpe比率奖励

    考虑收益和波动的风险调整奖励
    """

    def __init__(self, window: int = 20, risk_free_rate: float = 0.0):
        """
        Args:
            window: 计算窗口
            risk_free_rate: 无风险利率(年化)
        """
        self.window = window
        self.risk_free_rate = risk_free_rate
        self.returns_history = deque(maxlen=window)

    def compute(
        self,
        env,
        prev_value: float,
        curr_value: float,
        action: np.ndarray,
    ) -> float:
        """计算Sharpe奖励"""
        ret = (curr_value - prev_value) / prev_value
        self.returns_history.append(ret)

        if len(self.returns_history) < 2:
            return 0.0

        returns = np.array(self.returns_history)

        # 计算年化收益率和波动率
        mean_return = returns.mean() * 252  # 假设252个交易日
        std_return = returns.std() * np.sqrt(252)

        # Sharpe比率
        sharpe = (mean_return - self.risk_free_rate) / (std_return + 1e-10)

        return sharpe


class RiskAdjustedReward(RewardFunction):
    """风险调整奖励

    考虑最大回撤的奖励函数
    """

    def __init__(self, drawdown_penalty: float = 1.0):
        """
        Args:
            drawdown_penalty: 回撤惩罚系数
        """
        self.drawdown_penalty = drawdown_penalty
        self.peak = float('inf')
        self.history = []

    def compute(
        self,
        env,
        prev_value: float,
        curr_value: float,
        action: np.ndarray,
    ) -> float:
        """计算风险调整奖励"""
        self.peak = max(self.peak, curr_value)

        # 计算回撤
        drawdown = (self.peak - curr_value) / self.peak

        # 基础收益
        pnl = (curr_value - prev_value) / prev_value

        # 风险调整奖励
        reward = pnl - self.drawdown_penalty * drawdown

        return reward


class RuleBasedReward(RewardFunction):
    """基于规则的奖励

    根据当前状态和动作的"正确性"给予奖励
    """

    def __init__(
        self,
        reward_matrix: Optional[Dict] = None,
        action_penalty: float = 0.0,
    ):
        """
        Args:
            reward_matrix: 奖励矩阵 {zone: {position: {action: reward}}}
            action_penalty: 动作变化惩罚(过度交易)
        """
        self.reward_matrix = reward_matrix or self._default_reward_matrix()
        self.action_penalty = action_penalty
        self.last_action = None

    def _default_reward_matrix(self) -> Dict:
        """默认奖励矩阵

        Zone: 0=高zscore(应short leg0), 4=低zscore(应long leg0)
        Position: 0=short leg0, 1=flat, 2=long leg0
        Action: 0=short leg0, 1=flat, 2=long leg0
        """
        return {
            0: {  # 高zscore区域
                0: {0: 1, 1: 0, 2: -1},  # 已short, 应保持
                1: {0: 1, 1: 0, 2: 0},   # 空仓, 应开short
                2: {0: 1, 1: 1, 2: 0},   # 已long, 应平仓后short
            },
            1: {
                0: {0: 1, 1: 0, 2: 0},
                1: {0: 0, 1: 1, 2: 0},
                2: {0: 0, 1: 1, 2: 1},
            },
            2: {  # 中性区域
                0: {0: 0, 1: 1, 2: 0},
                1: {0: 0, 1: 1, 2: 0},
                2: {0: 0, 1: 1, 2: 0},
            },
            3: {
                0: {0: 0, 1: 1, 2: 1},
                1: {0: 0, 1: 1, 2: 0},
                2: {0: 0, 1: 0, 2: 1},
            },
            4: {  # 低zscore区域
                0: {0: 0, 1: 1, 2: 1},   # 已short, 应平仓后long
                1: {0: 0, 1: 0, 2: 1},    # 空仓, 应开long
                2: {0: -1, 1: 0, 2: 1},  # 已long, 应保持
            },
        }

    def compute(
        self,
        env,
        prev_value: float,
        curr_value: float,
        action: np.ndarray,
    ) -> float:
        """计算规则奖励"""
        # 获取当前状态
        zone = getattr(env, 'zone', 2)
        position = getattr(env, 'position', 1)

        # 获取动作
        if isinstance(action, np.ndarray):
            action = int(action[0]) if len(action) > 0 else 1
        else:
            action = int(action)

        # 从奖励矩阵获取基础奖励
        try:
            base_reward = self.reward_matrix.get(zone, {}).get(
                position, {}).get(action, 0)
        except KeyError:
            base_reward = 0

        # 过度交易惩罚
        action_penalty = 0
        if self.last_action is not None and action != self.last_action:
            action_penalty = -self.action_penalty

        self.last_action = action

        return base_reward + action_penalty


class CompositeReward(RewardFunction):
    """组合奖励函数

    组合多个奖励函数
    """

    def __init__(self, rewards: list, weights: Optional[list] = None):
        """
        Args:
            rewards: 奖励函数列表
            weights: 权重列表
        """
        self.rewards = rewards
        self.weights = weights or [1.0] * len(rewards)

        if len(self.rewards) != len(self.weights):
            raise ValueError("rewards和weights长度不一致")

    def compute(
        self,
        env,
        prev_value: float,
        curr_value: float,
        action: np.ndarray,
    ) -> float:
        """计算组合奖励"""
        total_reward = 0.0

        for reward_fn, weight in zip(self.rewards, self.weights):
            r = reward_fn.compute(env, prev_value, curr_value, action)
            total_reward += weight * r

        return total_reward


class RewardShaper:
    """奖励整形器

    对原始奖励进行变换
    """

    def __init__(
        self,
        clip_range: Optional[tuple] = None,
        scale: float = 1.0,
        offset: float = 0.0,
        transform: Optional[Callable] = None,
    ):
        """
        Args:
            clip_range: 裁剪范围 (min, max)
            scale: 缩放因子
            offset: 偏移量
            transform: 自定义变换函数
        """
        self.clip_range = clip_range
        self.scale = scale
        self.offset = offset
        self.transform = transform

    def shape(self, reward: float) -> float:
        """整形奖励"""
        # 应用裁剪
        if self.clip_range is not None:
            reward = np.clip(reward, self.clip_range[0], self.clip_range[1])

        # 应用缩放
        reward = reward * self.scale

        # 应用偏移
        reward = reward + self.offset

        # 应用自定义变换
        if self.transform is not None:
            reward = self.transform(reward)

        return reward
```

### 3.6 配对选择工具

```python
"""
backtrader/pairtrading/selector.py

配对资产选择工具
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional
from statsmodels.tsa.stattools import coint
from scipy.stats import pearsonr, spearmanr
from sklearn.cluster import KMeans


class PairSelector:
    """配对选择器

    基于协整检验和相关分析选择配对资产
    """

    def __init__(self, significance_level: float = 0.05):
        """
        Args:
            significance_level: 协整检验显著性水平
        """
        self.significance_level = significance_level
        self.results = {}

    def find_cointegrated_pairs(
        self,
        prices: pd.DataFrame,
        method: str = 'engle-granger',
        maxlag: int = 1
    ) -> List[Tuple[str, str, float]]:
        """寻找协整配对

        Args:
            prices: 价格DataFrame (列为资产名，索引为时间)
            method: 协整检验方法
            maxlag: 最大滞后阶数

        Returns:
            [(asset1, asset2, pvalue), ...] 协整配对列表(按p值排序)
        """
        assets = prices.columns.tolist()
        pairs = []

        for i, asset1 in enumerate(assets):
            for asset2 in assets[i+1:]:
                # 移除NaN
                series1 = prices[asset1].dropna()
                series2 = prices[asset2].dropna()

                # 对齐时间
                common_index = series1.index.intersection(series2.index)
                if len(common_index) < 30:  # 至少30个数据点
                    continue

                s1 = series1.loc[common_index]
                s2 = series2.loc[common_index]

                # 协整检验
                try:
                    score, pvalue, _ = coint(s1, s2, maxlag=maxlag)

                    if pvalue < self.significance_level:
                        pairs.append((asset1, asset2, pvalue))
                except:
                    continue

        # 按p值排序
        pairs.sort(key=lambda x: x[2])

        self.results['cointegrated'] = pairs
        return pairs

    def correlation_filter(
        self,
        prices: pd.DataFrame,
        min_corr: float = 0.7,
        method: str = 'pearson'
    ) -> List[Tuple[str, str, float]]:
        """相关性过滤

        Args:
            prices: 价格DataFrame
            min_corr: 最小相关系数
            method: 相关性方法 ('pearson', 'spearman')

        Returns:
            [(asset1, asset2, corr), ...] 高相关配对列表
        """
        assets = prices.columns.tolist()
        pairs = []

        for i, asset1 in enumerate(assets):
            for asset2 in assets[i+1:]:
                s1 = prices[asset1].dropna()
                s2 = prices[asset2].dropna()

                # 对齐时间
                common_index = s1.index.intersection(s2.index)
                if len(common_index) < 10:
                    continue

                s1 = s1.loc[common_index]
                s2 = s2.loc[common_index]

                # 计算相关性
                if method == 'pearson':
                    corr, _ = pearsonr(s1, s2)
                elif method == 'spearman':
                    corr, _ = spearmanr(s1, s2)
                else:
                    corr = s1.corr(s2)

                if abs(corr) >= min_corr:
                    pairs.append((asset1, asset2, corr))

        # 按相关系数排序
        pairs.sort(key=lambda x: abs(x[2]), reverse=True)

        self.results['correlation'] = pairs
        return pairs

    def combined_selection(
        self,
        prices: pd.DataFrame,
        min_corr: float = 0.7,
        max_pvalue: float = 0.05,
        correlation_method: str = 'pearson'
    ) -> List[Tuple[str, str, float, float]]:
        """组合选择: 同时满足协整和高相关

        Args:
            prices: 价格DataFrame
            min_corr: 最小相关系数
            max_pvalue: 最大p值
            correlation_method: 相关性方法

        Returns:
            [(asset1, asset2, corr, pvalue), ...]
        """
        # 获取高相关配对
        corr_pairs = self.correlation_filter(prices, min_corr, correlation_method)
        corr_pair_set = {(a, b) for a, b, _ in corr_pairs}

        # 获取协整配对
        coint_pairs = self.find_cointegrated_pairs(prices)
        coint_pair_dict = {(a, b): p for a, b, p in coint_pairs}

        # 取交集
        combined = []
        for a, b, corr in corr_pairs:
            # 检查两个方向
            pvalue = coint_pair_dict.get((a, b), coint_pair_dict.get((b, a)))
            if pvalue is not None and pvalue <= max_pvalue:
                combined.append((a, b, corr, pvalue))

        # 按综合得分排序
        combined.sort(key=lambda x: x[2] / (x[3] + 1e-10), reverse=True)

        self.results['combined'] = combined
        return combined

    def sector_filter(
        self,
        prices: pd.DataFrame,
        sector_map: Dict[str, str],
        target_sector: Optional[str] = None
    ) -> List[Tuple[str, str]]:
        """行业过滤

        Args:
            prices: 价格DataFrame
            sector_map: 资产到行业的映射
            target_sector: 目标行业，None则行业内部配对

        Returns:
            [(asset1, asset2), ...] 同行业配对列表
        """
        assets = prices.columns.tolist()
        pairs = []

        # 按行业分组
        sector_assets = {}
        for asset in assets:
            sector = sector_map.get(asset, 'Unknown')
            if sector not in sector_assets:
                sector_assets[sector] = []
            sector_assets[sector].append(asset)

        # 生成同行业配对
        for sector, sec_assets in sector_assets.items():
            if target_sector is not None and sector != target_sector:
                continue

            for i, a1 in enumerate(sec_assets):
                for a2 in sec_assets[i+1:]:
                    pairs.append((a1, a2))

        self.results['sector'] = pairs
        return pairs


class ClusterPairSelector(PairSelector):
    """基于聚类的配对选择器

    使用聚类分析将相似资产分组
    """

    def __init__(
        self,
        n_clusters: int = 5,
        significance_level: float = 0.05
    ):
        super().__init__(significance_level)
        self.n_clusters = n_clusters

    def find_clusters(
        self,
        prices: pd.DataFrame,
        feature: str = 'returns'
    ) -> Dict[int, List[str]]:
        """基于价格特征聚类

        Args:
            prices: 价格DataFrame
            feature: 聚类特征 ('returns', 'volatility', 'trend')

        Returns:
            {cluster_id: [assets]}
        """
        # 计算特征
        if feature == 'returns':
            features = prices.pct_change().mean().values.reshape(-1, 1)
        elif feature == 'volatility':
            features = prices.pct_change().std().values.reshape(-1, 1)
        elif feature == 'trend':
            # 线性趋势斜率
            features = []
            for asset in prices.columns:
                vals = prices[asset].values
                if len(vals) > 1:
                    slope = np.polyfit(range(len(vals)), vals, 1)[0]
                    features.append([slope])
                else:
                    features.append([0])
            features = np.array(features)
        else:
            features = prices.pct_change().mean().values.reshape(-1, 1)

        # K-means聚类
        kmeans = KMeans(n_clusters=self.n_clusters, random_state=42)
        labels = kmeans.fit_predict(features)

        # 分组
        clusters = {}
        for asset, label in zip(prices.columns, labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(asset)

        self.clusters = clusters
        return clusters

    def find_pairs_in_clusters(
        self,
        prices: pd.DataFrame,
        feature: str = 'returns'
    ) -> List[Tuple[str, str, float]]:
        """在聚类内寻找协整配对"""
        clusters = self.find_clusters(prices, feature)
        all_pairs = []

        for cluster_id, assets in clusters.items():
            if len(assets) < 2:
                continue

            # 在聚类内寻找协整配对
            cluster_prices = prices[assets]
            pairs = self.find_cointegrated_pairs(cluster_prices)

            for a1, a2, pvalue in pairs:
                all_pairs.append((a1, a2, pvalue))

        # 按p值排序
        all_pairs.sort(key=lambda x: x[2])

        return all_pairs


class PairRanker:
    """配对排序器

    根据多个指标对配对进行排序
    """

    def __init__(self):
        self.scores = {}

    def rank_pairs(
        self,
        pairs: List[Tuple],
        prices: pd.DataFrame,
        metrics: List[str] = None
    ) -> List[Tuple]:
        """对配对排序

        Args:
            pairs: 配对列表
            prices: 价格数据
            metrics: 评分指标

        Returns:
            排序后的配对列表
        """
        if metrics is None:
            metrics = ['cointegration', 'correlation', 'half_life']

        scores = []
        for pair in pairs:
            if len(pair) == 2:
                a1, a2 = pair
            else:
                a1, a2 = pair[0], pair[1]

            # 获取价格序列
            s1 = prices[a1].dropna()
            s2 = prices[a2].dropna()
            common_idx = s1.index.intersection(s2.index)
            s1 = s1.loc[common_idx]
            s2 = s2.loc[common_idx]

            score = self._compute_score(s1, s2, metrics)
            scores.append((a1, a2, score))

        # 按得分排序
        scores.sort(key=lambda x: x[2], reverse=True)

        return scores

    def _compute_score(
        self,
        s1: pd.Series,
        s2: pd.Series,
        metrics: List[str]
    ) -> float:
        """计算综合得分"""
        total_score = 0.0

        for metric in metrics:
            if metric == 'cointegration':
                # 协整检验p值越小越好
                _, pvalue, _ = coint(s1, s2)
                score = -np.log(pvalue + 1e-10)
            elif metric == 'correlation':
                # 相关性越高越好
                corr = s1.corr(s2)
                score = abs(corr)
            elif metric == 'half_life':
                # 半衰期适中为好
                spread = s1 - s2
                delta = spread.diff().dropna()
                lagged = spread.shift(1).dropna()
                # 简单估计
                if len(lagged) > 0 and len(delta) > 0:
                    lambda_val = -np.cov(lagged[1:], delta)[0, 1] / np.var(lagged[1:])
                    if lambda_val > 0:
                        half_life = np.log(2) / lambda_val
                        # 5-20天为理想区间
                        if 5 <= half_life <= 20:
                            score = 1.0
                        else:
                            score = 1.0 / (1.0 + abs(half_life - 12.5))
                    else:
                        score = 0
                else:
                    score = 0
            else:
                score = 0

            total_score += score

        return total_score
```

---

## 四、使用示例

### 4.1 配对交易策略使用

```python
"""
配对交易策略使用示例
"""

import backtrader as bt
import pandas as pd

# 1. 准备数据
data0 = bt.feeds.PandasData(dataname=pd.read_csv('asset0.csv'))
data1 = bt.feeds.PandasData(dataname=pd.read_csv('asset1.csv'))

# 2. 创建Cerebro引擎
cerebro = bt.Cerebro()

# 3. 添加数据
cerebro.adddata(data0, name='asset0')
cerebro.adddata(data1, name='asset1')

# 4. 添加策略
cerebro.addstrategy(
    PairTradingStrategy,
    open_threshold=2.0,
    close_threshold=0.5,
    period=30,
    use_kelly=True,
)

# 5. 设置初始资金和佣金
cerebro.broker.setcash(100000)
cerebro.broker.setcommission(commission=0.001)

# 6. 运行回测
results = cerebro.run()

# 7. 分析结果
print(f'最终净值: {cerebro.broker.getvalue():.2f}')
```

### 4.2 强化学习环境使用

```python
"""
强化学习环境使用示例
"""

import gymnasium as gym
from backtrader.RL.environment import PairTradingEnv
from stable_baselines3 import PPO

# 1. 准备数据
df = pd.read_csv('pair_data.csv')  # 包含close0, close1, zscore列

# 2. 创建环境
env = PairTradingEnv(
    df=df,
    mode='fixed',  # 或 'free'
    tc=0.0002,
    cash=1.0,
    open_threshold=1.6,
    close_threshold=0.4,
)

# 3. 训练RL智能体
model = PPO('MlpPolicy', env, verbose=1)
model.learn(total_timesteps=10000)

# 4. 测试
obs, info = env.reset()
done = False
total_reward = 0

while not done:
    action, _states = model.predict(obs)
    obs, reward, terminated, truncated, info = env.step(action)
    total_reward += reward
    done = terminated or truncated

print(f'总奖励: {total_reward:.2f}')
print(f'最终净值: {env.networth:.4f}')
```

### 4.3 配对选择流程

```python
"""
配对选择完整流程
"""

import pandas as pd
from backtrader.pairtrading.selector import PairSelector, ClusterPairSelector

# 1. 加载多资产价格数据
prices = pd.read_csv('multi_asset_prices.csv', index_col='date', parse_dates=True)

# 2. 方法1: 直接协整检验
selector = PairSelector(significance_level=0.05)
pairs = selector.find_cointegrated_pairs(prices)

print("协整配对:")
for a1, a2, pval in pairs[:10]:
    print(f"  {a1} - {a2}: p-value = {pval:.4f}")

# 3. 方法2: 组合选择
pairs = selector.combined_selection(
    prices,
    min_corr=0.7,
    max_pvalue=0.05
)

print("\n高相关+协整配对:")
for a1, a2, corr, pval in pairs[:10]:
    print(f"  {a1} - {a2}: corr={corr:.2f}, p-value={pval:.4f}")

# 4. 方法3: 聚类选择
cluster_selector = ClusterPairSelector(n_clusters=5)
pairs = cluster_selector.find_pairs_in_clusters(prices, feature='returns')

print("\n聚类内协整配对:")
for a1, a2, pval in pairs[:10]:
    print(f"  {a1} - {a2}: p-value = {pval:.4f}")
```

---

## 五、目录结构

```
backtrader/
├── pairtrading/              # 配对交易模块
│   ├── __init__.py
│   ├── strategy.py          # 配对交易策略
│   ├── spread.py            # 价差分析
│   └── selector.py          # 配对选择工具
│
├── RL/                       # 强化学习模块
│   ├── __init__.py
│   ├── environment.py       # Gym环境适配器
│   ├── observers.py         # 状态构建器
│   └── rewards.py           # 奖励函数
│
└── utils/
    └── kelly.py             # Kelly Criterion工具
```

---

## 六、实施计划

### 第一阶段（高优先级）

1. **配对交易策略基类** (~400行)
   - ZScoreIndicator指标
   - PairTradingStrategy策略
   - Kelly Criterion支持

2. **价差分析模块** (~300行)
   - 多种价差计算方法
   - 协整检验
   - 相关性分析

3. **状态构建器** (~200行)
   - 观察空间定义
   - 状态归一化

### 第二阶段（中优先级）

4. **RL环境适配器** (~400行)
   - Gymnasium接口
   - 固定/自由金额模式
   - 交易成本模拟

5. **奖励函数模块** (~300行)
   - 多种奖励函数
   - 组合奖励
   - 奖励整形

6. **配对选择工具** (~400行)
   - 协整检验筛选
   - 相关性过滤
   - 聚类分析

### 第三阶段（可选）

7. **高级功能**
   - 多资产配对
   - 动态对冲比率
   - 风险管理

---

## 七、与现有功能对比

| 功能 | backtrader (原生) | 配对交易扩展 |
|------|------------------|-------------|
| 多资产支持 | 基础支持 | 配对交易专用 |
| RL环境 | 无 | Gymnasium标准 |
| 价差分析 | 需手动实现 | 内置多种方法 |
| 协整检验 | 无 | 内置 |
| 配对选择 | 无 | 自动选择工具 |
| 奖励函数 | 无 | 多种预制函数 |
| Kelly准则 | 无 | 内置 |

---

## 八、向后兼容性

所有配对交易和RL功能均为**完全可选的独立模块**：

1. 配对交易功能通过`from backtrader.pairtrading import ...`使用
2. RL功能通过`from backtrader.RL import ...`使用
3. 不影响现有策略的运行
4. 用户可以选择使用传统策略或配对交易策略
5. RL环境可以与任何backtrader策略配合使用
