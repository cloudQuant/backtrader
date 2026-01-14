### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/BackTraderUI
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### BackTraderUI项目简介
BackTraderUI是backtrader的Web界面扩展项目，具有以下核心特点：
- **Web界面**: 提供Web管理界面
- **策略管理**: 策略可视化管理
- **回测控制**: 回测任务控制
- **结果展示**: 回测结果展示
- **参数配置**: 可视化参数配置
- **实时监控**: 实时状态监控

### 重点借鉴方向
1. **Web架构**: Web应用架构设计
2. **界面设计**: 用户界面设计
3. **API设计**: REST API设计
4. **实时更新**: 实时数据更新
5. **任务管理**: 回测任务管理
6. **结果可视化**: 结果可视化展示

---

# 分析与设计文档

## 一、框架对比分析

### 1.1 backtrader vs BackTraderUI 对比

| 维度 | backtrader (原生) | BackTraderUI |
|------|------------------|--------------|
| **定位** | Python回测框架 | Web可视化管理平台 |
| **使用方式** | 代码编写 | Web界面操作 |
| **策略管理** | 文件系统 | 数据库+界面 |
| **回测执行** | 本地运行 | 服务器端执行 |
| **结果展示** | 控制台/图表 | Web页面+交互图表 |
| **实时监控** | 无 | WebSocket推送 |
| **任务调度** | 无 | 异步任务队列 |
| **数据存储** | 内存/文件 | 数据库持久化 |
| **多用户支持** | 无 | 用户系统 |

### 1.2 可借鉴的核心优势

1. **前后端分离架构**: Django + Vue3 分离，易于扩展
2. **ECharts金融图表**: 专业的K线图和指标展示
3. **多市场数据支持**: SSE/SZSE/BJSE 分表设计
4. **技术指标预计算**: MA5/10/20/30 和九转信号
5. **统一API响应格式**: 标准化的JSON响应
6. **可扩展的模块设计**: 策略、数据、分析器分离

---

## 二、需求规格文档

### 2.1 Web服务框架

**需求描述**: 为backtrader提供可选的Web服务扩展，支持可视化管理。

**功能要求**:
- 提供RESTful API接口
- 支持多种部署方式（独立服务/嵌入式）
- 轻量级设计，可选依赖
- 完善的API文档

**技术选型**:
```python
# 推荐使用FastAPI框架（轻量、高性能）
# 或者提供Flask适配器（兼容性好）
```

### 2.2 策略管理服务

**需求描述**: 提供策略的上传、存储、列表和详情查询。

**功能要求**:
- 策略代码上传（Python文件）
- 策略元数据管理（名称、描述、参数）
- 策略版本控制
- 策略模板库

**API设计**:
```
GET    /api/strategies           # 获取策略列表
POST   /api/strategies           # 上传策略
GET    /api/strategies/{id}      # 获取策略详情
PUT    /api/strategies/{id}      # 更新策略
DELETE /api/strategies/{id}      # 删除策略
GET    /api/strategies/{id}/params  # 获取策略参数定义
```

### 2.3 回测任务服务

**需求描述**: 提供回测任务的创建、执行、监控和结果查询。

**功能要求**:
- 异步任务执行
- 任务状态跟踪（pending/running/completed/failed）
- 任务进度推送
- 任务取消和重试
- 任务队列管理

**API设计**:
```
POST   /api/backtests            # 创建回测任务
GET    /api/backtests            # 获取任务列表
GET    /api/backtests/{id}       # 获取任务详情
DELETE /api/backtests/{id}       # 取消任务
GET    /api/backtests/{id}/logs  # 获取任务日志
GET    /api/backtests/{id}/progress  # 获取任务进度
```

### 2.4 实时推送服务

**需求描述**: 提供WebSocket实时数据推送能力。

**功能要求**:
- 任务进度推送
- 回测日志实时输出
- 数据更新通知
- 心跳保活

**WebSocket事件**:
```javascript
// 客户端订阅
ws.send(JSON.stringify({
  action: 'subscribe',
  channel: 'backtest',
  task_id: '123'
}))

// 服务器推送
{
  event: 'progress',
  data: {
    task_id: '123',
    progress: 45,
    current_bar: 100,
    total_bars: 1000
  }
}
```

### 2.5 数据管理服务

**需求描述**: 提供数据源的统一管理和查询。

**功能要求**:
- 数据源注册
- 数据查询API
- 数据缓存
- 数据更新通知

**API设计**:
```
GET    /api/data/sources         # 获取数据源列表
GET    /api/data/{source}/symbols   # 获取品种列表
GET    /api/data/{source}/{symbol}   # 获取历史数据
POST   /api/data/{source}/update     # 更新数据
```

