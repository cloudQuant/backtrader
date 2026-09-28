#!/usr/bin/env python
"""Backward-compatible shim for the legacy TradeLogger module path."""

from .trade_logger import TradeLogger

__all__ = ["TradeLogger"]
