"""UNIT/FAKE baseline for the unconfigured Cerebro path before retirement.

No service, provider, account, or network is used. This does not exercise the
configured execution session or establish any retirement acceptance.
"""

import pytest

from backtrader.service import run_configured_cerebro


class _Cerebro:
    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize("config_form", ["omitted", "positional_none", "keyword_none"])
@pytest.mark.parametrize("raises", [False, True])
def test_unconfigured_cerebro_runs_directly(config_form, raises):
    result = object()
    error = RuntimeError("synthetic run failure")
    cerebro = _Cerebro(result=result, error=error if raises else None)
    factory_calls = []

    def runtime_factory(config):
        factory_calls.append(config)
        raise AssertionError("unconfigured run must not create a service runtime")

    # Deliberately invalid for a configured session: the direct branch does not
    # inspect session options or pass them on to Cerebro.
    session_options = {"unsupported_option": object()}
    run_value = object()
    args = [cerebro]
    kwargs = {
        "runtime_factory": runtime_factory,
        "session_options": session_options,
        "runonce": run_value,
        "maxcpus": 2,
    }
    if config_form == "positional_none":
        args.append(None)
    elif config_form == "keyword_none":
        kwargs["client_config"] = None

    if raises:
        with pytest.raises(RuntimeError) as captured:
            run_configured_cerebro(*args, **kwargs)
        assert captured.value is error
    else:
        assert run_configured_cerebro(*args, **kwargs) is result

    assert len(cerebro.calls) == 1
    run_args, run_kwargs = cerebro.calls[0]
    assert run_args == ()
    assert set(run_kwargs) == {"runonce", "maxcpus"}
    assert run_kwargs["runonce"] is run_value
    assert run_kwargs["maxcpus"] == 2
    assert factory_calls == []


def test_runtime_factory_is_keyword_only():
    cerebro = _Cerebro()

    def runtime_factory(config):
        raise AssertionError("factory must not run")

    with pytest.raises(TypeError):
        run_configured_cerebro(cerebro, None, runtime_factory)

    assert cerebro.calls == []