### 2.6 结果可视化服务

**需求描述**: 提供回测结果的标准化数据和图表配置。

**功能要求**:
- 标准化性能指标数据
- 图表配置生成（ECharts/Plotly）
- 交易记录导出
- 报告生成

**API设计**:
```
GET    /api/results/{id}/summary    # 获取性能指标
GET    /api/results/{id}/trades     # 获取交易记录
GET    /api/results/{id}/chart      # 获取图表配置
GET    /api/results/{id}/export     # 导出报告
```

---

## 三、详细设计文档

### 3.1 Web服务框架核心

**设计思路**: 使用FastAPI创建轻量级Web服务，支持ASGI异步执行。

```python
# backtrader/web/__init__.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


# === 数据模型 ===

class APIResponse(BaseModel):
    """统一API响应格式"""
    code: str = "ok"
    message: str = "success"
    data: Any = None


class StrategyInfo(BaseModel):
    """策略信息"""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    code: str
    params: Dict[str, Any] = {}
    created_at: Optional[str] = None


class BacktestRequest(BaseModel):
    """回测请求"""
    strategy_id: str
    strategy_params: Dict[str, Any] = {}
    data_source: str
    symbol: str
    start_date: str
    end_date: str
    initial_cash: float = 10000
    commission: float = 0.001


class BacktestStatus(BaseModel):
    """回测状态"""
    task_id: str
    status: str  # pending, running, completed, failed
    progress: float = 0
    current_bar: int = 0
    total_bars: int = 0
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class BacktestResult(BaseModel):
    """回测结果"""
    task_id: str
    status: str
    summary: Dict[str, Any]
    trades: List[Dict[str, Any]]
    equity_curve: List[Dict[str, Any]]
    drawdown: List[Dict[str, Any]]


# === FastAPI应用 ===

def create_app(config: Optional[Dict] = None) -> FastAPI:
    """创建FastAPI应用

    Args:
        config: 配置字典

    Returns:
        FastAPI应用实例
    """
    app = FastAPI(
        title="BackTrader Web API",
        description="BackTrader量化交易框架Web服务",
        version="1.0.0"
    )

    # CORS配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    _register_routes(app)

    # 注册异常处理
    _register_handlers(app)

    return app


def _register_routes(app: FastAPI):
    """注册路由"""
    from .routes import strategies, backtests, data, results

    app.include_router(strategies.router, prefix="/api/strategies", tags=["strategies"])
    app.include_router(backtests.router, prefix="/api/backtests", tags=["backtests"])
    app.include_router(data.router, prefix="/api/data", tags=["data"])
    app.include_router(results.router, prefix="/api/results", tags=["results"])


def _register_handlers(app: FastAPI):
    """注册异常处理"""

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error(f"Unhandled exception: {exc}")
        return APIResponse(
            code="error",
            message=str(exc)
        )

    @app.get("/")
    async def root():
        return {
            "name": "BackTrader Web API",
            "version": "1.0.0",
            "docs": "/docs"
        }

    @app.get("/health")
    async def health():
        return {"status": "healthy"}
```

### 3.2 策略管理服务

**设计思路**: 策略以代码形式存储，支持动态加载和参数解析。

