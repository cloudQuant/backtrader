=============
Visualization
=============

Backtrader provides multiple visualization backends for analyzing backtesting results,
including Plotly for interactive charts, Bokeh for real-time updates, and Matplotlib
for static publication-quality charts.

Quick Start
-----------

.. code-block:: python

   cerebro = bt.Cerebro()
   # ... setup strategy and data ...
   results = cerebro.run()
   
   # Default matplotlib plot
   cerebro.plot()
   
   # Interactive Plotly chart
   cerebro.plot(backend='plotly')
   
   # Bokeh chart
   cerebro.plot(backend='bokeh')

Plotly Backend (Recommended)
----------------------------

Plotly creates interactive HTML charts with zoom, pan, and hover capabilities.

Basic Usage
^^^^^^^^^^^

.. code-block:: python

   # Interactive plot
   cerebro.plot(backend='plotly', style='candle')
   
   # Customize appearance
   cerebro.plot(
       backend='plotly',
       style='candle',           # 'candle', 'bar', 'line'
       barup='green',
       bardown='red',
       volup='lightgreen',
       voldown='lightcoral'
   )

Save to HTML
^^^^^^^^^^^^

.. code-block:: python

   from backtrader.plot import PlotlyPlot
   
   # Create plotter
   plotter = PlotlyPlot(style='candle')
   
   # Generate figures
   figs = plotter.plot(results[0])
   
   # Save to HTML file
   figs[0].write_html('backtest_chart.html')
   
   # Save as static image (requires kaleido)
   figs[0].write_image('backtest_chart.png', width=1920, height=1080)

Large Dataset Handling
^^^^^^^^^^^^^^^^^^^^^^

Plotly efficiently handles large datasets with 100k+ data points:

.. code-block:: python

   cerebro.plot(
       backend='plotly',
       style='candle',
       numfigs=1,                # Single figure
       plotdist=0.1,             # Space between subplots
   )

Bokeh Backend
-------------

Bokeh provides interactive charts with real-time update capabilities.

.. code-block:: python

   # Basic Bokeh plot
   cerebro.plot(backend='bokeh')
   
   # With output to file
   from bokeh.io import output_file, save
   output_file('backtest.html')
   figs = cerebro.plot(backend='bokeh')

Matplotlib Backend
------------------

Matplotlib creates static, publication-quality charts.

Basic Plot
^^^^^^^^^^

.. code-block:: python

   import matplotlib.pyplot as plt
   
   # Default plot
   cerebro.plot()
   
   # Candlestick style
   cerebro.plot(style='candle')
   
   # Line chart
   cerebro.plot(style='line')
   
   # Bar chart (OHLC)
   cerebro.plot(style='bar')

Customization
^^^^^^^^^^^^^

.. code-block:: python

   cerebro.plot(
       style='candle',
       barup='green',
       bardown='red',
       volup='lightgreen',
       voldown='lightcoral',
       fmt_x_data='%Y-%m-%d',
       fmt_x_ticks='%b %d',
       plotdist=0.5,
       numfigs=1,
       width=16,
       height=9,
       dpi=100,
       tight=True
   )

Save Figure
^^^^^^^^^^^

.. code-block:: python

   import matplotlib.pyplot as plt
   
   cerebro.plot(style='candle')
   plt.savefig('backtest.png', dpi=300, bbox_inches='tight')
   plt.savefig('backtest.pdf', bbox_inches='tight')

Indicator Visualization
-----------------------

Configure Indicator Display
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def __init__(self):
           # Indicator in main plot
           self.sma = bt.indicators.SMA(period=20)
           self.sma.plotinfo.plotmaster = self.data
           
           # Indicator in subplot
           self.rsi = bt.indicators.RSI(period=14)
           self.rsi.plotinfo.subplot = True
           
           # Custom line styles
           self.bbands = bt.indicators.BollingerBands()
           self.bbands.plotlines.top._plotskip = False
           self.bbands.plotlines.mid.color = 'blue'
           self.bbands.plotlines.bot.linestyle = '--'

Custom Indicator Plot
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class MyIndicator(bt.Indicator):
       lines = ('signal',)
       
       plotinfo = dict(
           plot=True,
           subplot=True,
           plotname='My Signal',
           plotabove=False,
           plotlinelabels=True
       )
       
       plotlines = dict(
           signal=dict(
               _name='Signal',
               color='blue',
               linewidth=1.5,
               linestyle='-'
           )
       )

Observer Visualization
----------------------

Observers display trade information on charts:

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # Add built-in observers
   cerebro.addobserver(bt.observers.BuySell)      # Buy/Sell markers
   cerebro.addobserver(bt.observers.Trades)       # Trade P&L
   cerebro.addobserver(bt.observers.Value)        # Portfolio value
   cerebro.addobserver(bt.observers.DrawDown)     # Drawdown
   cerebro.addobserver(bt.observers.Cash)         # Cash levels
   
   # Customize observer appearance
   cerebro.addobserver(
       bt.observers.BuySell,
       barplot=True,
       bardist=0.015
   )

Multi-Data Visualization
------------------------

.. code-block:: python

   cerebro = bt.Cerebro()
   cerebro.adddata(data1, name='Stock1')
   cerebro.adddata(data2, name='Stock2')
   
   results = cerebro.run()
   
   # Plot all data in separate figures
   cerebro.plot(numfigs=2)
   
   # Plot specific data
   cerebro.plot(plotdata=[0])  # Only first data

Professional Reports
--------------------

Generate comprehensive HTML reports:

.. code-block:: python

   # Add report analyzers
   cerebro.add_report_analyzers(riskfree_rate=0.02)
   
   # Run backtest
   results = cerebro.run()
   
   # Generate report
   cerebro.generate_report(
       filename='report.html',
       user='Trader',
       memo='SMA Crossover Strategy Backtest',
       strategy_name='SMA Cross'
   )

Report Contents
^^^^^^^^^^^^^^^

- **Summary Statistics**: Total return, Sharpe ratio, max drawdown
- **Equity Curve**: Portfolio value over time
- **Drawdown Chart**: Drawdown percentage over time
- **Trade Analysis**: Win rate, profit factor, average trade
- **Monthly Returns**: Heatmap of monthly performance
- **Position Analysis**: Trade entry/exit details

Plot Configuration Reference
----------------------------

plotinfo Options
^^^^^^^^^^^^^^^^

.. list-table::
   :widths: 20 15 65
   :header-rows: 1

   * - Option
     - Default
     - Description
   * - plot
     - True
     - Enable/disable plotting
   * - subplot
     - False
     - Plot in separate subplot
   * - plotmaster
     - None
     - Data to plot alongside
   * - plotname
     - ''
     - Custom plot name
   * - plotabove
     - False
     - Plot above main chart
   * - plotlinelabels
     - False
     - Show line labels

Style Options
^^^^^^^^^^^^^

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Style
     - Description
   * - candle
     - Japanese candlestick chart
   * - bar
     - OHLC bar chart
   * - line
     - Line chart (close prices)

Best Practices
--------------

1. **Performance**: Use Plotly for large datasets (>10k bars)
2. **Publication**: Use Matplotlib for papers and reports
3. **Development**: Use Bokeh for live/real-time development
4. **Reports**: Use ``generate_report()`` for comprehensive analysis

See Also
--------

- :doc:`analyzers` - Performance analysis
- :doc:`strategies` - Strategy development
