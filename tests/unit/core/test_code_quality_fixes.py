"""Tests for code quality fixes.

Tests cover:
1. Mutable default argument fix in Strategy._notify
2. Resource leak fix in CSVDataBase.preload() null check
3. Centralized is_finite_real in mathsupport
4. ModuleImportError.args preservation fix
"""

import math
import pytest


class TestIsFiniteReal:
    """Test the centralized is_finite_real utility in mathsupport."""

    def test_finite_int(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real(42) is True

    def test_finite_float(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real(3.14) is True

    def test_zero(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real(0) is True
        assert is_finite_real(0.0) is True

    def test_negative(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real(-1.5) is True

    def test_inf(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real(float("inf")) is False
        assert is_finite_real(float("-inf")) is False

    def test_nan(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real(float("nan")) is False

    def test_complex(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real(1 + 2j) is False
        assert is_finite_real(complex(1, 0)) is False

    def test_none(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real(None) is False

    def test_string(self):
        from backtrader.mathsupport import is_finite_real
        assert is_finite_real("abc") is False

    def test_bool(self):
        from backtrader.mathsupport import is_finite_real
        # bool is a subclass of int, so True/False are finite reals
        assert is_finite_real(True) is True
        assert is_finite_real(False) is True


class TestModuleImportErrorArgs:
    """Test that ModuleImportError preserves the message in args."""

    def test_message_in_str(self):
        from backtrader.errors import ModuleImportError
        err = ModuleImportError("test module missing")
        assert "test module missing" in str(err)

    def test_message_in_args(self):
        from backtrader.errors import ModuleImportError
        err = ModuleImportError("test module missing")
        assert "test module missing" in err.args

    def test_message_with_extra_args(self):
        from backtrader.errors import ModuleImportError
        err = ModuleImportError("test module missing", "extra1", "extra2")
        assert err.args == ("test module missing", "extra1", "extra2")
        assert "test module missing" in str(err)

    def test_from_module_import_error_message(self):
        from backtrader.errors import FromModuleImportError
        err = FromModuleImportError("cannot import X from Y")
        assert "cannot import X from Y" in str(err)
        assert "cannot import X from Y" in err.args

    def test_from_module_import_error_with_extra_args(self):
        from backtrader.errors import FromModuleImportError
        err = FromModuleImportError("cannot import X", "hint1")
        assert err.args == ("cannot import X", "hint1")

    def test_raise_and_catch(self):
        from backtrader.errors import ModuleImportError
        with pytest.raises(ModuleImportError, match="mymodule"):
            raise ModuleImportError("mymodule not found")


class TestMutableDefaultArgs:
    """Test that _notify mutable default argument fix works correctly."""

    def test_notify_default_args_are_independent(self):
        """Verify that calling _notify without args doesn't share state."""
        # We can't easily call _notify directly without a full cerebro setup,
        # but we can verify the function signature no longer uses mutable defaults
        import inspect
        from backtrader.strategy import Strategy

        sig = inspect.signature(Strategy._notify)
        params = sig.parameters

        # qorders default should be None, not []
        assert params["qorders"].default is None, (
            "qorders default should be None, not a mutable list"
        )
        assert params["qtrades"].default is None, (
            "qtrades default should be None, not a mutable list"
        )

    def test_signal_strategy_notify_defaults(self):
        """Verify SignalStrategy._notify also uses None defaults."""
        import inspect
        from backtrader.strategy import SignalStrategy

        sig = inspect.signature(SignalStrategy._notify)
        params = sig.parameters

        assert params["qorders"].default is None
        assert params["qtrades"].default is None


class TestCSVPreloadNullCheck:
    """Test that CSVDataBase.preload handles None file handle."""

    def test_preload_with_none_file(self):
        """Verify preload doesn't crash if self.f is already None."""
        from backtrader.feed import CSVDataBase

        # Create a minimal CSVDataBase instance to test preload safety
        # We just need to verify that the null check exists in the code
        import inspect
        source = inspect.getsource(CSVDataBase.preload)
        assert "if self.f is not None" in source, (
            "preload() should check self.f is not None before calling close()"
        )


class TestAnalyzerImports:
    """Test that analyzers use centralized is_finite_real from mathsupport."""

    def test_sharpe_uses_centralized(self):
        """Verify sharpe.py imports is_finite_real from mathsupport."""
        import backtrader.analyzers.sharpe as mod
        import inspect
        source = inspect.getsource(mod)
        assert "from ..mathsupport import" in source and "is_finite_real" in source

    def test_drawdown_uses_centralized(self):
        """Verify drawdown.py imports is_finite_real from mathsupport."""
        import backtrader.analyzers.drawdown as mod
        import inspect
        source = inspect.getsource(mod)
        assert "from ..mathsupport import is_finite_real" in source

    def test_leverage_uses_centralized(self):
        """Verify leverage.py imports is_finite_real from mathsupport."""
        import backtrader.analyzers.leverage as mod
        import inspect
        source = inspect.getsource(mod)
        assert "from ..mathsupport import is_finite_real" in source

    def test_no_local_is_finite_real_in_sharpe(self):
        """Verify sharpe.py no longer has local _is_finite_real definition."""
        import backtrader.analyzers.sharpe as mod
        assert not hasattr(mod, "_is_finite_real"), (
            "sharpe.py should not have local _is_finite_real"
        )

    def test_no_local_is_finite_real_in_drawdown(self):
        """Verify drawdown.py no longer has local _is_finite_real definition."""
        import backtrader.analyzers.drawdown as mod
        assert not hasattr(mod, "_is_finite_real"), (
            "drawdown.py should not have local _is_finite_real"
        )

    def test_no_local_is_finite_real_in_leverage(self):
        """Verify leverage.py no longer has local _is_finite_real definition."""
        import backtrader.analyzers.leverage as mod
        assert not hasattr(mod, "_is_finite_real"), (
            "leverage.py should not have local _is_finite_real"
        )