```python
# backtrader/web/routes/strategies.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import inspect
import importlib.util
import os
import tempfile
from typing import Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# 内存存储（生产环境应使用数据库）
_strategies: Dict[str, StrategyInfo] = {}
_strategy_counter = 0


class StrategyUpload(BaseModel):
    """策略上传"""
    name: str
    description: Optional[str] = None
    code: str


class StrategyParams(BaseModel):
    """策略参数"""
    params: Dict[str, Any]


@router.get("/", response_model=List[StrategyInfo])
async def list_strategies():
    """获取策略列表"""
    return list(_strategies.values())


@router.post("/", response_model=StrategyInfo)
async def create_strategy(upload: StrategyUpload):
    """创建策略"""
    global _strategy_counter
    _strategy_counter += 1
    strategy_id = f"str_{_strategy_counter}"

    # 验证代码
    try:
        params = _extract_strategy_params(upload.code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"策略代码无效: {e}")

    strategy = StrategyInfo(
        id=strategy_id,
        name=upload.name,
        description=upload.description,
        code=upload.code,
        params=params,
        created_at=datetime.now().isoformat()
    )

    _strategies[strategy_id] = strategy
    return strategy


@router.get("/{strategy_id}", response_model=StrategyInfo)
async def get_strategy(strategy_id: str):
    """获取策略详情"""
    if strategy_id not in _strategies:
        raise HTTPException(status_code=404, detail="策略不存在")
    return _strategies[strategy_id]


@router.put("/{strategy_id}", response_model=StrategyInfo)
async def update_strategy(strategy_id: str, upload: StrategyUpload):
    """更新策略"""
    if strategy_id not in _strategies:
        raise HTTPException(status_code=404, detail="策略不存在")

    try:
        params = _extract_strategy_params(upload.code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"策略代码无效: {e}")

    strategy = StrategyInfo(
        id=strategy_id,
        name=upload.name,
        description=upload.description,
        code=upload.code,
        params=params,
        created_at=_strategies[strategy_id].created_at
    )

    _strategies[strategy_id] = strategy
    return strategy


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: str):
    """删除策略"""
    if strategy_id not in _strategies:
        raise HTTPException(status_code=404, detail="策略不存在")
    del _strategies[strategy_id]
    return {"code": "ok", "message": "删除成功"}


@router.get("/{strategy_id}/params")
async def get_strategy_params(strategy_id: str):
    """获取策略参数定义"""
    if strategy_id not in _strategies:
        raise HTTPException(status_code=404, detail="策略不存在")
    return {
        "code": "ok",
        "data": _strategies[strategy_id].params
    }


def _extract_strategy_params(code: str) -> Dict[str, Any]:
    """从代码中提取策略参数

    Args:
        code: 策略代码

    Returns:
        参数字典
    """
    import backtrader as bt

    # 创建临时模块
    temp_module = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
    temp_module.write(code)
    temp_module.close()

    try:
        # 动态导入
        spec = importlib.util.spec_from_file_location("temp_strategy", temp_module.name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 查找Strategy类
        strategy_class = None
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, bt.Strategy) and obj != bt.Strategy:
                strategy_class = obj
                break

        if strategy_class is None:
            raise ValueError("未找到Strategy类")

        # 提取参数
        params = {}
        if hasattr(strategy_class, 'params'):
            for key, value in strategy_class.params._getitems():
                params[key] = _serialize_param(value)

        return params

    finally:
        os.unlink(temp_module.name)


def _serialize_param(value):
    """序列化参数值"""
    if isinstance(value, (int, float, str, bool)):
        return value
    elif isinstance(value, (list, tuple)):
        return list(value)
    else:
        return str(value)
```

### 3.3 回测任务服务

**设计思路**: 使用后台任务队列执行回测，支持状态跟踪。

