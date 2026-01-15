#!/usr/bin/env python
"""
Main report generator.

Generates backtest reports in HTML, PDF, and JSON formats.
"""

import json
import os
from datetime import datetime

from .charts import ReportChart
from .performance import PerformanceCalculator

# Try to import Jinja2
try:
    from jinja2 import BaseLoader, Environment, FileSystemLoader

    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

# Try to import weasyprint (PDF generation)
try:
    from weasyprint import HTML as WeasyHTML

    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


# Default HTML template
DEFAULT_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Backtrader Report - {{ strategy_name }}</title>
<style>
    @page {
        size: A4;
        margin: 12mm 15mm;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { 
        font-family: 'Helvetica Neue', Helvetica, Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
        font-size: 10pt;
        line-height: 1.4;
        color: #2c3e50;
        background: white;
    }
    
    /* Header - Compact */
    .header {
        background: #1a365d;
        color: white;
        padding: 15px 20px;
        margin-bottom: 12px;
        border-bottom: 3px solid #3182ce;
    }
    .header h1 { 
        font-size: 18pt; 
        font-weight: 600;
        margin-bottom: 3px;
    }
    .header .subtitle {
        font-size: 11pt;
        font-weight: 400;
        margin-bottom: 10px;
        opacity: 0.9;
    }
    .header-info { 
        font-size: 9pt;
        line-height: 1.6;
    }
    .header-info span {
        margin-right: 20px;
    }
    .header-info b { color: #90cdf4; }
    
    /* Sections - Minimal spacing */
    .section { 
        margin-bottom: 8px;
    }
    .section h2 { 
        padding: 6px 12px;
        margin-bottom: 8px;
        background: #edf2f7;
        border-left: 3px solid #3182ce;
        font-size: 12pt;
        font-weight: 600;
        color: #1a365d;
    }
    
    /* Notes */
    .notes {
        background: #fffbeb;
        border: 1px solid #f6e05e;
        padding: 8px 12px;
        margin: 0 12px 10px 12px;
        font-size: 9pt;
        color: #744210;
    }
    
    /* Charts - New Page */
    .section.charts-page {
        page-break-before: always;
    }
    .charts { 
        padding: 0 12px;
    }
    .charts img { 
        width: 100%;
        height: auto;
        margin-bottom: 12px;
        border: 1px solid #e2e8f0;
    }
    
    /* Params - New Page */
    .section.params-page {
        page-break-before: always;
    }
    
    /* Metrics Table - Compact */
    .metrics-container {
        padding: 0 12px;
    }
    .metrics-table { 
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 10px;
        font-size: 9pt;
    }
    .metrics-table td {
        padding: 5px 8px;
        border-bottom: 1px solid #e2e8f0;
    }
    .metrics-table .group-header td {
        background: #3182ce;
        color: white;
        font-weight: 600;
        font-size: 9pt;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 6px 8px;
    }
    .metrics-table .label {
        color: #4a5568;
        width: 22%;
    }
    .metrics-table .value {
        font-weight: 600;
        color: #2d3748;
        text-align: right;
        width: 28%;
    }
    .metrics-table .value.positive { color: #276749; }
    .metrics-table .value.negative { color: #c53030; }
    
    /* Parameters - Compact */
    .params-table {
        width: 60%;
        border-collapse: collapse;
        font-size: 9pt;
        margin: 0 12px;
    }
    .params-table td {
        padding: 4px 8px;
        border: 1px solid #e2e8f0;
    }
    .params-table .param-name {
        background: #f7fafc;
        font-weight: 500;
        width: 40%;
    }
    
    /* Footer - Minimal */
    .footer { 
        text-align: center; 
        color: #718096; 
        font-size: 8pt;
        padding: 10px;
        border-top: 1px solid #e2e8f0;
        margin-top: 15px;
    }
    .footer p { margin: 2px 0; }
</style>
</head>
<body>

<div class="header">
    <h1>{{ strategy_name }}</h1>
    <div class="subtitle">Backtest Performance Report</div>
    <div class="header-info">
        <span><b>Data:</b> {{ data_name }}</span>
        <span><b>Period:</b> {{ start_date }} ~ {{ end_date }}</span>
        <span><b>Bars:</b> {{ bars }}</span>
        {% if user %}<span><b>Analyst:</b> {{ user }}</span>{% endif %}
        <span><b>Generated:</b> {{ report_date }}</span>
    </div>
</div>

{% if memo %}
<div class="section">
    <h2>Notes</h2>
    <div class="notes">{{ memo }}</div>
</div>
{% endif %}

<div class="section">
    <h2>Performance Summary</h2>
    <div class="metrics-container">
        <table class="metrics-table">
            <tr class="group-header"><td colspan="4">Profit & Loss</td></tr>
            <tr>
                <td class="label">Start Capital</td>
                <td class="value">{{ "${:,.2f}".format(start_cash) if start_cash else 'N/A' }}</td>
                <td class="label">End Value</td>
                <td class="value">{{ "${:,.2f}".format(end_value) if end_value else 'N/A' }}</td>
            </tr>
            <tr>
                <td class="label">Net Profit</td>
                <td class="value {{ 'positive' if rpl and rpl > 0 else 'negative' if rpl and rpl < 0 else '' }}">{{ "${:,.2f}".format(rpl) if rpl else 'N/A' }}</td>
                <td class="label">Total Return</td>
                <td class="value {{ 'positive' if total_return and total_return > 0 else 'negative' if total_return and total_return < 0 else '' }}">{{ "{:.2f}%".format(total_return) if total_return else 'N/A' }}</td>
            </tr>
            <tr>
                <td class="label">Annual Return</td>
                <td class="value {{ 'positive' if annual_return and annual_return > 0 else 'negative' if annual_return and annual_return < 0 else '' }}">{{ "{:.2f}%".format(annual_return) if annual_return else 'N/A' }}</td>
                <td class="label">Profit Factor</td>
                <td class="value">{{ "{:.2f}".format(profit_factor) if profit_factor else 'N/A' }}</td>
            </tr>
            
            <tr class="group-header"><td colspan="4">Risk Metrics</td></tr>
            <tr>
                <td class="label">Max Drawdown ($)</td>
                <td class="value negative">{{ "${:,.2f}".format(max_money_drawdown) if max_money_drawdown else 'N/A' }}</td>
                <td class="label">Max Drawdown (%)</td>
                <td class="value negative">{{ "{:.2f}%".format(max_pct_drawdown) if max_pct_drawdown else 'N/A' }}</td>
            </tr>
            <tr>
                <td class="label">Sharpe Ratio</td>
                <td class="value">{{ "{:.2f}".format(sharpe_ratio) if sharpe_ratio else 'N/A' }}</td>
                <td class="label">Calmar Ratio</td>
                <td class="value">{{ "{:.2f}".format(calmar_ratio) if calmar_ratio else 'N/A' }}</td>
            </tr>
            <tr>
                <td class="label">SQN Score</td>
                <td class="value">{{ "{:.2f}".format(sqn_score) if sqn_score else 'N/A' }}</td>
                <td class="label">SQN Rating</td>
                <td class="value">{{ sqn_human if sqn_human else 'N/A' }}</td>
            </tr>
            
            <tr class="group-header"><td colspan="4">Trade Statistics</td></tr>
            <tr>
                <td class="label">Total Trades</td>
                <td class="value">{{ total_number_trades }}</td>
                <td class="label">Closed Trades</td>
                <td class="value">{{ trades_closed }}</td>
            </tr>
            <tr>
                <td class="label">Win Rate</td>
                <td class="value">{{ "{:.2f}%".format(pct_winning) if pct_winning else 'N/A' }}</td>
                <td class="label">Avg Win</td>
                <td class="value positive">{{ "${:,.2f}".format(avg_money_winning) if avg_money_winning else 'N/A' }}</td>
            </tr>
            <tr>
                <td class="label">Avg Loss</td>
                <td class="value negative">{{ "${:,.2f}".format(avg_money_losing) if avg_money_losing else 'N/A' }}</td>
                <td class="label">Best Trade</td>
                <td class="value positive">{{ "${:,.2f}".format(best_winning_trade) if best_winning_trade else 'N/A' }}</td>
            </tr>
            <tr>
                <td class="label">Worst Trade</td>
                <td class="value negative">{{ "${:,.2f}".format(worst_losing_trade) if worst_losing_trade else 'N/A' }}</td>
                <td class="label"></td>
                <td class="value"></td>
            </tr>
        </table>
    </div>
</div>

<div class="section charts-page">
    <h2>Performance Charts</h2>
    <div class="charts">
        {% if equity_curve_img %}<img src="{{ equity_curve_img }}" alt="Equity Curve">{% endif %}
        {% if return_bars_img %}<img src="{{ return_bars_img }}" alt="Return Bars">{% endif %}
        {% if drawdown_img %}<img src="{{ drawdown_img }}" alt="Drawdown">{% endif %}
    </div>
</div>

{% if params %}
<div class="section params-page">
    <h2>Strategy Parameters</h2>
    <div class="metrics-container">
        <table class="params-table">
            {% for key, value in params.items() %}
            <tr>
                <td class="param-name">{{ key }}</td>
                <td>{{ value }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
</div>
{% endif %}

<div class="footer">
    <p>Generated by <strong>Backtrader Reports Module</strong></p>
    <p>{{ report_date }}</p>
</div>

</body>
</html>
"""


class ReportGenerator:
    """Main report generator.

    Generates backtest reports in HTML, PDF, and JSON formats.

    Attributes:
        strategy: Strategy instance
        calculator: Performance calculator
        charts: Chart generator

    Usage example:
        report = ReportGenerator(strategy)
        report.generate_html('report.html')
        report.generate_pdf('report.pdf')
        report.generate_json('report.json')
    """

    def __init__(self, strategy, template="default"):
        """Initialize the report generator.

        Args:
            strategy: backtrader strategy instance
            template: Template name or template string
        """
        self.strategy = strategy
        self.calculator = PerformanceCalculator(strategy)
        self.charts = ReportChart()
        self.template = template

        # User information
        self._user = None
        self._memo = None

    def generate_html(self, output_path, user=None, memo=None, **kwargs):
        """Generate HTML report.

        Args:
            output_path: Output file path
            user: Username
            memo: Notes
            **kwargs: Additional template variables

        Returns:
            str: Output file path
        """
        if not JINJA2_AVAILABLE:
            raise ImportError(
                "jinja2 is required for HTML report generation. "
                "Install it with: pip install jinja2"
            )

        self._user = user
        self._memo = memo

        # Collect all data
        context = self._build_context(**kwargs)

        # Render template
        html_content = self._render_template(context)

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Clean up charts
        self.charts.close_all()

        return output_path

    def generate_pdf(self, output_path, user=None, memo=None, **kwargs):
        """Generate PDF report.

        Args:
            output_path: Output file path
            user: Username
            memo: Notes
            **kwargs: Additional template variables

        Returns:
            str: Output file path
        """
        if not WEASYPRINT_AVAILABLE:
            raise ImportError(
                "weasyprint is required for PDF report generation. "
                "Install it with: pip install weasyprint"
            )

        self._user = user
        self._memo = memo

        # Collect all data
        context = self._build_context(**kwargs)

        # Render template
        html_content = self._render_template(context)

        # Convert to PDF
        WeasyHTML(string=html_content).write_pdf(output_path)

        # Clean up charts
        self.charts.close_all()

        return output_path

    def generate_json(self, output_path, indent=2, **kwargs):
        """Generate JSON report.

        Args:
            output_path: Output file path
            indent: JSON indentation
            **kwargs: Additional data

        Returns:
            str: Output file path
        """
        # Get all metrics
        metrics = self.calculator.get_all_metrics()
        strategy_info = self.calculator.get_strategy_info()
        data_info = self.calculator.get_data_info()

        # Build JSON structure
        report_data = {
            "generated_at": datetime.now().isoformat(),
            "strategy": strategy_info,
            "data": {
                "name": data_info.get("data_name"),
                "start_date": (
                    str(data_info.get("start_date")) if data_info.get("start_date") else None
                ),
                "end_date": str(data_info.get("end_date")) if data_info.get("end_date") else None,
                "bars": data_info.get("bars"),
            },
            "metrics": {
                "pnl": {
                    "start_cash": metrics.get("start_cash"),
                    "end_value": metrics.get("end_value"),
                    "net_profit": metrics.get("rpl"),
                    "total_return": metrics.get("total_return"),
                    "annual_return": metrics.get("annual_return"),
                    "profit_factor": metrics.get("profit_factor"),
                },
                "risk": {
                    "max_drawdown_money": metrics.get("max_money_drawdown"),
                    "max_drawdown_pct": metrics.get("max_pct_drawdown"),
                    "sharpe_ratio": metrics.get("sharpe_ratio"),
                    "calmar_ratio": metrics.get("calmar_ratio"),
                    "sqn_score": metrics.get("sqn_score"),
                    "sqn_rating": metrics.get("sqn_human"),
                },
                "trades": {
                    "total": metrics.get("total_number_trades"),
                    "closed": metrics.get("trades_closed"),
                    "won": metrics.get("trades_won"),
                    "lost": metrics.get("trades_lost"),
                    "win_rate": metrics.get("pct_winning"),
                    "avg_win": metrics.get("avg_money_winning"),
                    "avg_loss": metrics.get("avg_money_losing"),
                    "best_trade": metrics.get("best_winning_trade"),
                    "worst_trade": metrics.get("worst_losing_trade"),
                },
            },
            **kwargs,
        }

        # Handle non-serializable values
        report_data = self._make_json_serializable(report_data)

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=indent, ensure_ascii=False)

        return output_path

    def _build_context(self, **kwargs):
        """Build template context.

        Returns:
            dict: Template variables dictionary
        """
        # Get metrics
        metrics = self.calculator.get_all_metrics()
        strategy_info = self.calculator.get_strategy_info()
        data_info = self.calculator.get_data_info()

        # Generate charts
        dates, values = self.calculator.get_equity_curve()
        benchmark_dates, benchmark_values = self.calculator.get_buynhold_curve()

        equity_curve_img = ""
        return_bars_img = ""
        drawdown_img = ""

        if dates and values:
            # Equity curve
            fig_equity = self.charts.plot_equity_curve(
                dates, values, benchmark_dates, benchmark_values
            )
            if fig_equity:
                equity_curve_img = self.charts.to_base64(fig_equity)

            # Return bars chart
            fig_returns = self.charts.plot_return_bars(dates, values)
            if fig_returns:
                return_bars_img = self.charts.to_base64(fig_returns)

            # Drawdown chart
            fig_drawdown = self.charts.plot_drawdown(dates, values)
            if fig_drawdown:
                drawdown_img = self.charts.to_base64(fig_drawdown)

        # Build context
        context = {
            # Strategy information
            "strategy_name": strategy_info.get("strategy_name", "Strategy"),
            "params": strategy_info.get("params", {}),
            # Data information
            "data_name": data_info.get("data_name", "Data"),
            "start_date": (
                str(data_info.get("start_date", ""))[:10] if data_info.get("start_date") else "N/A"
            ),
            "end_date": (
                str(data_info.get("end_date", ""))[:10] if data_info.get("end_date") else "N/A"
            ),
            "bars": data_info.get("bars", 0),
            # User information
            "user": self._user,
            "memo": self._memo,
            "report_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            # Charts
            "equity_curve_img": equity_curve_img,
            "return_bars_img": return_bars_img,
            "drawdown_img": drawdown_img,
            # Metrics
            **metrics,
            **kwargs,
        }

        return context

    def _render_template(self, context):
        """Render template.

        Args:
            context: Template variables dictionary

        Returns:
            str: Rendered HTML
        """
        if self.template == "default":
            # Use default template
            env = Environment(loader=BaseLoader())
            template = env.from_string(DEFAULT_TEMPLATE)
        else:
            # Try to load as file path
            if os.path.isfile(self.template):
                template_dir = os.path.dirname(self.template)
                template_name = os.path.basename(self.template)
                env = Environment(loader=FileSystemLoader(template_dir))
                template = env.get_template(template_name)
            else:
                # Handle as template string
                env = Environment(loader=BaseLoader())
                template = env.from_string(self.template)

        return template.render(**context)

    def _make_json_serializable(self, obj):
        """Make object JSON serializable.

        Args:
            obj: Object to process

        Returns:
            Serializable object
        """
        import math

        if isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(v) for v in obj]
        elif isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        elif hasattr(obj, "isoformat") and callable(getattr(obj, "isoformat", None)):
            return obj.isoformat()
        elif hasattr(obj, "__dict__"):
            return str(obj)
        else:
            return obj

    def get_metrics(self):
        """Get all performance metrics.

        Returns:
            dict: Performance metrics dictionary
        """
        return self.calculator.get_all_metrics()

    def print_summary(self):
        """Print performance summary to console."""
        metrics = self.calculator.get_all_metrics()
        strategy_info = self.calculator.get_strategy_info()

        print("\n" + "=" * 60)
        print(f"Strategy: {strategy_info.get('strategy_name', 'Strategy')}")
        print("=" * 60)

        print("\n*** PnL ***")
        print(
            f"Start Capital         : {metrics.get('start_cash', 'N/A'):,.2f}"
            if metrics.get("start_cash")
            else "Start Capital         : N/A"
        )
        print(
            f"Net Profit            : {metrics.get('rpl', 'N/A'):,.2f}"
            if metrics.get("rpl")
            else "Net Profit            : N/A"
        )
        print(
            f"Total Return          : {metrics.get('total_return', 'N/A'):.2f}%"
            if metrics.get("total_return")
            else "Total Return          : N/A"
        )
        print(
            f"Annual Return         : {metrics.get('annual_return', 'N/A'):.2f}%"
            if metrics.get("annual_return")
            else "Annual Return         : N/A"
        )

        print("\n*** Risk ***")
        print(
            f"Max Drawdown ($)      : {metrics.get('max_money_drawdown', 'N/A'):,.2f}"
            if metrics.get("max_money_drawdown")
            else "Max Drawdown ($)      : N/A"
        )
        print(
            f"Max Drawdown (%)      : {metrics.get('max_pct_drawdown', 'N/A'):.2f}%"
            if metrics.get("max_pct_drawdown")
            else "Max Drawdown (%)      : N/A"
        )
        print(
            f"Sharpe Ratio          : {metrics.get('sharpe_ratio', 'N/A'):.2f}"
            if metrics.get("sharpe_ratio")
            else "Sharpe Ratio          : N/A"
        )

        print("\n*** Trades ***")
        print(f"Total Trades          : {metrics.get('total_number_trades', 0)}")
        print(
            f"Win Rate              : {metrics.get('pct_winning', 'N/A'):.2f}%"
            if metrics.get("pct_winning")
            else "Win Rate              : N/A"
        )
        print(
            f"SQN Score             : {metrics.get('sqn_score', 'N/A'):.2f}"
            if metrics.get("sqn_score")
            else "SQN Score             : N/A"
        )
        print(f"SQN Rating            : {metrics.get('sqn_human', 'N/A')}")

        print("\n" + "=" * 60)
