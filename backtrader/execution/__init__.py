"""Backtrader-owned execution contracts and framework-side ports.

This package owns the order and provider-handoff contracts consumed by the
framework, plus adapters that implement externally defined journal ports. It
does not contain the external execution SDK's journal implementation.

Keep package initialization inert: importing :mod:`backtrader.execution` alone
must not load an optional SDK or provider package. Import a focused submodule
when its contracts or adapters are needed.
"""

__all__ = []
