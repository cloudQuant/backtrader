# Backtrader 类继承关系分析报告

## 总体统计

- **总类数量**: 444
- **使用元类的类数量**: 51
- **根类数量**: 122
- **核心文件数量**: 170

## 1. 元类和元编程技术

### 1.1 元类定义

以下类定义了元类或使用了元编程技术：

- **Observer** (observer.py:47)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaObserver, ObserverBase)

- **LineActions** (linebuffer.py:652)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaLineActions, LineBuffer)

- **Store** (store.py:44)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaSingleton, object)

- **Filter** (flt.py:37)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **Cerebro** (cerebro.py:57)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **ParamsBase** (metabase.py:411)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **LineIterator** (lineiterator.py:173)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaLineIterator, LineSeries)

- **Timer** (timer.py:45)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **Sizer** (sizer.py:29)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **Indicator** (indicator.py:100)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaIndicator, IndicatorBase)

- **LinePlotterIndicator** (indicator.py:182)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MtLinePlotterIndicator, Indicator)

- **_BaseResampler** (resamplerfilter.py:116)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(metabase.MetaParams, object)

- **Analyzer** (analyzer.py:102)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaAnalyzer, object)

- **TimeFrameAnalyzerBase** (analyzer.py:350)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaTimeFrameAnalyzerBase, Analyzer)

- **OrderBase** (order.py:253)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **Strategy** (strategy.py:109)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaStrategy, StrategyBase)

- **SignalStrategy** (strategy.py:1778)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaSigStrategy, Strategy)

- **AbstractDataBase** (feed.py:131)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaAbstractDataBase, dataseries.OHLCDateTime)

- **FeedBase** (feed.py:691)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(metabase.MetaParams, object)

- **CSVDataBase** (feed.py:746)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaCSVDataBase, DataBase)

- **TradingCalendarBase** (tradingcal.py:52)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **FixedSize** (fillers.py:30)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **FixedBarPerc** (fillers.py:53)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **BarPointPerc** (fillers.py:75)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **WriterBase** (writer.py:38)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(bt.MetaParams, object)

- **LineSeries** (lineseries.py:682)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaLineSeries, LineMultiple)

- **BrokerBase** (broker.py:49)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaBroker, object)

- **_TALibIndicator** (talib.py:100)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(_MetaTALibIndicator, bt.Indicator)

- **LineRoot** (lineroot.py:63)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaLineRoot, object)

- **SessionFiller** (filters/session.py:31)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(metabase.MetaParams, object)

- **SessionFilterSimple** (filters/session.py:187)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(metabase.MetaParams, object)

- **SessionFilter** (filters/session.py:216)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(metabase.MetaParams, object)

- **CalendarDays** (filters/calendardays.py:31)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(metabase.MetaParams, object)

- **CCXTBroker** (brokers/ccxtbroker.py:53)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaCCXTBroker, BrokerBase)

- **CTPBroker** (brokers/ctpbroker.py:20)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaCTPBroker, BrokerBase)

- **OandaBroker** (brokers/oandabroker.py:60)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaOandaBroker, BrokerBase)

- **VCBroker** (brokers/vcbroker.py:70)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaVCBroker, BrokerBase)

- **IBBroker** (brokers/ibbroker.py:252)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaIBBroker, BrokerBase)

- **Plot_OldSync** (plot/plot.py:733)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaParams, object)

- **MovingAverageBase** (indicators/mabase.py:94)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaMovAvBase, Indicator)

- **OandaStore** (stores/oandastore.py:182)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaSingleton, object)

- **CCXTStore** (stores/ccxtstore.py:48)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaSingleton, object)

- **IBStore** (stores/ibstore.py:112)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaSingleton, object)

- **VCStore** (stores/vcstore.py:191)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaSingleton, object)

- **CTPStore** (stores/ctpstore.py:154)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaSingleton, object)

- **CTPData** (feeds/ctpdata.py:24)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaCTPData, DataBase)

- **IBData** (feeds/ibdata.py:45)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaIBData, DataBase)

- **CCXTFeed** (feeds/ccxtfeed.py:43)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaCCXTFeed, DataBase)

- **VCData** (feeds/vcdata.py:48)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaVCData, DataBase)

- **OandaData** (feeds/oanda.py:44)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaOandaData, DataBase)

- **DataTrades** (observers/trades.py:151)
  - 使用 with_metaclass 或其他元编程技术
  - 基类: with_metaclass(MetaDataTrades, Observer)


### 1.2 主要元类层次结构

#### MetaIndicator
- 文件: `indicator.py`
- 基类: IndicatorBase.__class__
- 使用该元类的类:
  - Indicator

#### MetaBase
- 文件: `metabase.py`
- 基类: type
- 使用该元类的类:
  - MetaParams

#### MetaLineSeries
- 文件: `lineseries.py`
- 基类: LineMultiple.__class__
- 使用该元类的类:
  - LineSeries

#### MetaLineRoot
- 文件: `lineroot.py`
- 基类: metabase.MetaParams
- 使用该元类的类:
  - LineRoot

#### MetaParams
- 文件: `metabase.py`
- 基类: MetaBase
- 使用该元类的类:
  - MetaSingleton
  - MetaFilter
  - Filter
  - Cerebro
  - ParamsBase
  - Timer
  - Sizer
  - _BaseResampler
  - MetaAnalyzer
  - OrderBase
  - ... 和其他 18 个类

#### MetaStrategy
- 文件: `strategy.py`
- 基类: StrategyBase.__class__
- 使用该元类的类:
  - Strategy

#### MetaLineIterator
- 文件: `lineiterator.py`
- 基类: LineSeries.__class__
- 使用该元类的类:
  - LineIterator

#### MetaAbstractDataBase
- 文件: `feed.py`
- 基类: dataseries.OHLCDateTime.__class__
- 使用该元类的类:
  - AbstractDataBase


## 2. 核心基类层次结构

- **LineRoot** (`lineroot.py`)
  - **LineMultiple** (`lineroot.py`)
    - **LineSeries** (`lineseries.py`)
      - **DataSeries** (`dataseries.py`)
        - **OHLC** (`dataseries.py`)
          - **OHLCDateTime** (`dataseries.py`)
            - **AbstractDataBase** (`feed.py`)
              - **DataBase** (`feed.py`)
                - **CSVDataBase** (`feed.py`)
                  - **QuandlCSV** (`feeds/quandl.py`)
                    - **Quandl** (`feeds/quandl.py`)
                  - **YahooFinanceCSVData** (`feeds/yahoo.py`)
                    - **YahooLegacyCSV** (`feeds/yahoo.py`)
                    - **YahooFinanceData** (`feeds/yahoo.py`)
                  - **GenericCSVData** (`feeds/csvgeneric.py`)
                    - **SierraChartCSVData** (`feeds/sierrachart.py`)
                    - **MT4CSVData** (`feeds/mt4csv.py`)
                  - **BacktraderCSVData** (`feeds/btcsv.py`)
                  - **VChartCSVData** (`feeds/vchartcsv.py`)
                - **CTPData** (`feeds/ctpdata.py`)
                - **PandasDirectData** (`feeds/pandafeed.py`)
                - **PandasData** (`feeds/pandafeed.py`)
                - **InfluxDB** (`feeds/influxfeed.py`)
                - ... 和其他 6 个子类
              - **DataClone** (`feed.py`)
              - **DataFilter** (`filters/datafilter.py`)
              - **DataFiller** (`filters/datafiller.py`)
      - **LineIterator** (`lineiterator.py`)
        - **DataAccessor** (`lineiterator.py`)
          - **IndicatorBase** (`lineiterator.py`)
            - **Indicator** (`indicator.py`)
              - **Signal** (`signal.py`)
              - **LinePlotterIndicator** (`indicator.py`)
              - **_TALibIndicator** (`talib.py`)
              - **UpMove** (`indicators/directionalmove.py`)
              - **DownMove** (`indicators/directionalmove.py`)
              - ... 和其他 54 个子类
          - **ObserverBase** (`lineiterator.py`)
            - **Observer** (`observer.py`)
              - **TimeReturn** (`analyzers/timereturn.py`)
                - **Benchmark** (`observers/benchmark.py`)
              - **DrawDown** (`analyzers/drawdown.py`)
              - **DrawDownLength** (`observers/drawdown.py`)
              - **DrawDown_Old** (`observers/drawdown.py`)
              - **Trades** (`observers/trades.py`)
              - ... 和其他 8 个子类
          - **StrategyBase** (`lineiterator.py`)
            - **Strategy** (`strategy.py`)
              - **SignalStrategy** (`strategy.py`)
              - **MA_CrossOver** (`strategies/sma_crossover.py`)
              - **SmaCross** (`strategies/test_backtrader_ctp.py`)
              - **SmaCross** (`strategies/test_backtrader_ctp.py`)
              - **TestStrategy** (`strategies/test_backtrader_ccxt_okex_sma.py`)
              - ... 和其他 5 个子类
        - **MultiCoupler** (`lineiterator.py`)
      - **LineSeriesStub** (`lineseries.py`)
  - **LineSingle** (`lineroot.py`)
    - **LineBuffer** (`linebuffer.py`)
      - **LineActions** (`linebuffer.py`)
        - **Logic** (`functions.py`)
          - **DivByZero** (`functions.py`)
          - **DivZeroByZero** (`functions.py`)
          - **Cmp** (`functions.py`)
          - **CmpEx** (`functions.py`)
          - **If** (`functions.py`)
          - ... 和其他 1 个子类
        - **_LineDelay** (`linebuffer.py`)
        - **_LineForward** (`linebuffer.py`)
        - **LinesOperation** (`linebuffer.py`)
        - **LineOwnOperation** (`linebuffer.py`)
        - ... 和其他 1 个子类

- **LineSingle** (`lineroot.py`)
  - **LineBuffer** (`linebuffer.py`)
    - **LineActions** (`linebuffer.py`)
      - **Logic** (`functions.py`)
        - **DivByZero** (`functions.py`)
        - **DivZeroByZero** (`functions.py`)
        - **Cmp** (`functions.py`)
        - **CmpEx** (`functions.py`)
        - **If** (`functions.py`)
        - ... 和其他 1 个子类
      - **_LineDelay** (`linebuffer.py`)
      - **_LineForward** (`linebuffer.py`)
      - **LinesOperation** (`linebuffer.py`)
      - **LineOwnOperation** (`linebuffer.py`)
      - ... 和其他 1 个子类

- **LineMultiple** (`lineroot.py`)
  - **LineSeries** (`lineseries.py`)
    - **DataSeries** (`dataseries.py`)
      - **OHLC** (`dataseries.py`)
        - **OHLCDateTime** (`dataseries.py`)
          - **AbstractDataBase** (`feed.py`)
            - **DataBase** (`feed.py`)
              - **CSVDataBase** (`feed.py`)
                - **QuandlCSV** (`feeds/quandl.py`)
                  - **Quandl** (`feeds/quandl.py`)
                - **YahooFinanceCSVData** (`feeds/yahoo.py`)
                  - **YahooLegacyCSV** (`feeds/yahoo.py`)
                  - **YahooFinanceData** (`feeds/yahoo.py`)
                - **GenericCSVData** (`feeds/csvgeneric.py`)
                  - **SierraChartCSVData** (`feeds/sierrachart.py`)
                  - **MT4CSVData** (`feeds/mt4csv.py`)
                - **BacktraderCSVData** (`feeds/btcsv.py`)
                - **VChartCSVData** (`feeds/vchartcsv.py`)
              - **CTPData** (`feeds/ctpdata.py`)
              - **PandasDirectData** (`feeds/pandafeed.py`)
              - **PandasData** (`feeds/pandafeed.py`)
              - **InfluxDB** (`feeds/influxfeed.py`)
              - ... 和其他 6 个子类
            - **DataClone** (`feed.py`)
            - **DataFilter** (`filters/datafilter.py`)
            - **DataFiller** (`filters/datafiller.py`)
    - **LineIterator** (`lineiterator.py`)
      - **DataAccessor** (`lineiterator.py`)
        - **IndicatorBase** (`lineiterator.py`)
          - **Indicator** (`indicator.py`)
            - **Signal** (`signal.py`)
            - **LinePlotterIndicator** (`indicator.py`)
            - **_TALibIndicator** (`talib.py`)
            - **UpMove** (`indicators/directionalmove.py`)
            - **DownMove** (`indicators/directionalmove.py`)
            - ... 和其他 54 个子类
        - **ObserverBase** (`lineiterator.py`)
          - **Observer** (`observer.py`)
            - **TimeReturn** (`analyzers/timereturn.py`)
              - **Benchmark** (`observers/benchmark.py`)
            - **DrawDown** (`analyzers/drawdown.py`)
            - **DrawDownLength** (`observers/drawdown.py`)
            - **DrawDown_Old** (`observers/drawdown.py`)
            - **Trades** (`observers/trades.py`)
            - ... 和其他 8 个子类
        - **StrategyBase** (`lineiterator.py`)
          - **Strategy** (`strategy.py`)
            - **SignalStrategy** (`strategy.py`)
            - **MA_CrossOver** (`strategies/sma_crossover.py`)
            - **SmaCross** (`strategies/test_backtrader_ctp.py`)
            - **SmaCross** (`strategies/test_backtrader_ctp.py`)
            - **TestStrategy** (`strategies/test_backtrader_ccxt_okex_sma.py`)
            - ... 和其他 5 个子类
      - **MultiCoupler** (`lineiterator.py`)
    - **LineSeriesStub** (`lineseries.py`)

- **LineBuffer** (`linebuffer.py`)
  - **LineActions** (`linebuffer.py`)
    - **Logic** (`functions.py`)
      - **DivByZero** (`functions.py`)
      - **DivZeroByZero** (`functions.py`)
      - **Cmp** (`functions.py`)
      - **CmpEx** (`functions.py`)
      - **If** (`functions.py`)
      - ... 和其他 1 个子类
    - **_LineDelay** (`linebuffer.py`)
    - **_LineForward** (`linebuffer.py`)
    - **LinesOperation** (`linebuffer.py`)
    - **LineOwnOperation** (`linebuffer.py`)
    - ... 和其他 1 个子类