```python
# backtrader/web/routes/backtests.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import uuid
import importlib.util
import os
import tempfile
import threading
import time
from typing import Dict, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

import backtrader as bt

logger = logging.getLogger(__name__)

router = APIRouter()

# 任务存储
_tasks: Dict[str, BacktestStatus] = {}
_task_counter = 0
_task_lock = threading.Lock()


class BacktestRequest(BaseModel):
    """回测请求"""
    strategy_id: str
    strategy_params: Dict[str, Any] = {}
    data_source: str = "yahoo"
    symbol: str = "AAPL"
    start_date: str
    end_date: str
    initial_cash: float = 10000
    commission: float = 0.001


@router.post("/", response_model=BacktestStatus)
async def create_backtest(request: BacktestRequest, background_tasks: BackgroundTasks):
    """创建回测任务"""
    global _task_counter

    # 验证策略存在
    if request.strategy_id not in _strategies:
        raise HTTPException(status_code=404, detail="策略不存在")

    _task_counter += 1
    task_id = f"task_{_task_counter}"

    task = BacktestStatus(
        task_id=task_id,
        status="pending",
        created_at=datetime.now().isoformat()
    )

    with _task_lock:
        _tasks[task_id] = task

    # 添加后台任务
    background_tasks.add_task(
        _execute_backtest,
        task_id,
        request
    )

    return task


@router.get("/", response_model=List[BacktestStatus])
async def list_backtests():
    """获取任务列表"""
    return list(_tasks.values())


@router.get("/{task_id}", response_model=BacktestStatus)
async def get_backtest(task_id: str):
    """获取任务详情"""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _tasks[task_id]


@router.delete("/{task_id}")
async def cancel_backtest(task_id: str):
    """取消任务"""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = _tasks[task_id]
    if task.status == "running":
        # TODO: 实现取消逻辑
        task.status = "cancelled"
    elif task.status in ("pending", "completed", "failed"):
        pass

    return {"code": "ok", "message": "任务已取消"}


@router.get("/{task_id}/logs")
async def get_backtest_logs(task_id: str):
    """获取任务日志"""
    # TODO: 实现日志存储
    return {"code": "ok", "data": []}


@router.get("/{task_id}/progress")
async def get_backtest_progress(task_id: str):
    """获取任务进度"""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = _tasks[task_id]
    return {
        "code": "ok",
        "data": {
            "task_id": task_id,
            "status": task.status,
            "progress": task.progress,
            "current_bar": task.current_bar,
            "total_bars": task.total_bars
        }
    }


def _execute_backtest(task_id: str, request: BacktestRequest):
    """执行回测（后台任务）"""
    try:
        # 更新状态
        with _task_lock:
            _tasks[task_id].status = "running"
            _tasks[task_id].started_at = datetime.now().isoformat()

        # 获取策略代码
        strategy_code = _strategies[request.strategy_id].code

        # 创建cerebro
        cerebro = bt.Cerebro()

        # 设置初始资金
        cerebro.broker.setcash(request.initial_cash)

        # 设置佣金
        cerebro.broker.setcommission(commission=request.commission)

        # 加载数据
        data = _load_data(
            request.data_source,
            request.symbol,
            request.start_date,
            request.end_date
        )
        cerebro.adddata(data)

        # 添加策略
        strategy_class = _load_strategy_class(strategy_code)
        cerebro.addstrategy(strategy_class, **request.strategy_params)

        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        # 执行回测
        strats = cerebro.run()

        # 提取结果
        result = _extract_result(cerebro, strats[0])

        # 存储结果
        _results[task_id] = result

        # 更新状态
        with _task_lock:
            _tasks[task_id].status = "completed"
            _tasks[task_id].progress = 100
            _tasks[task_id].completed_at = datetime.now().isoformat()

    except Exception as e:
        logger.error(f"Backtest failed: {e}")

        with _task_lock:
            _tasks[task_id].status = "failed"
            _tasks[task_id].error = str(e)
            _tasks[task_id].completed_at = datetime.now().isoformat()


def _load_data(source: str, symbol: str, start: str, end: str):
    """加载数据"""
    if source == "yahoo":
        import btfeeds
        return btfeeds.YahooFinanceData(
            dataname=symbol,
            fromdate=datetime.strptime(start, "%Y-%m-%d"),
            todate=datetime.strptime(end, "%Y-%m-%d")
        )
    # 其他数据源...
    else:
        raise ValueError(f"Unsupported data source: {source}")


def _load_strategy_class(code: str):
    """从代码加载策略类"""
    temp_module = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
    temp_module.write(code)
    temp_module.close()

    try:
        spec = importlib.util.spec_from_file_location("temp_strategy", temp_module.name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, bt.Strategy) and obj != bt.Strategy:
                return obj

        raise ValueError("未找到Strategy类")

    finally:
        os.unlink(temp_module.name)


def _extract_result(cerebro, strategy):
    """提取回测结果"""
    # 获取分析器结果
    sharpe = strategy.analyzers.sharpe.get_analysis()
    drawdown = strategy.analyzers.drawdown.get_analysis()
    trades = strategy.analyzers.trades.get_analysis()

    # 获取净值曲线
    values = [ cerebro.broker.getvalue() ]
    # TODO: 完整的净值曲线提取

    return BacktestResult(
        task_id=task_id,
        status="completed",
        summary={
            "sharpe_ratio": sharpe.get('sharperatio'),
            "max_drawdown": drawdown.get('max', {}).get('drawdown', 0),
            "total_trades": trades.get('total', {}).get('total', 0),
            "won": trades.get('won', {}).get('total', 0),
            "lost": trades.get('lost', {}).get('total', 0),
        },
        trades=[],
        equity_curve=[],
        drawdown=[]
    )
```

### 3.4 WebSocket实时推送

**设计思路**: 使用WebSocket推送回测进度和日志。

