"""Cerebro presentation mixin (iteration 28 split).

Moved from ``backtrader/cerebro.py``: plotting facade and report helpers.
Lazy optional-backend imports preserved (relative depth adjusted by +1).
"""

from ..dataseries import TimeFrame


class PresentationMixin:
    """Presentation half of Cerebro (see module docstring)."""

    def plot(
        self,
        plotter=None,
        numfigs=1,
        iplot=True,
        start=None,
        end=None,
        width=16,
        height=9,
        dpi=300,
        tight=True,
        use=None,
        backend="bokeh",
        **kwargs,
    ):
        """
        Plots the strategies inside cerebro

        If ``plotter`` is None, a default ``Plot`` instance is created and
        ``kwargs`` are passed to it during instantiation.

        ``numfigs`` split the plot in the indicated number of charts reducing
        chart density if wished

        ``iplot``: if ``True`` and running in a ``notebook`` the charts will be
        displayed inline

        ``use``: set it to the name of the desired matplotlib backend. It will
        take precedence over ``iplot``. Passing ``use`` also forces the
        matplotlib backend (since it is matplotlib-specific), even though the
        default backend is bokeh.

        ``backend``: plotting backend to use. Options:
            - 'bokeh': interactive Bokeh charts, tab-based browser rendering
              (default)
            - 'matplotlib': traditional matplotlib plotting
            - 'plotly': interactive Plotly charts (better for large data)

        The default ``'bokeh'`` requires the optional ``bokeh`` package. If it
        is not installed, ``cerebro.plot()`` falls back to ``matplotlib`` with a
        ``RuntimeWarning``. Pass ``backend='matplotlib'`` explicitly to silence
        the warning.

        Backend-specific notes:
            - matplotlib backend supports ``use``; other backends ignore it
              (passing ``use`` forces matplotlib, see above).
            - plotly backend accepts scheme-style kwargs from ``PlotlyScheme``.
            - bokeh backend accepts:
              ``style`` (bar/candle/line), ``scheme`` (``Scheme`` / theme instance),
              ``use_default_tabs`` and ``filter``.

        ``start``: An index to the datetime line array of the strategy or a
        ``datetime.date``, ``datetime.datetime`` instance indicating the start
        of the plot

        ``end``: An index to the datetime line array of the strategy or a
        ``datetime.date``, ``datetime.datetime`` instance indicating the end
        of the plot

        ``width``: in inches of the saved figure

        ``height``: in inches of the saved figure

        ``dpi``: quality in dots per inches of the saved figure

        ``tight``: only save actual content and not the frame of the figure
        """
        if self._exactbars > 0:
            return None

        # For plotly backend, ensure Transactions analyzer exists for buy/sell signals
        if backend == "plotly":
            for stratlist in self.runstrats:
                for strat in stratlist:
                    # Check if Transactions analyzer already exists
                    has_txn = any(a.__class__.__name__ == "Transactions" for a in strat.analyzers)
                    if not has_txn:
                        # Add Transactions analyzer retroactively is not possible
                        # So we'll rely on broker.orders instead
                        pass

        if not plotter:
            # `use` is a matplotlib backend selector; if provided, the caller
            # wants matplotlib output, so honor that even when the default
            # backend is bokeh.
            if use is not None and backend == "bokeh":
                backend = "matplotlib"

            if backend == "bokeh":
                try:
                    from ..bokeh import BokehPlot

                    plotter = BokehPlot(**kwargs)
                except ImportError:
                    # bokeh is the default but optional; fall back to matplotlib
                    # (a required dependency) so cerebro.plot() always works.
                    import warnings

                    warnings.warn(
                        "bokeh backend (default) is not available; falling back "
                        "to matplotlib. Install bokeh with: pip install bokeh, or "
                        "pass backend='matplotlib' to silence this warning.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    from .. import plot

                    plotter = plot.Plot(**kwargs)
            elif backend == "plotly":
                from .. import plot

                plotter = plot.PlotlyPlot(**kwargs)
            elif self.p.oldsync:
                from .. import plot

                plotter = plot.Plot_OldSync(**kwargs)
            else:
                from .. import plot

                plotter = plot.Plot(**kwargs)

        # pfillers = {self.datas[i]: self._plotfillers[i]
        # for i, x in enumerate(self._plotfillers)}

        # pfillers2 = {self.datas[i]: self._plotfillers2[i]
        # for i, x in enumerate(self._plotfillers2)}

        figs = []
        for stratlist in self.runstrats:
            for si, strat in enumerate(stratlist):
                rfig = plotter.plot(
                    strat,
                    figid=si * 100,
                    numfigs=numfigs,
                    iplot=iplot,
                    start=start,
                    end=end,
                    use=use,
                )
                # pfillers=pfillers2)

                figs.append(rfig)

            plotter.show()

        return figs

    def add_report_analyzers(self, riskfree_rate=0.01):
        """Automatically add analyzers required for reporting.

        Adds the following analyzers:
        - SharpeRatio: Sharpe ratio
        - DrawDown: Drawdown analysis
        - TradeAnalyzer: Trade analysis
        - SQN: System Quality Number
        - AnnualReturn: Annual returns

        Args:
            riskfree_rate: Risk-free rate, default 0.01 (1%)
        """
        from .. import analyzers

        self.addanalyzer(
            analyzers.SharpeRatio,
            _name="sharperatio",
            riskfreerate=riskfree_rate,
            timeframe=TimeFrame.Months,
        )
        self.addanalyzer(analyzers.DrawDown, _name="drawdown")
        self.addanalyzer(analyzers.TradeAnalyzer, _name="tradeanalyzer")
        self.addanalyzer(analyzers.SQN, _name="sqn")
        self.addanalyzer(analyzers.AnnualReturn, _name="annualreturn")
        self.addanalyzer(analyzers.TimeReturn, _name="timereturn", timeframe=TimeFrame.Days)

    def generate_report(
        self, output_path, format="html", template="default", user=None, memo=None, **kwargs
    ):
        """Generate backtest report.

        Args:
            output_path: Output file path
            format: Report format ('html', 'pdf', 'json')
            template: Template name or path (only for HTML/PDF)
            user: Username
            memo: Remarks/notes
            **kwargs: Additional parameters

        Returns:
            str: Output file path

        Raises:
            RuntimeError: If strategy has not been run yet

        Example:
            cerebro = bt.Cerebro()
            cerebro.addstrategy(MyStrategy)
            cerebro.adddata(data)
            cerebro.run()
            cerebro.generate_report('report.html')
        """
        if not self.runstrats:
            raise RuntimeError("No strategy has been run. Call cerebro.run() first.")

        # Get the first strategy
        strategy = self.runstrats[0][0]

        from ..reports import ReportGenerator

        report = ReportGenerator(strategy, template=template)

        format_lower = format.lower()
        if format_lower == "html":
            return report.generate_html(output_path, user=user, memo=memo, **kwargs)
        if format_lower == "pdf":
            return report.generate_pdf(output_path, user=user, memo=memo, **kwargs)
        if format_lower == "json":
            return report.generate_json(output_path, **kwargs)
        raise ValueError(f"Unsupported format: {format}. Use 'html', 'pdf', or 'json'.")