- **LineActions** (`linebuffer.py`)
  - **Logic** (`functions.py`)
    - **DivByZero** (`functions.py`)
    - **DivZeroByZero** (`functions.py`)
    - **Cmp** (`functions.py`)
    - **CmpEx** (`functions.py`)
    - **If** (`functions.py`)
    - ... 和其他 1 个子类
  - **_LineDelay** (`linebuffer.py`)
  - **_LineForward** (`linebuffer.py`)
  - **LinesOperation** (`linebuffer.py`)
  - **LineOwnOperation** (`linebuffer.py`)
  - ... 和其他 1 个子类

- **LineSeries** (`lineseries.py`)
  - **DataSeries** (`dataseries.py`)
    - **OHLC** (`dataseries.py`)
      - **OHLCDateTime** (`dataseries.py`)
        - **AbstractDataBase** (`feed.py`)
          - **DataBase** (`feed.py`)
            - **CSVDataBase** (`feed.py`)
              - **QuandlCSV** (`feeds/quandl.py`)
                - **Quandl** (`feeds/quandl.py`)
              - **YahooFinanceCSVData** (`feeds/yahoo.py`)
                - **YahooLegacyCSV** (`feeds/yahoo.py`)
                - **YahooFinanceData** (`feeds/yahoo.py`)
              - **GenericCSVData** (`feeds/csvgeneric.py`)
                - **SierraChartCSVData** (`feeds/sierrachart.py`)
                - **MT4CSVData** (`feeds/mt4csv.py`)
              - **BacktraderCSVData** (`feeds/btcsv.py`)
              - **VChartCSVData** (`feeds/vchartcsv.py`)
            - **CTPData** (`feeds/ctpdata.py`)
            - **PandasDirectData** (`feeds/pandafeed.py`)
            - **PandasData** (`feeds/pandafeed.py`)
            - **InfluxDB** (`feeds/influxfeed.py`)
            - ... 和其他 6 个子类
          - **DataClone** (`feed.py`)
          - **DataFilter** (`filters/datafilter.py`)
          - **DataFiller** (`filters/datafiller.py`)
  - **LineIterator** (`lineiterator.py`)
    - **DataAccessor** (`lineiterator.py`)
      - **IndicatorBase** (`lineiterator.py`)
        - **Indicator** (`indicator.py`)
          - **Signal** (`signal.py`)
          - **LinePlotterIndicator** (`indicator.py`)
          - **_TALibIndicator** (`talib.py`)
          - **UpMove** (`indicators/directionalmove.py`)
          - **DownMove** (`indicators/directionalmove.py`)
          - ... 和其他 54 个子类
      - **ObserverBase** (`lineiterator.py`)
        - **Observer** (`observer.py`)
          - **TimeReturn** (`analyzers/timereturn.py`)
            - **Benchmark** (`observers/benchmark.py`)
          - **DrawDown** (`analyzers/drawdown.py`)
          - **DrawDownLength** (`observers/drawdown.py`)
          - **DrawDown_Old** (`observers/drawdown.py`)
          - **Trades** (`observers/trades.py`)
          - ... 和其他 8 个子类
      - **StrategyBase** (`lineiterator.py`)
        - **Strategy** (`strategy.py`)
          - **SignalStrategy** (`strategy.py`)
          - **MA_CrossOver** (`strategies/sma_crossover.py`)
          - **SmaCross** (`strategies/test_backtrader_ctp.py`)
          - **SmaCross** (`strategies/test_backtrader_ctp.py`)
          - **TestStrategy** (`strategies/test_backtrader_ccxt_okex_sma.py`)
          - ... 和其他 5 个子类
    - **MultiCoupler** (`lineiterator.py`)
  - **LineSeriesStub** (`lineseries.py`)

- **LineIterator** (`lineiterator.py`)
  - **DataAccessor** (`lineiterator.py`)
    - **IndicatorBase** (`lineiterator.py`)
      - **Indicator** (`indicator.py`)
        - **Signal** (`signal.py`)
        - **LinePlotterIndicator** (`indicator.py`)
        - **_TALibIndicator** (`talib.py`)
        - **UpMove** (`indicators/directionalmove.py`)
        - **DownMove** (`indicators/directionalmove.py`)
        - ... 和其他 54 个子类
    - **ObserverBase** (`lineiterator.py`)
      - **Observer** (`observer.py`)
        - **TimeReturn** (`analyzers/timereturn.py`)
          - **Benchmark** (`observers/benchmark.py`)
        - **DrawDown** (`analyzers/drawdown.py`)
        - **DrawDownLength** (`observers/drawdown.py`)
        - **DrawDown_Old** (`observers/drawdown.py`)
        - **Trades** (`observers/trades.py`)
        - ... 和其他 8 个子类
    - **StrategyBase** (`lineiterator.py`)
      - **Strategy** (`strategy.py`)
        - **SignalStrategy** (`strategy.py`)
        - **MA_CrossOver** (`strategies/sma_crossover.py`)
        - **SmaCross** (`strategies/test_backtrader_ctp.py`)
        - **SmaCross** (`strategies/test_backtrader_ctp.py`)
        - **TestStrategy** (`strategies/test_backtrader_ccxt_okex_sma.py`)
        - ... 和其他 5 个子类
  - **MultiCoupler** (`lineiterator.py`)

- **IndicatorBase** (`lineiterator.py`)
  - **Indicator** (`indicator.py`)
    - **Signal** (`signal.py`)
    - **LinePlotterIndicator** (`indicator.py`)
    - **_TALibIndicator** (`talib.py`)
    - **UpMove** (`indicators/directionalmove.py`)
    - **DownMove** (`indicators/directionalmove.py`)
    - ... 和其他 54 个子类

- **StrategyBase** (`lineiterator.py`)
  - **Strategy** (`strategy.py`)
    - **SignalStrategy** (`strategy.py`)
    - **MA_CrossOver** (`strategies/sma_crossover.py`)
    - **SmaCross** (`strategies/test_backtrader_ctp.py`)
    - **SmaCross** (`strategies/test_backtrader_ctp.py`)
    - **TestStrategy** (`strategies/test_backtrader_ccxt_okex_sma.py`)
    - ... 和其他 5 个子类

- **DataAccessor** (`lineiterator.py`)
  - **IndicatorBase** (`lineiterator.py`)
    - **Indicator** (`indicator.py`)
      - **Signal** (`signal.py`)
      - **LinePlotterIndicator** (`indicator.py`)
      - **_TALibIndicator** (`talib.py`)
      - **UpMove** (`indicators/directionalmove.py`)
      - **DownMove** (`indicators/directionalmove.py`)
      - ... 和其他 54 个子类
  - **ObserverBase** (`lineiterator.py`)
    - **Observer** (`observer.py`)
      - **TimeReturn** (`analyzers/timereturn.py`)
        - **Benchmark** (`observers/benchmark.py`)
      - **DrawDown** (`analyzers/drawdown.py`)
      - **DrawDownLength** (`observers/drawdown.py`)
      - **DrawDown_Old** (`observers/drawdown.py`)
      - **Trades** (`observers/trades.py`)
      - ... 和其他 8 个子类
  - **StrategyBase** (`lineiterator.py`)
    - **Strategy** (`strategy.py`)
      - **SignalStrategy** (`strategy.py`)
      - **MA_CrossOver** (`strategies/sma_crossover.py`)
      - **SmaCross** (`strategies/test_backtrader_ctp.py`)
      - **SmaCross** (`strategies/test_backtrader_ctp.py`)
      - **TestStrategy** (`strategies/test_backtrader_ccxt_okex_sma.py`)
      - ... 和其他 5 个子类


## 3. 按功能分类的类统计

### Core/Meta
- 类数量: 31
- 主要文件: linebuffer.py, metabase.py, lineiterator.py, lineseries.py, lineroot.py

### Strategy
- 类数量: 4
- 主要文件: strategy.py

### Indicators
- 类数量: 132
- 主要文件: indicator.py, indicators/directionalmove.py, indicators/rmi.py, indicators/zlind.py, indicators/awesomeoscillator.py
- ... 和其他 46 个文件

### Data/Feeds
- 类数量: 51
- 主要文件: dataseries.py, feed.py, feeds/sierrachart.py, feeds/ctpdata.py, feeds/rollover.py
- ... 和其他 16 个文件

### Broker
- 类数量: 24
- 主要文件: broker.py, brokers/ccxtbroker.py, brokers/ctpbroker.py, brokers/oandabroker.py, brokers/vcbroker.py
- ... 和其他 3 个文件

### Analysis
- 类数量: 23
- 主要文件: analyzer.py, analyzers/calmar.py, analyzers/periodstats.py, analyzers/sqn.py, analyzers/tradeanalyzer.py
- ... 和其他 12 个文件

### Observers
- 类数量: 18
- 主要文件: observer.py, observers/benchmark.py, observers/timereturn.py, observers/drawdown.py, observers/trades.py
- ... 和其他 3 个文件

### Engine
- 类数量: 2
- 主要文件: cerebro.py

### Utilities
- 类数量: 49
- 主要文件: plot/plot.py, plot/finance.py, plot/formatters.py, plot/multicursor.py, plot/locator.py
- ... 和其他 15 个文件


## 4. 详细类列表 (按文件分组)

### analyzer.py

#### MetaAnalyzer
- **基类**: bt.MetaParams

#### Analyzer
- **基类**: with_metaclass(MetaAnalyzer, object)
- **使用元类**: 是
- **说明**: Analyzer base class. All analyzers are subclass of this one

An Analyzer instance operates in the frame of a strategy and provides an
analysis for that strategy.

# analyzer类，所有的analyzer都是这个类的基类，一个ana...
- **关键方法**: next, prenext

#### MetaTimeFrameAnalyzerBase
- **基类**: Analyzer.__class__
- **关键方法**: __new__

#### TimeFrameAnalyzerBase
- **基类**: with_metaclass(MetaTimeFrameAnalyzerBase, Analyzer)
- **使用元类**: 是


### analyzers/annualreturn.py

#### AnnualReturn
- **基类**: Analyzer
- **说明**: This analyzer calculates the AnnualReturns by looking at the beginning
and end of the year

Params:

  - (None)

Member Attributes:

  - ``rets``: list of calculated annual returns

  - ``ret``: dicti...

#### MyAnnualReturn
- **基类**: Analyzer
- **说明**: This analyzer calculates the AnnualReturns by looking at the beginning
and end of the year

Params:

  - (None)

Member Attributes:

  - ``rets``: list of calculated annual returns

  - ``ret``: dicti...


### analyzers/calmar.py

#### Calmar
- **基类**: bt.TimeFrameAnalyzerBase
- **说明**: This analyzer calculates the CalmarRatio
timeframe which can be different from the one used in the underlying data
Params:

  - ``timeframe`` (default: ``None``)
    If ``None`` the ``timeframe`` of t...
- **关键方法**: __init__


### analyzers/drawdown.py

#### DrawDown
- **基类**: bt.Analyzer
- **说明**: This analyzer calculates trading system drawdowns stats such as drawdown
values in %s and in dollars, max drawdown in %s and in dollars, drawdown
length and drawdown max length

Params:

  - ``fund`` ...
- **关键方法**: next

#### TimeDrawDown
- **基类**: bt.TimeFrameAnalyzerBase
- **说明**: This analyzer calculates trading system drawdowns on the chosen
timeframe which can be different from the one used in the underlying data
Params:

  - ``timeframe`` (default: ``None``)
    If ``None``...


### analyzers/leverage.py

#### GrossLeverage
- **基类**: bt.Analyzer
- **说明**: This analyzer calculates the Gross Leverage of the current strategy
on a timeframe basis