```python
# backtrader/web/websocket.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import json
from typing import Dict, Set
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        # task_id -> WebSocket连接集合
        self._connections: Dict[str, Set[WebSocket]] = {}

    async def subscribe(self, task_id: str, websocket: WebSocket):
        """订阅任务更新"""
        if task_id not in self._connections:
            self._connections[task_id] = set()
        self._connections[task_id].add(websocket)
        logger.info(f"WebSocket subscribed to task {task_id}")

    async def unsubscribe(self, task_id: str, websocket: WebSocket):
        """取消订阅"""
        if task_id in self._connections:
            self._connections[task_id].discard(websocket)
            if not self._connections[task_id]:
                del self._connections[task_id]

    async def broadcast(self, task_id: str, message: dict):
        """广播消息给订阅者"""
        if task_id not in self._connections:
            return

        removed = set()
        for websocket in self._connections[task_id]:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                removed.add(websocket)

        # 清理断开的连接
        for websocket in removed:
            self._connections[task_id].discard(websocket)

    async def send_progress(self, task_id: str, progress: float,
                           current_bar: int, total_bars: int):
        """发送进度更新"""
        await self.broadcast(task_id, {
            "event": "progress",
            "data": {
                "task_id": task_id,
                "progress": progress,
                "current_bar": current_bar,
                "total_bars": total_bars
            }
        })

    async def send_log(self, task_id: str, level: str, message: str):
        """发送日志"""
        await self.broadcast(task_id, {
            "event": "log",
            "data": {
                "task_id": task_id,
                "level": level,
                "message": message,
                "timestamp": time.time()
            }
        })

    async def send_complete(self, task_id: str, result: dict):
        """发送完成通知"""
        await self.broadcast(task_id, {
            "event": "complete",
            "data": {
                "task_id": task_id,
                "result": result
            }
        })


# 全局连接管理器
manager = ConnectionManager()


# WebSocket路由
@router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket端点"""
    await websocket.accept()

    await manager.subscribe(task_id, websocket)

    try:
        # 发送欢迎消息
        await websocket.send_json({
            "event": "connected",
            "data": {"task_id": task_id}
        })

        # 保持连接并处理客户端消息
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("action") == "ping":
                await websocket.send_json({"event": "pong"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected from task {task_id}")
    finally:
        await manager.unsubscribe(task_id, websocket)
```

### 3.5 结果可视化服务

**设计思路**: 提供标准化的结果数据和图表配置。

