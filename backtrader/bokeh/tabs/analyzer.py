#!/usr/bin/env python
"""
Analyzer tab.

Displays results of all analyzers.
"""

from ..tab import BokehTab

try:
    from bokeh.layouts import column
    from bokeh.models import ColumnDataSource, DataTable, TableColumn
    from bokeh.models.widgets import Div

    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False


class AnalyzerTab(BokehTab):
    """Analyzer tab.

    Displays analysis results of all analyzers in the strategy.
    """

    def _is_useable(self):
        """Check if useable.

        Useable when strategy has analyzers.
        """
        if not BOKEH_AVAILABLE:
            return False
        strategy = self.strategy
        if strategy is None:
            return False
        return len(getattr(strategy, "analyzers", [])) > 0

    def _get_panel(self):
        """Get panel content.

        Returns:
            tuple: (widget, title)
        """
        strategy = self.strategy
        scheme = self.scheme

        # Create analyzer results display
        widgets = []

        for analyzer in strategy.analyzers:
            analyzer_name = analyzer.__class__.__name__

            # Get analysis results
            try:
                analysis = analyzer.get_analysis()
            except Exception:
                analysis = {}

            # Create title
            title_div = Div(
                text=f'<h3 style="color: {scheme.text_color if scheme else "#333"};">{analyzer_name}</h3>',
                sizing_mode="stretch_width",
            )
            widgets.append(title_div)

            # Convert analysis results to table data
            data = self._flatten_analysis(analysis)

            if data:
                source = ColumnDataSource(
                    data={"key": list(data.keys()), "value": [str(v) for v in data.values()]}
                )

                columns = [
                    TableColumn(field="key", title="Metric"),
                    TableColumn(field="value", title="Value"),
                ]

                table = DataTable(
                    source=source,
                    columns=columns,
                    width=400,
                    height=min(len(data) * 25 + 30, 300),
                    index_position=None,
                )
                widgets.append(table)
            else:
                empty_div = Div(text="<p>No data available</p>")
                widgets.append(empty_div)

        content = column(*widgets, sizing_mode="stretch_width")
        return content, "Analyzers"

    def _flatten_analysis(self, analysis, prefix=""):
        """Flatten nested analysis results.

        Args:
            analysis: Analysis result dictionary
            prefix: Key prefix

        Returns:
            dict: Flattened dictionary
        """
        result = {}

        if isinstance(analysis, dict):
            for key, value in analysis.items():
                new_key = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, dict):
                    result.update(self._flatten_analysis(value, new_key))
                else:
                    result[new_key] = value
        else:
            result[prefix or "value"] = analysis

        return result