Params:

  - ``fund`` (default: ``None``)

    If ``None`` the actual mode of the broker (fundmode - True/Fals...
- **关键方法**: next


### analyzers/logreturnsrolling.py

#### LogReturnsRolling
- **基类**: bt.TimeFrameAnalyzerBase
- **说明**: This analyzer calculates rolling returns for a given timeframe and
compression

Params:

  - ``timeframe`` (default: ``None``)
    If ``None`` the ``timeframe`` of the 1st data in the system will be
 ...
- **关键方法**: next


### analyzers/periodstats.py

#### PeriodStats
- **基类**: bt.Analyzer
- **说明**: Calculates basic statistics for given timeframe

Params:

  - ``timeframe`` (default: ``Years``)
    If ``None`` the ``timeframe`` of the 1st data in the system will be
    used

    Pass ``TimeFrame....
- **关键方法**: __init__


### analyzers/positions.py

#### PositionsValue
- **基类**: bt.Analyzer
- **说明**: This analyzer reports the value of the positions of the current set of
datas

Params:

  - timeframe (default: ``None``)
    If ``None`` then the timeframe of the 1st data of the system will be
    us...
- **关键方法**: next


### analyzers/pyfolio.py

#### PyFolio
- **基类**: bt.Analyzer
- **说明**: This analyzer uses 4 children analyzers to collect data and transforms it
in to a data set compatible with ``pyfolio``

Children Analyzer

  - ``TimeReturn``

    Used to calculate the returns of the ...
- **关键方法**: __init__


### analyzers/returns.py

#### Returns
- **基类**: TimeFrameAnalyzerBase
- **说明**: Total, Average, Compound and Annualized Returns calculated using a
logarithmic approach

See:

  - https://www.crystalbull.com/sharpe-ratio-better-with-log-returns/

Params:

  - ``timeframe`` (defaul...


### analyzers/sharpe.py

#### SharpeRatio
- **基类**: Analyzer
- **说明**: This analyzer calculates the SharpeRatio of a strategy using a risk-free
asset which is simply an interest rate

See also:

  - https://en.wikipedia.org/wiki/Sharpe_ratio

Params:

  - ``timeframe``: ...
- **关键方法**: __init__

#### SharpeRatioA
- **基类**: SharpeRatio
- **说明**: Extension of the SharpeRatio which returns the Sharpe Ratio directly in
annualized form

The following param has been changed from ``SharpeRatio``

  - ``annualize`` (default: ``True``)


### analyzers/sqn.py

#### SQN
- **基类**: Analyzer
- **说明**: SQN or SystemQualityNumber. Defined by Van K. Tharp to categorize trading
systems.

  - 1.6 - 1.9 Below average
  - 2.0 - 2.4 Average
  - 2.5 - 2.9 Good
  - 3.0 - 5.0 Excellent
  - 5.1 - 6.9 Superb
  ...


### analyzers/timereturn.py

#### TimeReturn
- **基类**: TimeFrameAnalyzerBase
- **说明**: This analyzer calculates the Returns by looking at the beginning
and end of the timeframe

Params:

  - ``timeframe`` (default: ``None``)
    If ``None`` the ``timeframe`` of the 1st data in the syste...
- **关键方法**: next


### analyzers/total_value.py

#### TotalValue
- **基类**: Analyzer
- **说明**: This analyzer will get total value from every next.

Params:
Methods:

  - get_analysis

    Returns a dictionary with returns as values and the datetime points for
    each return as keys
- **关键方法**: next


### analyzers/tradeanalyzer.py

#### TradeAnalyzer
- **基类**: Analyzer
- **说明**: Provides statistics on closed trades (keeps also the count of open ones)

  - Total Open/Closed Trades

  - Streak Won/Lost Current/Longest

  - ProfitAndLoss Total/Average

  - Won/Lost Count/ Total ...


### analyzers/transactions.py

#### Transactions
- **基类**: bt.Analyzer
- **说明**: This analyzer reports the transactions occurred with each an every data in
the system

It looks at the order execution bits to create a ``Position`` starting from
0 during each ``next`` cycle.

The re...
- **关键方法**: next


### analyzers/vwr.py

#### VWR
- **基类**: TimeFrameAnalyzerBase
- **说明**: Variability-Weighted Return: Better SharpeRatio with Log Returns

Alias:

  - VariabilityWeightedReturn

See:

  - https://www.crystalbull.com/sharpe-ratio-better-with-log-returns/

Params:

  - ``tim...
- **关键方法**: __init__


### broker.py

#### MetaBroker
- **基类**: MetaParams
- **关键方法**: __init__

#### BrokerBase
- **基类**: with_metaclass(MetaBroker, object)
- **使用元类**: 是
- **关键方法**: __init__, next


### brokers/bbroker.py

#### BackBroker
- **基类**: bt.BrokerBase
- **说明**: Broker Simulator

The simulation supports different order types, checking a submitted order
cash requirements against current cash, keeping track of cash and value
for each iteration of ``cerebro`` an...
- **关键方法**: __init__, next


### brokers/ccxtbroker.py

#### CCXTOrder
- **基类**: Order
- **关键方法**: __init__

#### MetaCCXTBroker
- **基类**: BrokerBase.__class__
- **关键方法**: __init__

#### CCXTBroker
- **基类**: with_metaclass(MetaCCXTBroker, BrokerBase)
- **使用元类**: 是
- **说明**: Broker implementation for CCXT cryptocurrency trading library.
This class maps the orders/positions from CCXT to the
internal API of ``backtrader``.

Broker mapping added as I noticed that there diffe...
- **关键方法**: __init__, next


### brokers/ctpbroker.py

#### MetaCTPBroker
- **基类**: BrokerBase.__class__
- **关键方法**: __init__

#### CTPBroker
- **基类**: with_metaclass(MetaCTPBroker, BrokerBase)
- **使用元类**: 是
- **说明**: Broker implementation for ctp

This class maps the orders/positions from MetaTrader to the
internal API of `backtrader`.

Params:

  - `use_positions` (default:`False`): When connecting to the broker
...
- **关键方法**: __init__, next


### brokers/ibbroker.py

#### IBOrderState
- **基类**: object
- **关键方法**: __init__

#### IBOrder
- **基类**: OrderBase, ib.ext.Order.Order
- **说明**: Subclasses the IBPy order to provide the minimum extra functionality
needed to be compatible with the internally defined orders

Once ``OrderBase`` has processed the parameters, the __init__ method ta...
- **关键方法**: __init__

#### IBCommInfo
- **基类**: CommInfoBase
- **说明**: Commissions are calculated by ib, but the trades calculations in the
```Strategy`` rely on the order carrying a CommInfo object attached for the
calculation of the operation cost and value.

These are...

#### MetaIBBroker
- **基类**: BrokerBase.__class__
- **关键方法**: __init__

#### IBBroker
- **基类**: with_metaclass(MetaIBBroker, BrokerBase)
- **使用元类**: 是
- **说明**: Broker implementation for Interactive Brokers.

This class maps the orders/positions from Interactive Brokers to the
internal API of ``backtrader``.

Notes:

  - ``tradeid`` is not really supported, b...
- **关键方法**: __init__, next


### brokers/oandabroker.py

#### OandaCommInfo
- **基类**: CommInfoBase

#### MetaOandaBroker
- **基类**: BrokerBase.__class__
- **关键方法**: __init__

#### OandaBroker
- **基类**: with_metaclass(MetaOandaBroker, BrokerBase)
- **使用元类**: 是
- **说明**: Broker implementation for Oanda.

This class maps the orders/positions from Oanda to the
internal API of ``backtrader``.

Params:

  - ``use_positions`` (default:``True``): When connecting to the brok...
- **关键方法**: __init__, next


### brokers/vcbroker.py

#### VCCommInfo
- **基类**: CommInfoBase
- **说明**: Commissions are calculated by ib, but the trades calculations in the
```Strategy`` rely on the order carrying a CommInfo object attached for the
calculation of the operation cost and value.

These are...

#### MetaVCBroker
- **基类**: BrokerBase.__class__
- **关键方法**: __init__

#### VCBroker
- **基类**: with_metaclass(MetaVCBroker, BrokerBase)
- **使用元类**: 是
- **说明**: Broker implementation for VisualChart.

This class maps the orders/positions from VisualChart to the
internal API of ``backtrader``.

Params:

  - ``account`` (default: None)

    VisualChart supports...
- **关键方法**: __init__, next, __call__


### cerebro.py

#### OptReturn
- **基类**: object
- **关键方法**: __init__

#### Cerebro
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **说明**: Params:

- ``preload`` (default: ``True``)

  Whether to preload the different ``data feeds`` passed to cerebro for
  the Strategies

  # preload这个参数默认的是True，就意味着，在回测的时候，默认是先把数据加载之后传给cerebro，在内存中调用，
 ...
- **关键方法**: __init__, __call__


### comminfo.py

#### CommInfoBase
- **说明**: Base Class for the Commission Schemes.

Params:

  - ``commission`` (def: ``0.0``): base commission value in percentage or
    monetary units

    # 基础佣金，以百分比形式或者货币单位形式

  - ``mult`` (def ``1.0``): mu...
- **关键方法**: __init__

#### CommissionInfo
- **基类**: CommInfoBase
- **说明**: Base Class for the actual Commission Schemes.

CommInfoBase was created to keep support for the original, incomplete,
support provided by *backtrader*. New commission schemes derive from this
class wh...

#### ComminfoDC
- **基类**: CommInfoBase

#### ComminfoFuturesPercent
- **基类**: CommInfoBase

#### ComminfoFuturesFixed
- **基类**: CommInfoBase

#### ComminfoFundingRate
- **基类**: CommInfoBase
- **关键方法**: __init__


### commissions/__init__.py

#### CommInfo
- **基类**: CommInfoBase

#### CommInfo_Futures
- **基类**: CommInfoBase

#### CommInfo_Futures_Perc
- **基类**: CommInfo_Futures

#### CommInfo_Futures_Fixed
- **基类**: CommInfo_Futures

#### CommInfo_Stocks
- **基类**: CommInfoBase

#### CommInfo_Stocks_Perc
- **基类**: CommInfo_Stocks

#### CommInfo_Stocks_Fixed
- **基类**: CommInfo_Stocks


### commissions/dc_commission.py

#### ComminfoDC
- **基类**: bt.CommInfoBase
- **说明**: 实现一个数字货币的佣金类
    


### dataseries.py

#### TimeFrame
- **基类**: object

#### DataSeries
- **基类**: LineSeries

#### OHLC
- **基类**: DataSeries

#### OHLCDateTime
- **基类**: OHLC

#### SimpleFilterWrapper
- **基类**: object
- **说明**: Wrapper for filters added via .addfilter to turn them
into processors.

Filters are callables which

  - Take a ``data`` as an argument
  - Return False if the current bar has not triggered the filter...
- **关键方法**: __init__, __call__

#### _Bar
- **基类**: AutoOrderedDict
- **说明**: This class is a placeholder for the values of the standard lines of a
DataBase class (from OHLCDateTime)

It inherits from AutoOrderedDict to be able to easily return the values as
an iterable and add...
- **关键方法**: __init__


### errors.py

#### BacktraderError
- **基类**: Exception
- **说明**: Base exception for all other exceptions

#### StrategySkipError
- **基类**: BacktraderError
- **说明**: Requests the platform to skip this strategy for backtesting. To be
raised during the initialization (``__init__``) phase of the instance

#### ModuleImportError
- **基类**: BacktraderError
- **说明**: Raised if a class requests a module to be present to work and it cannot
be imported
- **关键方法**: __init__

#### FromModuleImportError
- **基类**: ModuleImportError
- **说明**: Raised if a class requests a module to be present to work and it cannot
be imported
- **关键方法**: __init__


### feed.py

#### MetaAbstractDataBase
- **基类**: dataseries.OHLCDateTime.__class__
- **关键方法**: __init__

#### AbstractDataBase
- **基类**: with_metaclass(MetaAbstractDataBase, dataseries.OHLCDateTime)
- **使用元类**: 是
- **关键方法**: next

#### DataBase
- **基类**: AbstractDataBase

#### FeedBase
- **基类**: with_metaclass(metabase.MetaParams, object)
- **使用元类**: 是
- **关键方法**: __init__

#### MetaCSVDataBase
- **基类**: DataBase.__class__

#### CSVDataBase
- **基类**: with_metaclass(MetaCSVDataBase, DataBase)
- **使用元类**: 是
- **说明**: Base class for classes implementing CSV DataFeeds

The class takes care of opening the file, reading the lines and
tokenizing them.

Subclasses do only need to override:

  - _loadline(tokens)

The re...

#### CSVFeedBase
- **基类**: FeedBase

#### DataClone
- **基类**: AbstractDataBase
- **关键方法**: __init__


### feeds/blaze.py

#### BlazeData
- **基类**: feed.DataBase
- **说明**: Support for `Blaze <blaze.pydata.org>`_ ``Data`` objects.

Only numeric indices to columns are supported.

Note:

  - The ``dataname`` parameter is a blaze ``Data`` object

  - A negative value in any...


### feeds/btcsv.py

#### BacktraderCSVData
- **基类**: feed.CSVDataBase
- **说明**: Parses a self-defined CSV Data used for testing.

Specific parameters:

  - ``dataname``: The filename to parse or a file-like object

#### BacktraderCSV
- **基类**: feed.CSVFeedBase


### feeds/ccxtfeed.py

#### MetaCCXTFeed
- **基类**: DataBase.__class__
- **关键方法**: __init__

#### CCXTFeed
- **基类**: with_metaclass(MetaCCXTFeed, DataBase)
- **使用元类**: 是
- **说明**: CryptoCurrency eXchange Trading Library Data Feed.
Params:
  - ``historical`` (default: ``False``)
    If set to ``True`` the data feed will stop after doing the first
    download of data.
    The st...
- **关键方法**: __init__


### feeds/chainer.py

#### MetaChainer
- **基类**: bt.DataBase.__class__
- **关键方法**: __init__

#### Chainer
- **基类**: <ast.Call object at 0x1057a7ee0>
- **说明**: Class that chains datas
- **关键方法**: __init__


### feeds/csvgeneric.py

#### GenericCSVData
- **基类**: feed.CSVDataBase
- **说明**: Parses a CSV file according to the order and field presence defined by the
parameters

Specific parameters (or specific meaning):

  - ``dataname``: The filename to parse or a file-like object

  - Th...

#### GenericCSV
- **基类**: feed.CSVFeedBase


### feeds/ctpdata.py

#### MetaCTPData
- **基类**: DataBase.__class__
- **关键方法**: __init__

#### CTPData
- **基类**: with_metaclass(MetaCTPData, DataBase)
- **使用元类**: 是
- **说明**: CTP Data Feed.

Params:

  - `historical` (default: `False`)

    If set to `True` the data feed will stop after doing the first
    download of data.

    The standard data feed parameters `fromdate`...
- **关键方法**: __init__


### feeds/ibdata.py

#### MetaIBData
- **基类**: DataBase.__class__
- **关键方法**: __init__

#### IBData
- **基类**: with_metaclass(MetaIBData, DataBase)
- **使用元类**: 是
- **说明**: Interactive Brokers Data Feed.
# 获取数据的时候，支持的dataname格式
Supports the following contract specifications in parameter ``dataname``:

      - TICKER  # Stock type and SMART exchange
      - TICKER-STK  # ...
- **关键方法**: __init__


### feeds/influxfeed.py

#### InfluxDB
- **基类**: feed.DataBase


### feeds/mt4csv.py

#### MT4CSVData
- **基类**: GenericCSVData
- **说明**: Parses a `Metatrader4 <https://www.metaquotes.net/en/metatrader4>`_ History
center CSV exported file.

Specific parameters (or specific meaning):

  - ``dataname``: The filename to parse or a file-lik...


### feeds/oanda.py

#### MetaOandaData
- **基类**: DataBase.__class__
- **关键方法**: __init__

#### OandaData
- **基类**: with_metaclass(MetaOandaData, DataBase)
- **使用元类**: 是
- **说明**: Oanda Data Feed.

Params:

  - ``qcheck`` (default: ``0.5``)

    Time in seconds to wake up if no data is received to give a chance to
    resample/replay packets properly and pass notifications up t...
- **关键方法**: __init__


### feeds/pandafeed.py

#### PandasDirectData
- **基类**: feed.DataBase
- **说明**: Uses a Pandas DataFrame as the feed source, iterating directly over the
tuples returned by "itertuples".

This means that all parameters related to lines must have numeric
values as indices into the t...

#### PandasData
- **基类**: feed.DataBase
- **说明**: Uses a Pandas DataFrame as the feed source, using indices into column
names (which can be "numeric")

This means that all parameters related to lines must have numeric
values as indices into the tuple...
- **关键方法**: __init__


### feeds/quandl.py

#### QuandlCSV
- **基类**: feed.CSVDataBase
- **说明**: Parses pre-downloaded Quandl CSV Data Feeds (or locally generated if they
comply to the Quandl format)

Specific parameters:

  - ``dataname``: The filename to parse or a file-like object

  - ``rever...

#### Quandl
- **基类**: QuandlCSV
- **说明**: Executes a direct download of data from Quandl servers for the given time
range.

Specific parameters (or specific meaning):

  - ``dataname``

    The ticker to download ('YHOO' for example)

  - ``b...


### feeds/rollover.py

#### MetaRollOver
- **基类**: bt.DataBase.__class__
- **关键方法**: __init__

#### RollOver
- **基类**: <ast.Call object at 0x1057b40a0>
- **说明**: Class that rolls over to the next future when a condition is met

Params:

    - ``checkdate`` (default: ``None``)

      This must be a *callable* with the following signature::

        checkdate(dt...
- **关键方法**: __init__


### feeds/sierrachart.py

#### SierraChartCSVData
- **基类**: GenericCSVData
- **说明**: Parses a `SierraChart <http://www.sierrachart.com>`_ CSV exported file.

Specific parameters (or specific meaning):

  - ``dataname``: The filename to parse or a file-like object

  - Uses GenericCSVD...


### feeds/vcdata.py

#### MetaVCData
- **基类**: DataBase.__class__
- **关键方法**: __init__

#### VCData
- **基类**: with_metaclass(MetaVCData, DataBase)
- **使用元类**: 是
- **说明**: VisualChart Data Feed.

Params:

  - ``qcheck`` (default: ``0.5``)
    Default timeout for waking up to let a resampler/replayer that the
    current bar can be check for due delivery

    The value i...
- **关键方法**: __init__


### feeds/vchart.py

#### VChartData
- **基类**: feed.DataBase
- **说明**: Support for `Visual Chart <www.visualchart.com>`_ binary on-disk files for
both daily and intradaily formats.

Note:

  - ``dataname``: to file or open file-like object

    If a file-like object is p...

#### VChartFeed
- **基类**: feed.FeedBase


### feeds/vchartcsv.py

#### VChartCSVData
- **基类**: feed.CSVDataBase
- **说明**: Parses a `VisualChart <http://www.visualchart.com>`_ CSV exported file.

Specific parameters (or specific meaning):

  - ``dataname``: The filename to parse or a file-like object

#### VChartCSV
- **基类**: feed.CSVFeedBase


### feeds/vchartfile.py

#### MetaVChartFile
- **基类**: bt.DataBase.__class__
- **关键方法**: __init__

#### VChartFile
- **基类**: <ast.Call object at 0x1058339a0>
- **说明**: Support for `Visual Chart <www.visualchart.com>`_ binary on-disk files for
both daily and intradaily formats.

Note:

  - ``dataname``: Market code displayed by Visual Chart. Example: 015ES for
    Eu...


### feeds/yahoo.py

#### YahooFinanceCSVData
- **基类**: feed.CSVDataBase
- **说明**: Parses pre-downloaded Yahoo CSV Data Feeds (or locally generated if they
comply to the Yahoo format)
# 处理预下载的雅虎csv格式的数据或者说本地产生的符合雅虎格式的数据
Specific parameters:
# 特殊的参数：
  - ``dataname``: The filename to...

#### YahooLegacyCSV
- **基类**: YahooFinanceCSVData
- **说明**: This is intended to load files which were downloaded before Yahoo
discontinued the original service in May-2017
# 用于load 2017年5月之前下载的数据

#### YahooFinanceCSV
- **基类**: feed.CSVFeedBase

#### YahooFinanceData
- **基类**: YahooFinanceCSVData
- **说明**: Executes a direct download of data from Yahoo servers for the given time
range.

Specific parameters (or specific meaning):

  - ``dataname``

    The ticker to download ('YHOO' for Yahoo own stock qu...

#### YahooFinance
- **基类**: feed.CSVFeedBase


### fillers.py

#### FixedSize
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **说明**: Returns the execution size for a given order using a *percentage* of the
volume in a bar.

This percentage is set with the parameter ``perc``

Params:

  - ``size`` (default: ``None``)  maximum size t...
- **关键方法**: __call__

#### FixedBarPerc
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **说明**: Returns the execution size for a given order using a *percentage* of the
volume in a bar.

This percentage is set with the parameter ``perc``

Params:

  - ``perc`` (default: ``100.0``) (valied values...
- **关键方法**: __call__

#### BarPointPerc
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **说明**: Returns the execution size for a given order. The volume will be
distributed uniformly in the range *high*-*low* using ``minmov`` to
partition.

From the allocated volume for the given price, the ``pe...
- **关键方法**: __call__


### filters/bsplitter.py

#### DaySplitter_Close
- **基类**: <ast.Call object at 0x10579f070>
- **说明**: Splits a daily bar in two parts simulating 2 ticks which will be used to
replay the data:

  - First tick: ``OHLX``

    The ``Close`` will be replaced by the *average* of ``Open``, ``High``
    and `...
- **关键方法**: __init__, __call__


### filters/calendardays.py

#### CalendarDays
- **基类**: with_metaclass(metabase.MetaParams, object)
- **使用元类**: 是
- **说明**: Bar Filler to add missing calendar days to trading days

Params:

  - fill_price (def: None):

    > 0: The given value to fill
    0 or None: Use the last known closing price
    -1: Use the midpoint...
- **关键方法**: __init__, __call__


### filters/datafiller.py

#### DataFiller
- **基类**: AbstractDataBase
- **说明**: This class will fill gaps in the source data using the following
information bits from the underlying data source

  - timeframe and compression to dimension the output bars

  - sessionstart and sess...


### filters/datafilter.py

#### DataFilter
- **基类**: bt.AbstractDataBase
- **说明**: This class filters out bars from a given data source. In addition to the
standard parameters of a DataBase it takes a ``funcfilter`` parameter which
can be any callable

Logic:

  - ``funcfilter`` wil...


### filters/daysteps.py

#### BarReplayer_Open
- **基类**: object
- **说明**: This filters splits a bar in two parts:

  - ``Open``: the opening price of the bar will be used to deliver an
    initial price bar in which the four components (OHLC) are equal

    The volume/openi...
- **关键方法**: __init__, __call__


### filters/heikinashi.py

#### HeikinAshi
- **基类**: object
- **说明**: The filter remodels the open, high, low, close to make HeikinAshi
candlesticks

See:
  - https://en.wikipedia.org/wiki/Candlestick_chart#Heikin_Ashi_candlesticks
  - http://stockcharts.com/school/doku...
- **关键方法**: __init__, __call__


### filters/renko.py

#### Renko
- **基类**: Filter
- **说明**: Modify the data stream to draw Renko bars (or bricks)

Params:

  - ``hilo`` (default: *False*) Use high and low instead of close to decide
    if a new brick is needed

  - ``size`` (default: *None*)...
- **关键方法**: next


### filters/session.py

#### SessionFiller
- **基类**: with_metaclass(metabase.MetaParams, object)
- **使用元类**: 是
- **说明**: Bar Filler for a Data Source inside the declared session start/end times.

The fill bars are constructed using the declared Data Source ``timeframe``
and ``compression`` (used to calculate the interve...
- **关键方法**: __init__, __call__

#### SessionFilterSimple
- **基类**: with_metaclass(metabase.MetaParams, object)
- **使用元类**: 是
- **说明**: This class can be applied to a data source as a filter and will filter out
intraday bars which fall outside of the regular session times (ie: pre/post
market data)

This is a "simple" filter and must ...
- **关键方法**: __init__, __call__

#### SessionFilter
- **基类**: with_metaclass(metabase.MetaParams, object)
- **使用元类**: 是
- **说明**: This class can be applied to a data source as a filter and will filter out
intraday bars which fall outside of the regular session times (ie: pre/post
market data)

This is a "non-simple" filter and m...
- **关键方法**: __init__, __call__


### flt.py

#### MetaFilter
- **基类**: MetaParams

#### Filter
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **关键方法**: __init__, __call__, next


### functions.py

#### List
- **基类**: list

#### Logic
- **基类**: LineActions
- **关键方法**: __init__

#### DivByZero
- **基类**: Logic
- **说明**: This operation is a Lines object and fills it values by executing a
division on the numerator / denominator arguments and avoiding a division
by zero exception by checking the denominator

Params:
  -...
- **关键方法**: __init__, next, once

#### DivZeroByZero
- **基类**: Logic
- **说明**: This operation is a Lines object and fills it values by executing a
division on the numerator / denominator arguments and avoiding a division
by zero exception or an indetermination by checking the
de...
- **关键方法**: __init__, next, once

#### Cmp
- **基类**: Logic
- **关键方法**: __init__, next, once

#### CmpEx
- **基类**: Logic
- **关键方法**: __init__, next, once

#### If
- **基类**: Logic
- **关键方法**: __init__, next, once

#### MultiLogic
- **基类**: Logic
- **关键方法**: next, once

#### MultiLogicReduce
- **基类**: MultiLogic
- **关键方法**: __init__

#### Reduce
- **基类**: MultiLogicReduce
- **关键方法**: __init__

#### And
- **基类**: MultiLogicReduce

#### Or
- **基类**: MultiLogicReduce

#### Max
- **基类**: MultiLogic

#### Min
- **基类**: MultiLogic

#### Sum
- **基类**: MultiLogic

#### Any
- **基类**: MultiLogic

#### All
- **基类**: MultiLogic


### indicator.py

#### MetaIndicator
- **基类**: IndicatorBase.__class__
- **关键方法**: __call__, __init__

#### Indicator
- **基类**: with_metaclass(MetaIndicator, IndicatorBase)
- **使用元类**: 是

#### MtLinePlotterIndicator
- **基类**: Indicator.__class__

#### LinePlotterIndicator
- **基类**: with_metaclass(MtLinePlotterIndicator, Indicator)
- **使用元类**: 是


### indicators/accdecoscillator.py

#### AccelerationDecelerationOscillator
- **基类**: bt.Indicator
- **说明**: Acceleration/Deceleration Technical Indicator (AC) measures acceleration
and deceleration of the current driving force. This indicator will change
direction before any changes in the driving force, wh...
- **关键方法**: __init__


### indicators/aroon.py

#### _AroonBase
- **基类**: Indicator
- **说明**: Base class which does the calculation of the AroonUp/AroonDown values and
defines the common parameters.

It uses the class attributes _up and _down (boolean flags) to decide which
value has to be cal...
- **关键方法**: __init__

#### AroonUp
- **基类**: _AroonBase
- **说明**: This is the AroonUp from the indicator AroonUpDown developed by Tushar
Chande in 1995.

Formula:
  - up = 100 * (period - distance to highest high) / period

Note:
  The lines oscillate between 0 and ...
- **关键方法**: __init__

#### AroonDown
- **基类**: _AroonBase
- **说明**: This is the AroonDown from the indicator AroonUpDown developed by Tushar
Chande in 1995.

Formula:
  - down = 100 * (period - distance to lowest low) / period

Note:
  The lines oscillate between 0 an...
- **关键方法**: __init__

#### AroonUpDown
- **基类**: AroonUp, AroonDown
- **说明**: Developed by Tushar Chande in 1995.

It tries to determine if a trend exists or not by calculating how far away
within a given period the last highs/lows are (AroonUp/AroonDown)

Formula:
  - up = 100...

#### AroonOscillator
- **基类**: _AroonBase
- **说明**: It is a variation of the AroonUpDown indicator which shows the current
difference between the AroonUp and AroonDown value, trying to present a
visualization which indicates which is stronger (greater ...
- **关键方法**: __init__

#### AroonUpDownOscillator
- **基类**: AroonUpDown, AroonOscillator
- **说明**: Presents together the indicators AroonUpDown and AroonOsc

Formula:
  (None, uses the aforementioned indicators)

See:
  - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:a...


### indicators/atr.py

#### TrueHigh
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* for the ATR

Records the "true high" which is the maximum of today's high and
yesterday's close

Form...
- **关键方法**: __init__

#### TrueLow
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* for the ATR

Records the "true low" which is the minimum of today's low and
yesterday's close

Formul...
- **关键方法**: __init__

#### TrueRange
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book New Concepts in
Technical Trading Systems.

Formula:
  - max(high - low, abs(high - prev_close), abs(prev_close - low)

  which can be simplified t...
- **关键方法**: __init__

#### AverageTrueRange
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

The idea is to take the close into account to calculate the range if it
yields a larger range than ...
- **关键方法**: __init__


### indicators/awesomeoscillator.py

#### AwesomeOscillator
- **基类**: bt.Indicator
- **说明**: Awesome Oscillator (AO) is a momentum indicator reflecting the precise
changes in the market driving force which helps to identify the trend’s
strength up to the points of formation and reversal.


Fo...
- **关键方法**: __init__


### indicators/basicops.py

#### PeriodN
- **基类**: Indicator
- **说明**: Base class for indicators which take a period (__init__ has to be called
either via super or explicitly)

This class has no defined lines
- **关键方法**: __init__

#### OperationN
- **基类**: PeriodN
- **说明**: Calculates "func" for a given period

Serves as a base for classes that work with a period and can express the
logic in a callable object

Note:
  Base classes must provide a "func" attribute which is...
- **关键方法**: next, once

#### BaseApplyN
- **基类**: OperationN
- **说明**: Base class for ApplyN and others which may take a ``func`` as a parameter
but want to define the lines in the indicator.

Calculates ``func`` for a given period where func is given as a parameter,
aka...
- **关键方法**: __init__

#### ApplyN
- **基类**: BaseApplyN
- **说明**: Calculates ``func`` for a given period

Formula:
  - line = func(data, period)

#### Highest
- **基类**: OperationN
- **说明**: Calculates the highest value for the data in a given period

Uses the built-in ``max`` for the calculation

Formula:
  - highest = max(data, period)

#### Lowest
- **基类**: OperationN
- **说明**: Calculates the lowest value for the data in a given period

Uses the built-in ``min`` for the calculation

Formula:
  - lowest = min(data, period)

#### ReduceN
- **基类**: OperationN
- **说明**: Calculates the Reduced value of the ``period`` data points applying
``function``

Uses the built-in ``reduce`` for the calculation plus the ``func`` that
subclassess define

Formula:
  - reduced = red...
- **关键方法**: __init__

#### SumN
- **基类**: OperationN
- **说明**: Calculates the Sum of the data values over a given period

Uses ``math.fsum`` for the calculation rather than the built-in ``sum`` to
avoid precision errors

Formula:
  - sumn = sum(data, period)

#### AnyN
- **基类**: OperationN
- **说明**: Has a value of ``True`` (stored as ``1.0`` in the lines) if *any* of the
values in the ``period`` evaluates to non-zero (ie: ``True``)

Uses the built-in ``any`` for the calculation

Formula:
  - anyn...

#### AllN
- **基类**: OperationN
- **说明**: Has a value of ``True`` (stored as ``1.0`` in the lines) if *all* of the
values in the ``period`` evaluates to non-zero (ie: ``True``)

Uses the built-in ``all`` for the calculation

Formula:
  - alln...

#### FindFirstIndex
- **基类**: OperationN
- **说明**: Returns the index of the last data that satisfies equality with the
condition generated by the parameter _evalfunc

Note:
  Returned indexes look backwards. 0 is the current index and 1 is
  the previ...

#### FindFirstIndexHighest
- **基类**: FindFirstIndex
- **说明**: Returns the index of the first data that is the highest in the period

Note:
  Returned indexes look backwards. 0 is the current index and 1 is
  the previous bar.

Formula:
  - index = index of first...

#### FindFirstIndexLowest
- **基类**: FindFirstIndex
- **说明**: Returns the index of the first data that is the lowest in the period

Note:
  Returned indexes look backwards. 0 is the current index and 1 is
  the previous bar.

Formula:
  - index = index of first ...

#### FindLastIndex
- **基类**: OperationN
- **说明**: Returns the index of the last data that satisfies equality with the
condition generated by the parameter _evalfunc

Note:
  Returned indexes look backwards. 0 is the current index and 1 is
  the previ...

#### FindLastIndexHighest
- **基类**: FindLastIndex
- **说明**: Returns the index of the last data that is the highest in the period

Note:
  Returned indexes look backwards. 0 is the current index and 1 is
  the previous bar.

Formula:
  - index = index of last d...

#### FindLastIndexLowest
- **基类**: FindLastIndex
- **说明**: Returns the index of the last data that is the lowest in the period

Note:
  Returned indexes look backwards. 0 is the current index and 1 is
  the previous bar.

Formula:
  - index = index of last da...

#### Accum
- **基类**: Indicator
- **说明**: Cummulative sum of the data values

Formula:
  - accum += data
- **关键方法**: next, once

#### Average
- **基类**: PeriodN
- **说明**: Averages a given data arithmetically over a period

Formula:
  - av = data(period) / period

See also:
  - https://en.wikipedia.org/wiki/Arithmetic_mean
- **关键方法**: next, once

#### ExponentialSmoothing
- **基类**: Average
- **说明**: Averages a given data over a period using exponential smoothing

A regular ArithmeticMean (Average) is used as the seed value considering
the first period values of data

Formula:
  - av = prev * (1 -...
- **关键方法**: __init__, next, once

#### ExponentialSmoothingDynamic
- **基类**: ExponentialSmoothing
- **说明**: Averages a given data over a period using exponential smoothing

A regular ArithmeticMean (Average) is used as the seed value considering
the first period values of data

Note:
  - alpha is an array o...
- **关键方法**: __init__, next, once

#### WeightedAverage
- **基类**: PeriodN
- **说明**: Calculates the weighted average of the given data over a period

The default weights (if none are provided) are linear to assigne more
weight to the most recent data

The result will be multiplied by ...
- **关键方法**: __init__, next, once


### indicators/bollinger.py

#### BollingerBands
- **基类**: Indicator
- **说明**: Defined by John Bollinger in the 80s. It measures volatility by defining
upper and lower bands at distance x standard deviations

Formula:
  - midband = SimpleMovingAverage(close, period)
  - topband ...
- **关键方法**: __init__

#### BollingerBandsPct
- **基类**: BollingerBands
- **说明**: Extends the Bollinger Bands with a Percentage line
- **关键方法**: __init__


### indicators/cci.py

#### CommodityChannelIndex
- **基类**: Indicator
- **说明**: Introduced by Donald Lambert in 1980 to measure variations of the
"typical price" (see below) from its mean to identify extremes and
reversals

Formula:
  - tp = typical_price = (high + low + close) /...
- **关键方法**: __init__


### indicators/contrib/vortex.py

#### Vortex
- **基类**: bt.Indicator
- **说明**: See:
  - http://www.vortexindicator.com/VFX_VORTEX.PDF
- **关键方法**: __init__


### indicators/crossover.py

#### NonZeroDifference
- **基类**: Indicator
- **说明**: Keeps track of the difference between two data inputs skipping, memorizing
the last non zero value if the current difference is zero

Formula:
  - diff = data - data1
  - nzd = diff if diff else diff(...
- **关键方法**: next, once

#### _CrossBase
- **基类**: Indicator
- **关键方法**: __init__

#### CrossUp
- **基类**: _CrossBase
- **说明**: This indicator gives a signal if the 1st provided data crosses over the 2nd
indicator upwards

It does need to look into the current time index (0) and the previous time
index (-1) of both the 1st and...

#### CrossDown
- **基类**: _CrossBase
- **说明**: This indicator gives a signal if the 1st provided data crosses over the 2nd
indicator upwards

It does need to look into the current time index (0) and the previous time
index (-1) of both the 1st and...

#### CrossOver
- **基类**: Indicator
- **说明**: This indicator gives a signal if the provided datas (2) cross up or down.

  - 1.0 if the 1st data crosses the 2nd data upwards
  - -1.0 if the 1st data crosses the 2nd data downwards

It does need to...
- **关键方法**: __init__


### indicators/dema.py

#### DoubleExponentialMovingAverage
- **基类**: MovingAverageBase
- **说明**: DEMA was first time introduced in 1994, in the article "Smoothing Data with
Faster Moving Averages" by Patrick G. Mulloy in "Technical Analysis of
Stocks & Commodities" magazine.

It attempts to reduc...
- **关键方法**: __init__

#### TripleExponentialMovingAverage
- **基类**: MovingAverageBase
- **说明**: TEMA was first time introduced in 1994, in the article "Smoothing Data with
Faster Moving Averages" by Patrick G. Mulloy in "Technical Analysis of
Stocks & Commodities" magazine.

It attempts to reduc...
- **关键方法**: __init__


### indicators/deviation.py

#### StandardDeviation
- **基类**: Indicator
- **说明**: Calculates the standard deviation of the passed data for a given period

Note:
  - If 2 datas are provided as parameters, the 2nd is considered to be the
    mean of the first

  - ``safepow`` (defaul...
- **关键方法**: __init__

#### MeanDeviation
- **基类**: Indicator
- **说明**: MeanDeviation (alias MeanDev)

Calculates the Mean Deviation of the passed data for a given period

Note:
  - If 2 datas are provided as parameters, the 2nd is considered to be the
    mean of the fir...
- **关键方法**: __init__


### indicators/directionalmove.py

#### UpMove
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* as part of the Directional Move System to
calculate Directional Indicators.

Positive if the given da...
- **关键方法**: __init__

#### DownMove
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* as part of the Directional Move System to
calculate Directional Indicators.

Positive if the given da...
- **关键方法**: __init__

#### _DirectionalIndicator
- **基类**: Indicator
- **说明**: This class serves as the root base class for all "Directional Movement
System" related indicators, given that the calculations are first common
and then derived from the common calculations.

It can c...
- **关键方法**: __init__

#### DirectionalIndicator
- **基类**: _DirectionalIndicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

Intended to measure trend strength

This indicator shows +DI, -DI:
  - Use PlusDirectionalIndicator...
- **关键方法**: __init__

#### PlusDirectionalIndicator
- **基类**: _DirectionalIndicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

Intended to measure trend strength

This indicator shows +DI:
  - Use MinusDirectionalIndicator (Mi...
- **关键方法**: __init__

#### MinusDirectionalIndicator
- **基类**: _DirectionalIndicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

Intended to measure trend strength

This indicator shows -DI:
  - Use PlusDirectionalIndicator (Plu...
- **关键方法**: __init__

#### AverageDirectionalMovementIndex
- **基类**: _DirectionalIndicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

Intended to measure trend strength

This indicator only shows ADX:
  - Use PlusDirectionalIndicator...
- **关键方法**: __init__

#### AverageDirectionalMovementIndexRating
- **基类**: AverageDirectionalMovementIndex
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

Intended to measure trend strength.

ADXR is the average of ADX with a value period bars ago

This ...
- **关键方法**: __init__

#### DirectionalMovementIndex
- **基类**: AverageDirectionalMovementIndex, DirectionalIndicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

Intended to measure trend strength

This indicator shows the ADX, +DI, -DI:
  - Use PlusDirectional...

#### DirectionalMovement
- **基类**: AverageDirectionalMovementIndexRating, DirectionalIndicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

Intended to measure trend strength

This indicator shows ADX, ADXR, +DI, -DI.

  - Use PlusDirectio...


### indicators/dma.py

#### DicksonMovingAverage
- **基类**: MovingAverageBase
- **说明**: By Nathan Dickson

The *Dickson Moving Average* combines the ``ZeroLagIndicator`` (aka
*ErrorCorrecting* or *EC*) by *Ehlers*, and the ``HullMovingAverage`` to
try to deliver a result close to that of...
- **关键方法**: __init__


### indicators/dpo.py

#### DetrendedPriceOscillator
- **基类**: Indicator
- **说明**: Defined by Joe DiNapoli in his book *"Trading with DiNapoli levels"*

It measures the price variations against a Moving Average (the trend)
and therefore removes the "trend" factor from the price.

Fo...
- **关键方法**: __init__


### indicators/dv2.py

#### DV2
- **基类**: Indicator
- **说明**: RSI(2) alternative
Developed by David Varadi of http://cssanalytics.wordpress.com/

This seems to be the *Bounded* version.

See also:

  - http://web.archive.org/web/20131216100741/http://quantingdut...
- **关键方法**: __init__


### indicators/ema.py

#### ExponentialMovingAverage
- **基类**: MovingAverageBase
- **说明**: A Moving Average that smoothes data exponentially over time.

It is a subclass of SmoothingMovingAverage.

  - self.smfactor -> 2 / (1 + period)
  - self.smfactor1 -> `1 - self.smfactor`

Formula:
  -...
- **关键方法**: __init__


### indicators/envelope.py

#### EnvelopeMixIn
- **基类**: object
- **说明**: MixIn class to create a subclass with another indicator. The main line of
that indicator will be surrounded by an upper and lower band separated a
given "percentage“ from the input main line

The usag...
- **关键方法**: __init__

#### _EnvelopeBase
- **基类**: Indicator
- **关键方法**: __init__

#### Envelope
- **基类**: _EnvelopeBase, EnvelopeMixIn
- **说明**: It creates envelopes bands separated from the source data by a given
percentage

Formula:
  - src = datasource
  - top = src * (1 + perc)
  - bot = src * (1 - perc)

See also:
  - http://stockcharts.c...


### indicators/hadelta.py

#### haDelta
- **基类**: bt.Indicator
- **说明**: Heikin Ashi Delta. Defined by Dan Valcu in his book "Heikin-Ashi: How to
Trade Without Candlestick Patterns ".

This indicator measures difference between Heikin Ashi close and open of
Heikin Ashi can...
- **关键方法**: __init__


### indicators/heikinashi.py

#### HeikinAshi
- **基类**: bt.Indicator
- **说明**: Heikin Ashi candlesticks in the forms of lines

Formula:
    ha_open = (ha_open(-1) + ha_close(-1)) / 2
    ha_high = max(hi, ha_open, ha_close)
    ha_low = min(lo, ha_open, ha_close)
    ha_close = ...
- **关键方法**: __init__, prenext


### indicators/hma.py

#### HullMovingAverage
- **基类**: MovingAverageBase
- **说明**: By Alan Hull

The Hull Moving Average solves the age old dilemma of making a moving
average more responsive to current price activity whilst maintaining curve
smoothness. In fact the HMA almost elimin...
- **关键方法**: __init__


### indicators/hurst.py

#### HurstExponent
- **基类**: PeriodN
- **说明**:  References:

   - https://www.quantopian.com/posts/hurst-exponent
   - https://www.quantopian.com/posts/some-code-from-ernie-chans-new-book-implemented-in-python

Interpretation of the results

   1....
- **关键方法**: __init__, next


### indicators/ichimoku.py

#### Ichimoku
- **基类**: bt.Indicator
- **说明**: Developed and published in his book in 1969 by journalist Goichi Hosoda

Formula:
  - tenkan_sen = (Highest(High, tenkan) + Lowest(Low, tenkan)) / 2.0
  - kijun_sen = (Highest(High, kijun) + Lowest(Lo...
- **关键方法**: __init__


### indicators/kama.py

#### AdaptiveMovingAverage
- **基类**: MovingAverageBase
- **说明**: Defined by Perry Kaufman in his book `"Smarter Trading"`.

It is A Moving Average with a continuously scaled smoothing factor by
taking into account market direction and volatility. The smoothing fact...
- **关键方法**: __init__


### indicators/kst.py

#### KnowSureThing
- **基类**: bt.Indicator
- **说明**: It is a "summed" momentum indicator. Developed by Martin Pring and
published in 1992 in Stocks & Commodities.

Formula:
  - rcma1 = MovAv(roc100(rp1), period)
  - rcma2 = MovAv(roc100(rp2), period)
  ...
- **关键方法**: __init__


### indicators/lrsi.py

#### LaguerreRSI
- **基类**: PeriodN
- **说明**: Defined by John F. Ehlers in `Cybernetic Analysis for Stock and Futures`,
2004, published by Wiley. `ISBN: 978-0-471-46307-8`

The Laguerre RSI tries to implements a better RSI by providing a sort of
...
- **关键方法**: next

#### LaguerreFilter
- **基类**: PeriodN
- **说明**: Defined by John F. Ehlers in `Cybernetic Analysis for Stock and Futures`,
2004, published by Wiley. `ISBN: 978-0-471-46307-8`

``gamma`` is meant to have values between ``0.2`` and ``0.8``, with the
b...
- **关键方法**: next


### indicators/mabase.py

#### MovingAverage
- **基类**: object
- **说明**: MovingAverage (alias MovAv)

A placeholder to gather all Moving Average Types in a single place.

Instantiating a SimpleMovingAverage can be achieved as follows::

  sma = MovingAverage.Simple(self.da...

#### MovAv
- **基类**: MovingAverage

#### MetaMovAvBase
- **基类**: Indicator.__class__
- **关键方法**: __new__

#### MovingAverageBase
- **基类**: with_metaclass(MetaMovAvBase, Indicator)
- **使用元类**: 是


### indicators/macd.py

#### MACD
- **基类**: Indicator
- **说明**: Moving Average Convergence Divergence. Defined by Gerald Appel in the 70s.

It measures the distance of a short and a long term moving average to
try to identify the trend.

A second lagging moving av...
- **关键方法**: __init__

#### MACDHisto
- **基类**: MACD
- **说明**: Subclass of MACD which adds a "histogram" of the difference between the
macd and signal lines

Formula:
  - histo = macd - signal

See:
  - http://en.wikipedia.org/wiki/MACD
- **关键方法**: __init__


### indicators/momentum.py

#### Momentum
- **基类**: Indicator
- **说明**: Measures the change in price by calculating the difference between the
current price and the price from a given period ago


Formula:
  - momentum = data - data_period

See:
  - http://en.wikipedia.or...
- **关键方法**: __init__

#### MomentumOscillator
- **基类**: Indicator
- **说明**: Measures the ratio of change in prices over a period

Formula:
  - mosc = 100 * (data / data_period)

See:
  - http://ta.mql4.com/indicators/oscillators/momentum
- **关键方法**: __init__

#### RateOfChange
- **基类**: Indicator
- **说明**: Measures the ratio of change in prices over a period

Formula:
  - roc = (data - data_period) / data_period

See:
  - http://en.wikipedia.org/wiki/Momentum_(technical_analysis)
- **关键方法**: __init__

#### RateOfChange100
- **基类**: Indicator
- **说明**: Measures the ratio of change in prices over a period with base 100

This is for example how ROC is defined in stockcharts

Formula:
  - roc = 100 * (data - data_period) / data_period

See:
  - http://...
- **关键方法**: __init__


### indicators/myind.py

#### MaBetweenHighAndLow
- **基类**: bt.Indicator
- **关键方法**: __init__

#### BarsLast
- **基类**: bt.Indicator
- **关键方法**: __init__, next

#### NewDiff
- **基类**: bt.Indicator
- **关键方法**: __init__, next


### indicators/ols.py

#### OLS_Slope_InterceptN
- **基类**: PeriodN
- **说明**: Calculates a linear regression using ``statsmodel.OLS`` (Ordinary least
squares) of data1 on data0

Uses ``pandas`` and ``statsmodels``
- **关键方法**: next

#### OLS_TransformationN
- **基类**: PeriodN
- **说明**: Calculates the ``zscore`` for data0 and data1. Although it doesn't directly
uses any external package it relies on ``OLS_SlopeInterceptN`` which uses
``pandas`` and ``statsmodels``
- **关键方法**: __init__

#### OLS_BetaN
- **基类**: PeriodN
- **说明**: Calculates a regression of data1 on data0 using ``pandas.ols``

Uses ``pandas``
- **关键方法**: next

#### CointN
- **基类**: PeriodN
- **说明**: Calculates the score (coint_t) and pvalue for a given ``period`` for the
data feeds

Uses ``pandas`` and ``statsmodels`` (for ``coint``)
- **关键方法**: next


### indicators/oscillator.py

#### OscillatorMixIn
- **基类**: Indicator
- **说明**: MixIn class to create a subclass with another indicator. The main line of
that indicator will be substracted from the other base class main line
creating an oscillator

The usage is:

  - Class XXXOsc...
- **关键方法**: __init__

#### Oscillator
- **基类**: Indicator
- **说明**: Oscillation of a given data around another data

Datas:
  This indicator can accept 1 or 2 datas for the calculation.

  - If 1 data is provided, it must be a complex "Lines" object (indicator)
    wh...
- **关键方法**: __init__


### indicators/percentchange.py

#### PercentChange
- **基类**: Indicator
- **说明**: Measures the perccentage change of the current value with respect to that
of period bars ago
- **关键方法**: __init__


### indicators/percentrank.py

#### PercentRank
- **基类**: BaseApplyN
- **说明**: Measures the percent rank of the current value with respect to that of
period bars ago


### indicators/pivotpoint.py

#### PivotPoint
- **基类**: Indicator
- **说明**: Defines a level of significance by taking into account the average of price
bar components of the past period of a larger timeframe. For example when
operating with days, the values are taking from th...
- **关键方法**: __init__

#### FibonacciPivotPoint
- **基类**: Indicator
- **说明**: Defines a level of significance by taking into account the average of price
bar components of the past period of a larger timeframe. For example when
operating with days, the values are taking from th...
- **关键方法**: __init__

#### DemarkPivotPoint
- **基类**: Indicator
- **说明**: Defines a level of significance by taking into account the average of price
bar components of the past period of a larger timeframe. For example when
operating with days, the values are taking from th...
- **关键方法**: __init__


### indicators/prettygoodoscillator.py

#### PrettyGoodOscillator
- **基类**: Indicator
- **说明**: The "Pretty Good Oscillator" (PGO) by Mark Johnson measures the distance of
the current close from its simple moving average of period
Average), expressed in terms of an average true range (see Averag...
- **关键方法**: __init__


### indicators/priceoscillator.py

#### _PriceOscBase
- **基类**: Indicator
- **关键方法**: __init__

#### PriceOscillator
- **基类**: _PriceOscBase
- **说明**: Shows the difference between a short and long exponential moving
averages expressed in points.

Formula:
  - po = ema(short) - ema(long)

See:
  - http://www.metastock.com/Customer/Resources/TAAZ/?c=3...

#### PercentagePriceOscillator
- **基类**: _PriceOscBase
- **说明**: Shows the difference between a short and long exponential moving
averages expressed in percentage. The MACD does the same but expressed in
absolute points.

Expressing the difference in percentage all...
- **关键方法**: __init__

#### PercentagePriceOscillatorShort
- **基类**: PercentagePriceOscillator
- **说明**: Shows the difference between a short and long exponential moving
averages expressed in percentage. The MACD does the same but expressed in
absolute points.

Expressing the difference in percentage all...


### indicators/psar.py

#### _SarStatus
- **基类**: object

#### ParabolicSAR
- **基类**: PeriodN
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* for the RSI

SAR stands for *Stop and Reverse* and the indicator was meant as a signal
for entry (and...
- **关键方法**: prenext, next


### indicators/rmi.py

#### RelativeMomentumIndex
- **基类**: RSI
- **说明**: Description:
The Relative Momentum Index was developed by Roger Altman and was
introduced in his article in the February, 1993 issue of Technical Analysis
of Stocks & Commodities magazine.

While your...


### indicators/rsi.py

#### UpDay
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* for the RSI

Records days which have been "up", i.e.: the close price has been
higher than the day be...
- **关键方法**: __init__

#### DownDay
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* for the RSI

Records days which have been "down", i.e.: the close price has been
lower than the day b...
- **关键方法**: __init__

#### UpDayBool
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* for the RSI

Records days which have been "up", i.e.: the close price has been
higher than the day be...
- **关键方法**: __init__

#### DownDayBool
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"* for the RSI

Records days which have been "down", i.e.: the close price has been
lower than the day b...
- **关键方法**: __init__

#### RelativeStrengthIndex
- **基类**: Indicator
- **说明**: Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
Technical Trading Systems"*.

It measures momentum by calculating the ration of higher closes and
lower closes after having been ...
- **关键方法**: __init__

#### RSI_Safe
- **基类**: RSI
- **说明**: Subclass of RSI which changes parameers ``safediv`` to ``True`` as the
default value

See:
  - http://en.wikipedia.org/wiki/Relative_strength_index

#### RSI_SMA
- **基类**: RSI
- **说明**: Uses a SimpleMovingAverage as described in Wikipedia and other soures

See:
  - http://en.wikipedia.org/wiki/Relative_strength_index

#### RSI_EMA
- **基类**: RSI
- **说明**: Uses an ExponentialMovingAverage as described in Wikipedia

See:
  - http://en.wikipedia.org/wiki/Relative_strength_index


### indicators/sma.py

#### MovingAverageSimple
- **基类**: MovingAverageBase
- **说明**: Non-weighted average of the last n periods

Formula:
  - movav = Sum(data, period) / period

See also:
  - http://en.wikipedia.org/wiki/Moving_average#Simple_moving_average
- **关键方法**: __init__


### indicators/smma.py

#### SmoothedMovingAverage
- **基类**: MovingAverageBase
- **说明**: Smoothing Moving Average used by Wilder in his 1978 book `New Concepts in
Technical Trading`

Defined in his book originally as:

  - new_value = (old_value * (period - 1) + new_data) / period

Can be...
- **关键方法**: __init__


### indicators/stochastic.py

#### _StochasticBase
- **基类**: Indicator
- **关键方法**: __init__

#### StochasticFast
- **基类**: _StochasticBase
- **说明**: By Dr. George Lane in the 50s. It compares a closing price to the price
range and tries to show convergence if the closing prices are close to the
extremes

  - It will go up if closing prices are clo...
- **关键方法**: __init__

#### Stochastic
- **基类**: _StochasticBase
- **说明**: The regular (or slow version) adds an additional moving average layer and
thus:

  - The percD line of the StochasticFast becomes the percK line
  - percD becomes a  moving average of period_dslow of ...
- **关键方法**: __init__

#### StochasticFull
- **基类**: _StochasticBase
- **说明**: This version displays the 3 possible lines:

  - percK
  - percD
  - percSlow

Formula:
  - k = d
  - d = MovingAverage(k, period_dslow)
  - dslow =

See:
  - http://en.wikipedia.org/wiki/Stochastic_o...
- **关键方法**: __init__


### indicators/trix.py

#### Trix
- **基类**: Indicator
- **说明**: Defined by Jack Hutson in the 80s and shows the Rate of Change (%) or slope
of a triple exponentially smoothed moving average

Formula:
  - ema1 = EMA(data, period)
  - ema2 = EMA(ema1, period)
  - em...
- **关键方法**: __init__

#### TrixSignal
- **基类**: Trix
- **说明**: Extension of Trix with a signal line (ala MACD)

Formula:
  - trix = Trix(data, period)
  - signal = EMA(trix, sigperiod)

See:
  - http://stockcharts.com/school/doku.php?id=chart_school:technical_ind...
- **关键方法**: __init__


### indicators/tsi.py

#### TrueStrengthIndicator
- **基类**: bt.Indicator
- **说明**: The True Strength Indicators was first introduced in Stocks & Commodities
Magazine by its author William Blau. It measures momentum with a double
exponential (default) of the prices.

It shows diverge...
- **关键方法**: __init__


### indicators/ultimateoscillator.py

#### UltimateOscillator
- **基类**: bt.Indicator
- **说明**: Formula:
  # Buying Pressure = Close - TrueLow
  BP = Close - Minimum(Low or Prior Close)

  # TrueRange = TrueHigh - TrueLow
  TR = Maximum(High or Prior Close)  -  Minimum(Low or Prior Close)

  Ave...
- **关键方法**: __init__


### indicators/vortex.py

#### Vortex
- **基类**: bt.Indicator
- **说明**: See:
  - http://www.vortexindicator.com/VFX_VORTEX.PDF
- **关键方法**: __init__


### indicators/williams.py

#### WilliamsR
- **基类**: Indicator
- **说明**: Developed by Larry Williams to show the relation of closing prices to
the highest-lowest range of a given period.

Known as Williams %R (but % is not allowed in Python identifiers)

Formula:
  - num =...
- **关键方法**: __init__

#### WilliamsAD
- **基类**: Indicator
- **说明**: By Larry Williams. It does cumulatively measure if the price is
accumulating (upwards) or distributing (downwards) by using the concept of
UpDays and DownDays.

Prices can go upwards but do so in a fa...
- **关键方法**: __init__


### indicators/wma.py

#### WeightedMovingAverage
- **基类**: MovingAverageBase
- **说明**: A Moving Average which gives an arithmetic weighting to values with the
newest having the more weight

Formula:
  - weights = range(1, period + 1)
  - coef = 2 / (period * (period + 1))
  - movav = co...
- **关键方法**: __init__


### indicators/zlema.py

#### ZeroLagExponentialMovingAverage
- **基类**: MovingAverageBase
- **说明**: The zero-lag exponential moving average (ZLEMA) is a variation of the EMA
which adds a momentum term aiming to reduce lag in the average so as to
track current prices more closely.

Formula:
  - lag =...
- **关键方法**: __init__


### indicators/zlind.py

#### ZeroLagIndicator
- **基类**: MovingAverageBase
- **说明**: By John Ehlers and Ric Way

The zero-lag indicator (ZLIndicator) is a variation of the EMA
which modifies the EMA by trying to minimize the error (distance price -
error correction) and thus reduce th...
- **关键方法**: __init__, next


### linebuffer.py

#### LineBuffer
- **基类**: LineSingle
- **说明**: LineBuffer defines an interface to an "array.array" (or list) in which
index 0 points to the item which is active for input and output.

Positive indices fetch values from the past (left hand side)
Ne...
- **关键方法**: __init__, __call__

#### MetaLineActions
- **基类**: LineBuffer.__class__
- **说明**: Metaclass for LineActions

Scans the instance before init for LineBuffer (or parentclass LineSingle)
instances to calculate the minperiod for this instance

postinit it registers the instance to the o...
- **关键方法**: __call__

#### PseudoArray
- **基类**: object
- **说明**: 伪array,访问任何的index的时候都会返回来wrapped,使用.array会返回自身
- **关键方法**: __init__

#### LineActions
- **基类**: with_metaclass(MetaLineActions, LineBuffer)
- **使用元类**: 是
- **说明**: Base class derived from LineBuffer intented to defined the
minimum interface to make it compatible with a LineIterator by
providing operational _next and _once interfaces.

The metaclass does the dirt...

#### _LineDelay
- **基类**: LineActions
- **说明**: Takes a LineBuffer (or derived) object and stores the value from
"ago" periods effectively delaying the delivery of data
- **关键方法**: __init__, next, once

#### _LineForward
- **基类**: LineActions
- **说明**: Takes a LineBuffer (or derived) object and stores the value from
"ago" periods from the future
- **关键方法**: __init__, next, once

#### LinesOperation
- **基类**: LineActions
- **说明**: Holds an operation that operates on a two operands. Example: mul

It will "next"/traverse the array applying the operation on the
two operands and storing the result in self.

To optimize the operatio...
- **关键方法**: __init__, next, once

#### LineOwnOperation
- **基类**: LineActions
- **说明**: Holds an operation that operates on a single operand. Example: abs

It will "next"/traverse the array applying the operation and storing
the result in self
- **关键方法**: __init__, next, once


### lineiterator.py

#### MetaLineIterator
- **基类**: LineSeries.__class__

#### LineIterator
- **基类**: with_metaclass(MetaLineIterator, LineSeries)
- **使用元类**: 是
- **关键方法**: once, prenext, next

#### DataAccessor
- **基类**: LineIterator

#### IndicatorBase
- **基类**: DataAccessor

#### ObserverBase
- **基类**: DataAccessor

#### StrategyBase
- **基类**: DataAccessor

#### SingleCoupler
- **基类**: LineActions
- **关键方法**: __init__, next

#### MultiCoupler
- **基类**: LineIterator
- **关键方法**: __init__, next


### lineroot.py

#### MetaLineRoot
- **基类**: metabase.MetaParams
- **说明**: Once the object is created (effectively pre-init) the "owner" of this
class is sought
# 当这个类在创建之前(pre-init之前)，会寻找这个类的一个父类，并保存到_owner属性上

#### LineRoot
- **基类**: with_metaclass(MetaLineRoot, object)
- **使用元类**: 是
- **说明**: Defines a common base and interfaces for Single and Multiple
LineXXX instances

    Period management
    Iteration management
    Operation (dual/single operand) Management
    Rich Comparison operat...
- **关键方法**: prenext, next, once

#### LineMultiple
- **基类**: LineRoot
- **说明**: Base class for LineXXX instances that hold more than one line
LineMultiple-->LineRoot-->MetaLineRoot-->MetaParams-->MetaBase-->type
# 这个类继承自LineRoot，用于操作line多余1条的类

#### LineSingle
- **基类**: LineRoot
- **说明**: Base class for LineXXX instances that hold a single line
LineSingle-->LineRoot-->MetaLineRoot-->MetaParams-->MetaBase-->type
# 这个类继承自LineRoot，用于操作line是一条的类


### lineseries.py

#### LineAlias
- **基类**: object
- **说明**: Descriptor class that store a line reference and returns that line
from the owner

Keyword Args:
    line (int): reference to the line that will be returned from
    owner's *lines* buffer

As a conve...
- **关键方法**: __init__

#### Lines
- **基类**: object
- **说明**: Defines an "array" of lines which also has most of the interface of
a LineBuffer class (forward, rewind, advance...).

This interface operations are passed to the lines held by self

The class can aut...
- **关键方法**: __init__

#### MetaLineSeries
- **基类**: LineMultiple.__class__
- **说明**: Dirty job manager for a LineSeries

  - During __new__ (class creation), it reads "lines", "plotinfo",
    "plotlines" class variable definitions and turns them into
    Classes of type Lines or AutoC...
- **关键方法**: __new__

#### MetaLineSeries
- **基类**: LineMultiple.__class__
- **说明**: Dirty job manager for a LineSeries

  - During __new__ (class creation), it reads "lines", "plotinfo",
    "plotlines" class variable definitions and turns them into
    Classes of type Lines or AutoC...
- **关键方法**: __new__

#### LineSeries
- **基类**: with_metaclass(MetaLineSeries, LineMultiple)
- **使用元类**: 是
- **关键方法**: __init__, __call__

#### LineSeriesStub
- **基类**: LineSeries
- **说明**: Simulates a LineMultiple object based on LineSeries from a single line

The index management operations are overriden to take into account if the
line is a slave, ie:

  - The line reference is a line...
- **关键方法**: __init__


### metabase.py

#### MetaBase
- **基类**: type
- **关键方法**: __call__

#### AutoInfoClass
- **基类**: object
- **关键方法**: __new__

#### MetaParams
- **基类**: MetaBase
- **关键方法**: __new__

#### ParamsBase
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是

#### ItemCollection
- **基类**: object
- **说明**: Holds a collection of items that can be reached by

  - Index
  - Name (if set in the append operation)
- **关键方法**: __init__


### observer.py

#### MetaObserver
- **基类**: ObserverBase.__class__

#### Observer
- **基类**: with_metaclass(MetaObserver, ObserverBase)
- **使用元类**: 是
- **关键方法**: prenext


### observers/benchmark.py

#### Benchmark
- **基类**: TimeReturn
- **说明**: This observer stores the *returns* of the strategy and the *return* of a
reference asset which is one of the datas passed to the system.

Params:

  - ``timeframe`` (default: ``None``)
    If ``None``...
- **关键方法**: __init__, next, prenext


### observers/broker.py

#### Cash
- **基类**: Observer
- **说明**: This observer keeps track of the current amount of cash in the broker

Params: None
- **关键方法**: next

#### Value
- **基类**: Observer
- **说明**: This observer keeps track of the current portfolio value in the broker
including the cash

Params:

  - ``fund`` (default: ``None``)

    If ``None`` the actual mode of the broker (fundmode - True/Fal...
- **关键方法**: next

#### Broker
- **基类**: Observer
- **说明**: This observer keeps track of the current cash amount and portfolio value in
the broker (including the cash)

Params: None
- **关键方法**: next

#### FundValue
- **基类**: Observer
- **说明**: This observer keeps track of the current fund-like value

Params: None
- **关键方法**: next

#### FundShares
- **基类**: Observer
- **说明**: This observer keeps track of the current fund-like shares

Params: None
- **关键方法**: next


### observers/buysell.py

#### BuySell
- **基类**: Observer
- **说明**: This observer keeps track of the individual buy/sell orders (individual
executions) and will plot them on the chart along the data around the
execution price level

Params:
  - ``barplot`` (default: `...
- **关键方法**: next


### observers/drawdown.py

#### DrawDown
- **基类**: Observer
- **说明**: This observer keeps track of the current drawdown level (plotted) and
the maxdrawdown (not plotted) levels

Params:

  - ``fund`` (default: ``None``)

    If ``None`` the actual mode of the broker (fu...
- **关键方法**: __init__, next

#### DrawDownLength
- **基类**: Observer
- **说明**: This observer keeps track of the current drawdown length (plotted) and
the drawdown max length (not plotted)

Params: None
- **关键方法**: __init__, next

#### DrawDown_Old
- **基类**: Observer
- **说明**: This observer keeps track of the current drawdown level (plotted) and
the maxdrawdown (not plotted) levels

Params: None
- **关键方法**: __init__, next


### observers/logreturns.py

#### LogReturns
- **基类**: bt.Observer
- **说明**: This observer stores the *log returns* of the strategy or a

Params:

  - ``timeframe`` (default: ``None``)
    If ``None`` then the complete return over the entire backtested period
    will be repor...
- **关键方法**: __init__, next

#### LogReturns2
- **基类**: LogReturns
- **说明**: Extends the observer LogReturns to show two instruments
- **关键方法**: __init__, next


### observers/timereturn.py

#### TimeReturn
- **基类**: Observer
- **说明**: This observer stores the *returns* of the strategy.

Params:

  - ``timeframe`` (default: ``None``)
    If ``None`` then the complete return over the entire backtested period
    will be reported

   ...
- **关键方法**: __init__, next


### observers/trades.py

#### Trades
- **基类**: Observer
- **说明**: This observer keeps track of full trades and plot the PnL level achieved
when a trade is closed.

A trade is open when a position goes from 0 (or crossing over 0) to X and
is then closed when it goes ...
- **关键方法**: __init__, next

#### MetaDataTrades
- **基类**: Observer.__class__

#### DataTrades
- **基类**: with_metaclass(MetaDataTrades, Observer)
- **使用元类**: 是
- **关键方法**: next


### order.py

#### OrderExecutionBit
- **基类**: object
- **说明**: Intended to hold information about order execution. A "bit" does not
determine if the order has been fully/partially executed, it just holds
information.

Member Attributes:

  - dt: datetime (float) ...
- **关键方法**: __init__

#### OrderData
- **基类**: object
- **说明**: Holds actual order data for Creation and Execution.

In the case of Creation the request made and in the case of Execution the
actual outcome.

Member Attributes:

  - exbits : iterable of OrderExecut...
- **关键方法**: __init__

#### OrderBase
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **关键方法**: __init__

#### Order
- **基类**: OrderBase
- **说明**: 订单类用于保存订单创建、执行数据和订单类型
Class which holds creation/execution data and type of oder.
# 订单可能有下面的一些状态
The order may have the following status:
    # 提交给broker并且等待信息
  - Submitted: sent to the broker and aw...

#### BuyOrder
- **基类**: Order

#### StopBuyOrder
- **基类**: BuyOrder

#### StopLimitBuyOrder
- **基类**: BuyOrder

#### SellOrder
- **基类**: Order

#### StopSellOrder
- **基类**: SellOrder

#### StopLimitSellOrder
- **基类**: SellOrder


### plot/finance.py

#### CandlestickPlotHandler
- **基类**: object
- **关键方法**: __init__

#### VolumePlotHandler
- **基类**: object
- **关键方法**: __init__

#### OHLCPlotHandler
- **基类**: object
- **关键方法**: __init__

#### LineOnClosePlotHandler
- **基类**: object
- **关键方法**: __init__


### plot/formatters.py

#### MyVolFormatter
- **基类**: mplticker.Formatter
- **关键方法**: __init__, __call__

#### MyDateFormatter
- **基类**: mplticker.Formatter
- **关键方法**: __init__, __call__


### plot/locator.py

#### RRuleLocator
- **基类**: RRLocator
- **关键方法**: __init__

#### AutoDateLocator
- **基类**: ADLocator
- **关键方法**: __init__

#### AutoDateFormatter
- **基类**: ADFormatter
- **关键方法**: __init__, __call__


### plot/multicursor.py

#### Widget
- **基类**: object
- **说明**: Abstract base class for GUI neutral widgets

#### MultiCursor
- **基类**: Widget
- **说明**: Provide a vertical (default) and/or horizontal line cursor shared between
multiple axes.

For the cursor to remain responsive you much keep a reference to
it.

Example usage::

    from matplotlib.wid...
- **关键方法**: __init__

#### MultiCursor2
- **基类**: Widget
- **说明**: Provide a vertical (default) and/or horizontal line cursor shared between
multiple axes.
For the cursor to remain responsive you much keep a reference to
it.
Example usage::
    from matplotlib.widget...
- **关键方法**: __init__


### plot/plot.py

#### PInfo
- **基类**: object
- **关键方法**: __init__

#### Plot_OldSync
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **关键方法**: __init__


### plot/scheme.py

#### PlotScheme
- **基类**: object
- **关键方法**: __init__


### position.py

#### Position
- **基类**: object
- **说明**: Keeps and updates the size and price of a position. The object has no
relationship to any asset. It only keeps size and price.

Member Attributes:
  - size (int): current size of the position
  - pric...
- **关键方法**: __init__


### resamplerfilter.py

#### DTFaker
- **基类**: object
- **关键方法**: __init__, __call__

#### _BaseResampler
- **基类**: with_metaclass(metabase.MetaParams, object)
- **使用元类**: 是
- **关键方法**: __init__

#### Resampler
- **基类**: _BaseResampler
- **说明**: This class resamples data of a given timeframe to a larger timeframe.

Params

  - bar2edge (default: True)

    resamples using time boundaries as the target. For example with a
    "ticks -> 5 secon...
- **关键方法**: __call__

#### Replayer
- **基类**: _BaseResampler
- **说明**: This class replays data of a given timeframe to a larger timeframe.

It simulates the action of the market by slowly building up (for ex.) a
daily bar from tick/seconds/minutes data

Only when the bar...
- **关键方法**: __call__

#### ResamplerTicks
- **基类**: Resampler

#### ResamplerSeconds
- **基类**: Resampler

#### ResamplerMinutes
- **基类**: Resampler

#### ResamplerDaily
- **基类**: Resampler

#### ResamplerWeekly
- **基类**: Resampler

#### ResamplerMonthly
- **基类**: Resampler

#### ResamplerYearly
- **基类**: Resampler

#### ReplayerTicks
- **基类**: Replayer

#### ReplayerSeconds
- **基类**: Replayer

#### ReplayerMinutes
- **基类**: Replayer

#### ReplayerDaily
- **基类**: Replayer

#### ReplayerWeekly
- **基类**: Replayer

#### ReplayerMonthly
- **基类**: Replayer


### signal.py

#### Signal
- **基类**: bt.Indicator
- **关键方法**: __init__


### sizer.py

#### Sizer
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **说明**: This is the base class for *Sizers*. Any *sizer* should subclass this
and override the ``_getsizing`` method

Member Attribs:

  - ``strategy``: will be set by the strategy in which the sizer is worki...


### sizers/fixedsize.py

#### FixedSize
- **基类**: bt.Sizer
- **说明**: This sizer simply returns a fixed size for any operation.
Size can be controlled by number of tranches that a system
wishes to use to scale into trades by specifying the ``tranches``
parameter.


Para...

#### FixedReverser
- **基类**: bt.Sizer
- **说明**: This sizer returns the needes fixed size to reverse an open position or
the fixed size to open one

  - To open a position: return the param ``stake``

  - To reverse a position: return 2 * ``stake``
...

#### FixedSizeTarget
- **基类**: bt.Sizer
- **说明**: This sizer simply returns a fixed target size, useful when coupled
with Target Orders and specifically ``cerebro.target_order_size()``.
Size can be controlled by number of tranches that a system
wishe...


### sizers/percents_sizer.py

#### PercentSizer
- **基类**: bt.Sizer
- **说明**: This sizer return percents of available cash

Params:
  - ``percents`` (default: ``20``)
- **关键方法**: __init__

#### AllInSizer
- **基类**: PercentSizer
- **说明**: This sizer return all available cash of broker

Params:
  - ``percents`` (default: ``100``)

#### PercentSizerInt
- **基类**: PercentSizer
- **说明**: This sizer return percents of available cash in form of size truncated
to an int

Params:
  - ``percents`` (default: ``20``)

#### AllInSizerInt
- **基类**: PercentSizerInt
- **说明**: This sizer return all available cash of broker with the
size truncated to an int

 Params:
   - ``percents`` (default: ``100``)
 


### store.py

#### MetaSingleton
- **基类**: MetaParams
- **说明**: Metaclass to make a metaclassed class a singleton
- **关键方法**: __init__, __call__

#### Store
- **基类**: with_metaclass(MetaSingleton, object)
- **使用元类**: 是
- **说明**: Base class for all Stores


### stores/ccxtstore.py

#### MetaSingleton
- **基类**: MetaParams
- **说明**: Metaclass to make a metaclassed class a singleton
- **关键方法**: __init__, __call__

#### CCXTStore
- **基类**: with_metaclass(MetaSingleton, object)
- **使用元类**: 是
- **说明**: API provider for CCXT feed and broker classes.

Added a new get_wallet_balance method. This will allow manual checking of the balance.
    The method will allow setting parameters. Useful for getting ...
- **关键方法**: __init__


### stores/ctpstore.py

#### MyCtpbeeApi
- **基类**: CtpbeeApi
- **关键方法**: __init__

#### MetaSingleton
- **基类**: MetaParams
- **说明**: Metaclass to make a metaclassed class a singleton
- **关键方法**: __init__, __call__

#### CTPStore
- **基类**: with_metaclass(MetaSingleton, object)
- **使用元类**: 是
- **说明**: Singleton class wrapping
- **关键方法**: __init__


### stores/ibstore.py

#### RTVolume
- **基类**: object
- **说明**: Parses a tickString tickType 48 (RTVolume) event from the IB API into its
constituent fields
Supports using a "price" to simulate an RTVolume from a tickPrice event
- **关键方法**: __init__

#### MetaSingleton
- **基类**: MetaParams
- **说明**: Metaclass to make a metaclassed class a singleton
- **关键方法**: __init__, __call__

#### IBStore
- **基类**: with_metaclass(MetaSingleton, object)
- **使用元类**: 是
- **说明**: Singleton class wrapping an ibpy ibConnection instance.

The parameters can also be specified in the classes which use this store,
like ``IBData`` and ``IBBroker``
# 参数也可以在使用这个store的类里面，比如``IBData`` 和...
- **关键方法**: __init__


### stores/oandastore.py

#### OandaRequestError
- **基类**: oandapy.OandaError
- **关键方法**: __init__

#### OandaStreamError
- **基类**: oandapy.OandaError
- **关键方法**: __init__

#### OandaTimeFrameError
- **基类**: oandapy.OandaError
- **关键方法**: __init__

#### OandaNetworkError
- **基类**: oandapy.OandaError
- **关键方法**: __init__

#### API
- **基类**: oandapy.API

#### Streamer
- **基类**: oandapy.Streamer
- **关键方法**: __init__

#### MetaSingleton
- **基类**: MetaParams
- **说明**: Metaclass to make a metaclassed class a singleton
- **关键方法**: __init__, __call__

#### OandaStore
- **基类**: with_metaclass(MetaSingleton, object)
- **使用元类**: 是
- **说明**: Singleton class wrapping to control the connections to Oanda.

Params:

  - ``token`` (default:``None``): API access token

  - ``account`` (default: ``None``): account id

  - ``practice`` (default: ...
- **关键方法**: __init__


### stores/vchartfile.py

#### VChartFile
- **基类**: bt.Store
- **说明**: Store provider for Visual Chart binary files

Params:

  - ``path`` (default:``None``):

    If the path is ``None`` and running under *Windows*, the registry will
    be examined to find the root dir...
- **关键方法**: __init__


### stores/vcstore.py

#### _SymInfo
- **基类**: object
- **关键方法**: __init__

#### RTEventSink
- **基类**: object
- **关键方法**: __init__

#### MetaSingleton
- **基类**: MetaParams
- **说明**: Metaclass to make a metaclassed class a singleton
- **关键方法**: __init__, __call__

#### VCStore
- **基类**: with_metaclass(MetaSingleton, object)
- **使用元类**: 是
- **说明**: Singleton class wrapping an ibpy ibConnection instance.

The parameters can also be specified in the classes which use this store,
like ``VCData`` and ``VCBroker``
- **关键方法**: __init__


### strategies/sample.py

#### Origin
- **说明**:     
- **关键方法**: __init__

#### SmaCross
- **基类**: bt.Strategy
- **关键方法**: __init__, prenext, next


### strategies/sma_crossover.py

#### MA_CrossOver
- **基类**: bt.Strategy
- **说明**: This is a long-only strategy which operates on a moving average cross

Note:
  - Although the default

Buy Logic:
  - No position is open on the data

  - The ``fast`` moving averagecrosses over the `...
- **关键方法**: __init__, next


### strategies/test_backtrader_ccxt_okex_sma.py

#### TestStrategy
- **基类**: bt.Strategy
- **关键方法**: __init__, next


### strategies/test_backtrader_ctp.py

#### Origin
- **说明**:     
- **关键方法**: __init__

#### SmaCross
- **基类**: bt.Strategy
- **关键方法**: __init__, prenext, next


### strategies/test_ctp_sample.py

#### Origin
- **说明**:     
- **关键方法**: __init__

#### SmaCross
- **基类**: bt.Strategy
- **关键方法**: __init__, prenext, next


### strategy.py

#### MetaStrategy
- **基类**: StrategyBase.__class__
- **关键方法**: __new__, __init__

#### Strategy
- **基类**: with_metaclass(MetaStrategy, StrategyBase)
- **使用元类**: 是
- **说明**: Base class to be subclassed for user defined strategies.

#### MetaSigStrategy
- **基类**: Strategy.__class__
- **关键方法**: __new__

#### SignalStrategy
- **基类**: with_metaclass(MetaSigStrategy, Strategy)
- **使用元类**: 是
- **说明**: This subclass of ``Strategy`` is meant to to auto-operate using
**signals**.

*Signals* are usually indicators and the expected output values:

  - ``> 0`` is a ``long`` indication

  - ``< 0`` is a `...


### studies/contrib/fractal.py

#### Fractal
- **基类**: bt.ind.PeriodN
- **说明**: References:
    [Ref 1] http://www.investopedia.com/articles/trading/06/fractals.asp
- **关键方法**: next


### talib.py

#### _MetaTALibIndicator
- **基类**: bt.Indicator.__class__

#### _TALibIndicator
- **基类**: with_metaclass(_MetaTALibIndicator, bt.Indicator)
- **使用元类**: 是
- **关键方法**: once, next


### tests/test_backtrader_ts_strategy/test_backtrader_ts.py

#### SmaStrategy
- **基类**: bt.Strategy
- **关键方法**: __init__, next


### tests/test_vector_cs_strategy/test_backtrader_cs.py

#### CloseMaCs
- **基类**: bt.Strategy
- **关键方法**: __init__, prenext, next


### tests/test_vector_ts_strategy/test_backtrader_vector_ts_equal.py

#### AlphaTs001
- **基类**: AlphaTs

#### SmaStrategy
- **基类**: bt.Strategy
- **关键方法**: __init__, next


### timer.py

#### Timer
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是
- **关键方法**: __init__


### trade.py

#### TradeHistory
- **基类**: AutoOrderedDict
- **说明**: Represents the status and update event for each update a Trade has

This object is a dictionary which allows '.' notation
# 这个类保存每个交易的状态和事件更新
Attributes:
  - ``status`` (``dict`` with '.' notation): H...
- **关键方法**: __init__

#### Trade
- **基类**: object
- **说明**: Keeps track of the life of an trade: size, price,
commission (and value?)

An trade starts at 0 can be increased and reduced and can
be considered closed if it goes back to 0.

The trade can be long (...
- **关键方法**: __init__


### tradingcal.py

#### TradingCalendarBase
- **基类**: with_metaclass(MetaParams, object)
- **使用元类**: 是

#### TradingCalendar
- **基类**: TradingCalendarBase
- **说明**: Wrapper of ``pandas_market_calendars`` for a trading calendar. The package
``pandas_market_calendar`` must be installed
# 在这个类里面，目前来看，似乎没有必须要安装pandas_market_calendar
Params:

  - ``open`` (default ``t...
- **关键方法**: __init__

#### PandasMarketCalendar
- **基类**: TradingCalendarBase
- **说明**: Wrapper of ``pandas_market_calendars`` for a trading calendar. The package
``pandas_market_calendar`` must be installed
# 必须要安装pandas_market_calendar
Params:

  - ``calendar`` (default ``None``)

    ...
- **关键方法**: __init__


### utils/autodict.py

#### AutoDictList
- **基类**: dict

#### DotDict
- **基类**: dict

#### AutoDict
- **基类**: dict

#### AutoOrderedDict
- **基类**: OrderedDict


### utils/dateintern.py

#### _UTC
- **基类**: datetime.tzinfo
- **说明**: UTC

#### _LocalTimezone
- **基类**: datetime.tzinfo
- **说明**: 本地时区相关的处理


### utils/flushfile.py

#### flushfile
- **基类**: object
- **关键方法**: __init__

#### StdOutDevNull
- **基类**: object
- **关键方法**: __init__


### utils/fractal.py

#### Fractal
- **基类**: bt.ind.PeriodN
- **说明**: References:
    [Ref 1] http://www.investopedia.com/articles/trading/06/fractals.asp
- **关键方法**: next


### utils/ordereddefaultdict.py

#### OrderedDefaultdict
- **基类**: OrderedDict
- **关键方法**: __init__


### utils/py3.py

#### metaclass
- **基类**: meta
- **关键方法**: __new__


### utils/python_code.py

#### _UTC
- **基类**: datetime.tzinfo
- **说明**: UTC


### utils/test_backtrader.py

#### DirectStrategy
- **基类**: bt.Strategy
- **关键方法**: __init__, next


### vectors/cs.py

#### AlphaCs
- **基类**: object
- **关键方法**: __init__


### vectors/ts.py

#### AlphaTs
- **基类**: object
- **关键方法**: __init__


### writer.py

#### WriterBase
- **基类**: with_metaclass(bt.MetaParams, object)
- **使用元类**: 是

#### WriterFile
- **基类**: WriterBase
- **说明**: The system wide writer class.

It can be parametrized with:

  - ``out`` (default: ``sys.stdout``): output stream to write to

    If a string is passed a filename with the content of the parameter wi...
- **关键方法**: __init__, next

#### WriterStringIO
- **基类**: WriterFile
- **关键方法**: __init__



## 5. 继承关系图表总结


### 元类继承链

```
type (Python 内置)
 └── MetaBase (metabase.py)
     └── MetaParams (metabase.py)
         ├── MetaLineRoot (lineroot.py)
         ├── MetaLineSeries (lineseries.py)
         ├── MetaLineIterator (lineiterator.py)
         ├── MetaStrategy (strategy.py)
         ├── MetaIndicator (indicator.py)
         └── MetaAbstractDataBase (feed.py)
```

### 核心基类继承链

```
LineRoot (lineroot.py)
 ├── LineSingle (lineroot.py)
 │   └── LineBuffer (linebuffer.py)
 │       └── LineActions (linebuffer.py)
 └── LineMultiple (lineroot.py)
     └── LineSeries (lineseries.py)
         └── LineIterator (lineiterator.py)
             ├── DataAccessor (lineiterator.py)
             │   ├── IndicatorBase (lineiterator.py)
             │   │   └── Indicator (indicator.py)
             │   ├── StrategyBase (lineiterator.py)
             │   │   └── Strategy (strategy.py)
             │   └── ObserverBase (lineiterator.py)
             └── AbstractDataBase (feed.py)
```

### 主要组件层次

1. **元编程层**: MetaBase → MetaParams → 各种具体元类
2. **数据结构层**: LineRoot → LineSingle/LineMultiple → LineBuffer/LineSeries
3. **迭代器层**: LineIterator → DataAccessor → 各种功能基类
4. **应用层**: Strategy, Indicator, Observer, DataFeed 等具体实现