```python
# backtrader/web/routes/results.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import numpy as np
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class ChartConfig(BaseModel):
    """图表配置"""
    title: str
    type: str  # candlestick, line, bar, scatter
    series: List[Dict]
    xAxis: Optional[Dict] = None
    yAxis: Optional[Dict] = None


@router.get("/{task_id}/summary")
async def get_result_summary(task_id: str):
    """获取性能指标汇总"""
    if task_id not in _results:
        raise HTTPException(status_code=404, detail="结果不存在")

    result = _results[task_id]

    return {
        "code": "ok",
        "data": {
            "initial_cash": result.summary.get("initial_cash"),
            "final_value": result.summary.get("final_value"),
            "total_return": result.summary.get("total_return"),
            "annual_return": result.summary.get("annual_return"),
            "sharpe_ratio": result.summary.get("sharpe_ratio"),
            "max_drawdown": result.summary.get("max_drawdown"),
            "max_drawdown_pct": result.summary.get("max_drawdown_pct"),
            "total_trades": result.summary.get("total_trades"),
            "win_rate": result.summary.get("win_rate"),
            "profit_factor": result.summary.get("profit_factor"),
            "avg_win": result.summary.get("avg_win"),
            "avg_loss": result.summary.get("avg_loss"),
        }
    }


@router.get("/{task_id}/trades")
async def get_result_trades(task_id: str, skip: int = 0, limit: int = 100):
    """获取交易记录"""
    if task_id not in _results:
        raise HTTPException(status_code=404, detail="结果不存在")

    result = _results[task_id]
    trades = result.trades[skip:skip + limit]

    return {
        "code": "ok",
        "data": {
            "total": len(result.trades),
            "trades": trades
        }
    }


@router.get("/{task_id}/chart")
async def get_result_chart(task_id: str, chart_type: str = "candlestick"):
    """获取图表配置"""
    if task_id not in _results:
        raise HTTPException(status_code=404, detail="结果不存在")

    result = _results[task_id]

    if chart_type == "candlestick":
        config = _generate_candlestick_chart(result)
    elif chart_type == "equity":
        config = _generate_equity_chart(result)
    elif chart_type == "drawdown":
        config = _generate_drawdown_chart(result)
    else:
        raise HTTPException(status_code=400, detail="不支持的图表类型")

    return {
        "code": "ok",
        "data": config
    }


@router.get("/{task_id}/export")
async def export_result(task_id: str, format: str = "json"):
    """导出结果"""
    if task_id not in _results:
        raise HTTPException(status_code=404, detail="结果不存在")

    result = _results[task_id]

    if format == "json":
        return result.dict()
    elif format == "csv":
        # 生成CSV
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        # 写入摘要
        writer.writerow(["指标", "值"])
        for key, value in result.summary.items():
            writer.writerow([key, value])

        # 写入交易
        writer.writerow([])
        writer.writerow(["交易记录"])
        writer.writerow(["日期", "类型", "价格", "数量", "盈亏"])
        for trade in result.trades:
            writer.writerow([
                trade.get("date"),
                trade.get("type"),
                trade.get("price"),
                trade.get("size"),
                trade.get("pnl")
            ])

        return {
            "code": "ok",
            "data": output.getvalue(),
            "content_type": "text/csv"
        }
    else:
        raise HTTPException(status_code=400, detail="不支持的导出格式")


def _generate_candlestick_chart(result: BacktestResult) -> ChartConfig:
    """生成K线图配置（ECharts格式）"""
    # 从数据中提取OHLC
    ohlc = []
    for bar in result.bars:
        ohlc.append([
            bar['datetime'],
            bar['open'],
            bar['close'],
            bar['low'],
            bar['high'],
            bar['volume']
        ])

    return ChartConfig(
        title="回测K线图",
        type="candlestick",
        series=[
            {
                "name": "K线",
                "type": "candlestick",
                "data": ohlc,
                "itemStyle": {
                    "color": "#ef5350",
                    "color0": "#26a69a",
                    "borderColor": "#ef5350",
                    "borderColor0": "#26a69a"
                }
            },
            {
                "name": "MA5",
                "type": "line",
                "data": result.indicators.get("ma5", []),
                "smooth": True,
                "lineStyle": {"opacity": 0.8}
            },
            {
                "name": "MA10",
                "type": "line",
                "data": result.indicators.get("ma10", []),
                "smooth": True,
                "lineStyle": {"opacity": 0.8}
            },
            {
                "name": "MA20",
                "type": "line",
                "data": result.indicators.get("ma20", []),
                "smooth": True,
                "lineStyle": {"opacity": 0.8}
            },
            {
                "name": "成交量",
                "type": "bar",
                "xAxisIndex": 1,
                "yAxisIndex": 1,
                "data": [bar[5] for bar in ohlc],
                "itemStyle": {
                    "color": "#7fbe9e"
                }
            }
        ]
    )


def _generate_equity_chart(result: BacktestResult) -> ChartConfig:
    """生成净值曲线图"""
    return ChartConfig(
        title="净值曲线",
        type="line",
        series=[
            {
                "name": "账户净值",
                "type": "line",
                "data": result.equity_curve,
                "areaStyle": {},
                "lineStyle": {"width": 2}
            },
            {
                "name": "基准",
                "type": "line",
                "data": result.benchmark_curve,
                "lineStyle": {"type": "dashed"}
            }
        ]
    )


def _generate_drawdown_chart(result: BacktestResult) -> ChartConfig:
    """生成回撤图"""
    return ChartConfig(
        title="回撤分析",
        type="line",
        series=[
            {
                "name": "回撤",
                "type": "line",
                "data": result.drawdown,
                "areaStyle": {
                    "color": "rgba(239, 83, 80, 0.3)"
                },
                "lineStyle": {"color": "#ef5350"}
            }
        ]
    )
```

### 3.6 数据管理服务

**设计思路**: 统一的数据源管理和查询接口。

