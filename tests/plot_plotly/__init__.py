"""Plotly plotting tests for backtrader framework.

This module contains tests for the Plotly-based plotting functionality in backtrader.
Plotly provides interactive, web-based visualization capabilities for backtesting results,
complementing the standard matplotlib plotting.

The test suite covers:
    - Basic chart rendering with Plotly
    - Indicator visualization
    - Multi-data feed plotting
    - Interactive plot generation
    - Plot configuration and customization

Example:
    To run all Plotly tests::

        $ python -m pytest tests/plot_plotly/ -v

    To run a specific test::

        $ python tests/plot_plotly/test_plot_plotly.py

Dependencies:
    - plotly: Interactive plotting library
    - backtrader: Core backtesting framework

Note:
    Plotly plots are generated as HTML files that can be viewed in a web browser.
    They provide interactive features like zooming, panning, and data inspection.
"""