```python
# backtrader/web/routes/data.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()

# 数据源注册表
_data_sources = {}


def register_data_source(name: str, source_class):
    """注册数据源"""
    _data_sources[name] = source_class


@router.get("/sources")
async def list_data_sources():
    """获取数据源列表"""
    return {
        "code": "ok",
        "data": [
            {
                "name": name,
                "description": source.description
            }
            for name, source in _data_sources.items()
        ]
    }


@router.get("/{source}/symbols")
async def list_symbols(
    source: str,
    search: Optional[str] = None,
    limit: int = Query(100, le=1000)
):
    """获取品种列表"""
    if source not in _data_sources:
        raise HTTPException(status_code=404, detail="数据源不存在")

    data_source = _data_sources[source]
    symbols = data_source.list_symbols(search=search, limit=limit)

    return {
        "code": "ok",
        "data": symbols
    }


@router.get("/{source}/{symbol}")
async def get_data(
    source: str,
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1d"
):
    """获取历史数据"""
    if source not in _data_sources:
        raise HTTPException(status_code=404, detail="数据源不存在")

    data_source = _data_sources[source]

    try:
        data = data_source.get_data(
            symbol=symbol,
            start_date=datetime.strptime(start_date, "%Y-%m-%d"),
            end_date=datetime.strptime(end_date, "%Y-%m-%d"),
            timeframe=timeframe
        )

        return {
            "code": "ok",
            "data": {
                "symbol": symbol,
                "timeframe": timeframe,
                "bars": data
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"数据获取失败: {e}")


@router.post("/{source}/update")
async def update_data(
    source: str,
    symbol: str,
    force: bool = False
):
    """更新数据"""
    if source not in _data_sources:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # 触发后台更新任务
    # TODO: 实现异步更新

    return {
        "code": "ok",
        "message": "更新任务已创建"
    }


# === 内置数据源 ===

class YahooDataSource:
    """Yahoo Finance数据源"""

    description = "Yahoo Finance (免费)"

    def list_symbols(self, search=None, limit=100):
        # Yahoo支持的常见股票
        common_symbols = [
            {"symbol": "AAPL", "name": "Apple Inc."},
            {"symbol": "MSFT", "name": "Microsoft Corporation"},
            {"symbol": "GOOGL", "name": "Alphabet Inc."},
            # ...
        ]
        return common_symbols[:limit]

    def get_data(self, symbol, start_date, end_date, timeframe):
        import backtrader as bt
        from backtrader.feeds import YahooFinanceData

        # 创建临时cerebro加载数据
        cerebro = bt.Cerebro()
        data = YahooFinanceData(
            dataname=symbol,
            fromdate=start_date,
            todate=end_date
        )

        # 执行数据加载
        cerebro.adddata(data)
        cerebro.run()

        # 转换为标准格式
        bars = []
        for i in range(len(data)):
            bars.append({
                "datetime": data.datetime.date(i).isoformat(),
                "open": float(data.open[i]),
                "high": float(data.high[i]),
                "low": float(data.low[i]),
                "close": float(data.close[i]),
                "volume": int(data.volume[i]) if data.volume[i] else 0
            })

        return bars


# 注册内置数据源
register_data_source("yahoo", YahooDataSource)
```

---

## 四、目录结构

```
backtrader/
├── web/                          # Web服务模块
│   ├── __init__.py              # 模块初始化
│   ├── app.py                   # FastAPI应用创建
│   ├── config.py                # 配置管理
│   │
│   ├── routes/                  # API路由
│   │   ├── __init__.py
│   │   ├── strategies.py        # 策略管理
│   │   ├── backtests.py         # 回测任务
│   │   ├── data.py              # 数据管理
│   │   ├── results.py           # 结果查询
│   │   └── websocket.py         # WebSocket
│   │
│   ├── models/                  # 数据模型
│   │   ├── __init__.py
│   │   ├── strategy.py
│   │   ├── backtest.py
│   │   └── result.py
│   │
│   ├── services/                # 业务服务
│   │   ├── __init__.py
│   │   ├── strategy_service.py
│   │   ├── backtest_service.py
│   │   └── data_service.py
│   │
│   ├── data_sources/            # 数据源适配器
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── yahoo.py
│   │   └── csv.py
│   │
│   ├── utils/                   # 工具函数
│   │   ├── __init__.py
│   │   └── chart.py             # 图表生成
│   │
│   └── static/                  # 静态资源（可选UI）
│       ├── index.html
│       ├── css/
│       └── js/
│
└── __init__.py
```

---

## 五、前端界面设计（可选）

### 5.1 Vue3组件结构

```
frontend/
├── src/
│   ├── views/                  # 页面组件
│   │   ├── Dashboard.vue       # 仪表板
│   │   ├── StrategyList.vue    # 策略列表
│   │   ├── StrategyEditor.vue  # 策略编辑器
│   │   ├── BacktestCreate.vue  # 创建回测
│   │   ├── BacktestList.vue    # 任务列表
│   │   └── ResultDetail.vue    # 结果详情
│   │
│   ├── components/             # 可复用组件
│   │   ├── ChartCard.vue       # 图表卡片
│   │   ├── KLineChart.vue      # K线图
│   │   ├── EquityChart.vue     # 净值曲线
│   │   ├── TradeTable.vue      # 交易记录表
│   │   └── MetricCard.vue      # 指标卡片
│   │
│   ├── api/                    # API调用
│   │   ├── client.js           # Axios客户端
│   │   ├── strategy.js
│   │   ├── backtest.js
│   │   └── data.js
│   │
│   └── utils/                  # 工具函数
│       ├── chart.js            # ECharts配置
│       └── format.js           # 格式化函数
│
└── package.json
```

### 5.2 K线图组件示例

```vue
<!-- KLineChart.vue -->
<template>
  <div ref="chart" class="kline-chart"></div>
</template>

<script>
import * as echarts from 'echarts'

export default {
  name: 'KLineChart',
  props: {
    data: Array,
    indicators: Object
  },
  mounted() {
    this.chart = echarts.init(this.$refs.chart)
    this.updateChart()
  },
  watch: {
    data() {
      this.updateChart()
    }
  },
  methods: {
    updateChart() {
      const option = {
        animation: false,
        legend: {
          data: ['K线', 'MA5', 'MA10', 'MA20'],
          top: 10
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' }
        },
        grid: [
          { left: '10%', right: '10%', height: '50%' },
          { left: '10%', right: '10%', top: '70%', height: '16%' }
        ],
        xAxis: [
          { type: 'category', data: this.dates, scale: true },
          { type: 'category', gridIndex: 1, data: this.dates, scale: true }
        ],
        yAxis: [
          { scale: true, splitArea: { show: true } },
          { scale: true, gridIndex: 1, axisLabel: { show: false } }
        ],
        dataZoom: [
          { type: 'inside', xAxisIndex: [0, 1], start: 70, end: 100 },
          { show: true, xAxisIndex: [0, 1], type: 'slider', top: '90%', start: 70, end: 100 }
        ],
        series: [
          {
            name: 'K线',
            type: 'candlestick',
            data: this.candlestickData,
            itemStyle: {
              color: '#ef5350',
              color0: '#26a69a',
              borderColor: '#ef5350',
              borderColor0: '#26a69a'
            }
          },
          {
            name: 'MA5',
            type: 'line',
            data: this.indicators.ma5,
            smooth: true,
            lineStyle: { opacity: 0.8, color: '#FF5722' }
          },
          {
            name: 'MA10',
            type: 'line',
            data: this.indicators.ma10,
            smooth: true,
            lineStyle: { opacity: 0.8, color: '#2196F3' }
          },
          {
            name: 'MA20',
            type: 'line',
            data: this.indicators.ma20,
            smooth: true,
            lineStyle: { opacity: 0.8, color: '#4CAF50' }
          },
          {
            name: '成交量',
            type: 'bar',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: this.volumeData,
            itemStyle: { color: '#7fbe9e' }
          }
        ]
      }

      this.chart.setOption(option, true)
    }
  },
  computed: {
    dates() {
      return this.data.map(d => d.datetime)
    },
    candlestickData() {
      return this.data.map(d => [d.open, d.close, d.low, d.high])
    },
    volumeData() {
      return this.data.map(d => d.volume)
    }
  }
}
</script>

<style scoped>
.kline-chart {
  width: 100%;
  height: 500px;
}
</style>
```

---

## 六、实施计划

### 第一阶段（高优先级）

1. **核心Web框架**
   - 实现FastAPI应用创建
   - 实现统一响应格式
   - 实现异常处理

2. **策略管理API**
   - 策略上传/列表/详情/删除
   - 策略参数提取

3. **回测任务API**
   - 创建任务
   - 查询状态
   - 存储结果

### 第二阶段（中优先级）

4. **WebSocket支持**
   - 连接管理
   - 进度推送
   - 日志推送

5. **结果服务**
   - 性能指标提取
   - 图表配置生成
   - 数据导出

6. **数据服务**
   - 数据源注册
   - 数据查询API
   - 数据更新

### 第三阶段（可选）

7. **前端界面**
   - 策略管理页面
   - 回测创建页面
   - 结果展示页面

8. **高级功能**
   - 用户认证
   - 数据库持久化
   - 任务队列（Celery）
   - Docker部署

---

## 七、向后兼容性

所有Web服务均为**完全可选的独立模块**：

1. Web服务通过`pip install backtrader[web]`安装
2. 用户可以选择使用Web界面或继续使用代码方式
3. Web服务不影响backtrader核心功能
4. 提供嵌入式启动选项，可在现有应用中集成

---

## 八、使用示例

```python
# 启动Web服务
from backtrader.web import create_app

app = create_app()

# 使用uvicorn运行
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8000)

# 或嵌入到现有应用
from fastapi import FastAPI
main_app = FastAPI()
main_app.mount("/backtrader", app)
```

```bash
# 访问API文档
# http://localhost:8000/docs
```

```javascript
// 前端调用示例
import axios from 'axios'

// 创建回测
const response = await axios.post('/api/backtests', {
  strategy_id: 'str_1',
  symbol: 'AAPL',
  start_date: '2023-01-01',
  end_date: '2023-12-31',
  initial_cash: 10000
})

// WebSocket连接
const ws = new WebSocket(`ws://localhost:8000/ws/${task_id}`)
ws.onmessage = (event) => {
  const message = JSON.parse(event.data)
  if (message.event === 'progress') {
    console.log('Progress:', message.data.progress)
  }
}
```
