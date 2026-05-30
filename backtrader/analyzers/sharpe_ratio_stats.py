"""Sharpe Ratio Statistics Module - Advanced Sharpe ratio calculations.

This module provides functions for calculating Sharpe ratio statistics
including estimated, probabilistic, and defecto Sharpe ratios, along
with their confidence intervals and significance tests.

Functions:
    estimated_sharpe_ratio: Calculate basic Sharpe ratio.
    ann_estimated_sharpe_ratio: Calculate annualized Sharpe ratio.
    estimated_sharpe_ratio_stdev: Standard deviation of Sharpe estimation.
    probabilistic_sharpe_ratio: PSR calculation.
    min_track_record_length: Minimum track record for significance.
    sharpe_ratio_defacto: Defacto Sharpe ratio calculation.
"""

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


def _is_integer_like(value):
    try:
        return (
            not isinstance(value, (bool, np.bool_))
            and np.isscalar(value)
            and np.isfinite(value)
            and float(value).is_integer()
        )
    except (TypeError, ValueError):
        return False


def _is_finite_value(value):
    try:
        return bool(np.all(np.isfinite(np.asarray(value))))
    except (TypeError, ValueError):
        return False


def _average_upper_triangle_correlation(trials_returns):
    """Compute the mean pairwise correlation across trial return columns."""
    corr_matrix = trials_returns.corr()
    if corr_matrix.empty:
        return 0.0

    upper = corr_matrix.values[np.triu_indices_from(corr_matrix.values, 1)]
    if upper.size == 0:
        return 0.0

    avg_corr = np.nanmean(upper)
    if not np.isfinite(avg_corr):
        return 0.0

    return float(avg_corr)


def estimated_sharpe_ratio(returns):
    """
    Calculate the estimated sharpe ratio (risk_free=0).

    Parameters
    ----------
    returns: `np.array`, pd.Series, pd.DataFrame

    Returns
    -------
    float, pd.Series
    """
    if returns is None:
        raise ValueError("estimated_sharpe_ratio requires returns")
    if len(returns) <= 1:
        raise ValueError("estimated_sharpe_ratio requires at least 2 return samples")

    return returns.mean() / returns.std(ddof=1)


def ann_estimated_sharpe_ratio(returns=None, periods=261, *, sr=None):
    """
    Calculate the annualized estimated sharpe ratio (risk_free=0).

    Parameters
    ----------
    returns: `np.array`, pd.Series, pd.DataFrame

    periods: int
        How many items in `returns` complete a Year.
        If returns are daily: 261, weekly: 52, monthly: 12, ...

    sr: float, `np.array`, pd.Series, pd.DataFrame
        Sharpe ratio to be annualized, its frequency must be coherent with `periods`

    Returns
    -------
    float, pd.Series
    """
    if returns is None and sr is None:
        raise ValueError("ann_estimated_sharpe_ratio requires returns or sr")
    if not _is_integer_like(periods):
        raise ValueError("ann_estimated_sharpe_ratio requires integer periods")
    periods = int(periods)
    if periods <= 0:
        raise ValueError("ann_estimated_sharpe_ratio requires periods > 0")
    if sr is not None and not _is_finite_value(sr):
        raise ValueError("ann_estimated_sharpe_ratio requires finite sr")

    if sr is None:
        if len(returns) <= 1:
            raise ValueError(
                "ann_estimated_sharpe_ratio requires at least 2 return samples when sr is None"
            )
        sr = estimated_sharpe_ratio(returns)
    sr = sr * np.sqrt(periods)
    return sr


def estimated_sharpe_ratio_stdev(returns=None, *, n=None, skew=None, kurtosis=None, sr=None):
    """
    Calculate the standard deviation of the sharpe ratio estimation.

    Parameters
    ----------
    returns: `np.array`, pd.Series, pd.DataFrame
        If no `returns` are passed it is mandatory to pass the other four parameters.

    n: int
        Number of returns samples used for calculating `skew`, `kurtosis` and `sr`.

    skew: float, `np.array`, pd.Series, pd.DataFrame
        The third moment expressed in the same frequency as the other parameters.
        `Skew`=0 for normal returns.

    kurtosis: float, `np.array`, pd.Series, pd.DataFrame
        The fourth moment expressed in the same frequency as the other parameters.
        `Kurtosis`=3 for normal returns.

    sr: float, `np.array`, pd.Series, pd.DataFrame
        Sharpe ratio expressed in the same frequency as the other parameters.

    Returns
    -------
    float, pd.Series

    Notes
    -----
    This formula generalizes for both normal and non-normal returns.
    https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643
    """
    # if type(returns) != pd.DataFrame:
    #     _returns = pd.DataFrame(returns)
    # else:
    #     _returns = returns.copy()

    if returns is None:
        if any(param is None for param in (n, skew, kurtosis, sr)):
            raise ValueError(
                "estimated_sharpe_ratio_stdev requires n, skew, kurtosis, and sr when returns is None"
            )
        _returns = None
    elif isinstance(returns, pd.DataFrame):
        _returns = pd.DataFrame(returns)
    else:
        _returns = returns.copy()

    if _returns is not None and n is None:
        n = len(_returns)
    if not _is_integer_like(n):
        raise ValueError("estimated_sharpe_ratio_stdev requires integer n")
    n = int(n)
    if n <= 1:
        raise ValueError("estimated_sharpe_ratio_stdev requires n > 1")
    if skew is not None and not _is_finite_value(skew):
        raise ValueError("estimated_sharpe_ratio_stdev requires finite skew")
    if kurtosis is not None and not _is_finite_value(kurtosis):
        raise ValueError("estimated_sharpe_ratio_stdev requires finite kurtosis")
    if sr is not None and not _is_finite_value(sr):
        raise ValueError("estimated_sharpe_ratio_stdev requires finite sr")
    if _returns is not None and skew is None:
        skew_values = scipy_stats.skew(_returns)
        if isinstance(_returns, pd.DataFrame):
            skew = pd.Series(skew_values, index=_returns.columns)
        else:
            skew = skew_values
    if _returns is not None and kurtosis is None:
        kurtosis_values = scipy_stats.kurtosis(_returns, fisher=False)
        if isinstance(_returns, pd.DataFrame):
            kurtosis = pd.Series(kurtosis_values, index=_returns.columns)
        else:
            kurtosis = kurtosis_values
    if _returns is not None and sr is None:
        sr = estimated_sharpe_ratio(_returns)

    sr_std = np.sqrt((1 + (0.5 * sr**2) - (skew * sr) + (((kurtosis - 3) / 4) * sr**2)) / (n - 1))

    if isinstance(returns, pd.DataFrame):
        sr_std = pd.Series(sr_std, index=returns.columns)
    elif type(sr_std) not in (float, np.float64, pd.DataFrame):
        sr_std = sr_std.values[0]

    return sr_std


def probabilistic_sharpe_ratio(returns=None, sr_benchmark=0.0, *, sr=None, sr_std=None):
    """
    Calculate the Probabilistic Sharpe Ratio (PSR).

    Parameters
    ----------
    returns: `np.array`, pd.Series, pd.DataFrame
        If no `returns` are passed it is mandatory to pass a `sr` and `sr_std`.

    sr_benchmark: float
        Benchmark sharpe ratio expressed in the same frequency as the other parameters.
        By default, set to zero (comparing against no investment skill).

    sr: float, `np.array`, pd.Series, pd.DataFrame
        Sharpe ratio expressed in the same frequency as the other parameters.

    sr_std: float, `np.array`, pd.Series, pd.DataFrame
        Standard deviation fo the Estimated sharpe ratio,
        expressed in the same frequency as the other parameters.

    Returns
    -------
    float, pd.Series

    Notes
    -----
    PSR(SR*) = probability that SR^ > SR*
    SR^ = sharpe ratio estimated with `returns`, or `sr`
    SR* = `sr_benchmark`

    https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643
    """
    if returns is None and any(param is None for param in (sr, sr_std)):
        raise ValueError("probabilistic_sharpe_ratio requires sr and sr_std when returns is None")
    if sr is not None and not _is_finite_value(sr):
        raise ValueError("probabilistic_sharpe_ratio requires finite sr")
    if not _is_finite_value(sr_benchmark):
        raise ValueError("probabilistic_sharpe_ratio requires finite sr_benchmark")

    if sr is None:
        sr = estimated_sharpe_ratio(returns)
    if sr_std is None:
        sr_std = estimated_sharpe_ratio_stdev(returns, sr=sr)
    if np.any(~np.isfinite(np.asarray(sr_std))) or np.any(np.asarray(sr_std) <= 0):
        raise ValueError("probabilistic_sharpe_ratio requires finite sr_std > 0")

    psr = scipy_stats.norm.cdf((sr - sr_benchmark) / sr_std)

    if isinstance(returns, pd.DataFrame):
        psr = pd.Series(psr, index=returns.columns)
    elif type(psr) not in (float, np.float64):
        psr = psr.iloc[0] if isinstance(psr, pd.Series) else psr[0]

    return psr


def min_track_record_length(
    returns=None, sr_benchmark=0.0, prob=0.95, *, n=None, sr=None, sr_std=None
):
    """
    Calculate the MIn Track Record Length (minTRL).

    Parameters
    ----------
    returns: `np.array`, pd.Series, pd.DataFrame
        If no `returns` are passed it is mandatory to pass a `sr` and `sr_std`.

    sr_benchmark: float
        Benchmark sharpe ratio expressed in the same frequency as the other parameters.
        By default, set to zero (comparing against no investment skill).

    prob: float
        Confidence level used for calculating the minTRL.
        Between 0 and 1, by default=0.95

    n: int
        Number of returns samples used for calculating `sr` and `sr_std`.

    sr: float, `np.array`, pd.Series, pd.DataFrame
        Sharpe ratio expressed in the same frequency as the other parameters.

    sr_std: float, `np.array`, pd.Series, pd.DataFrame
        Standard deviation fo the Estimated sharpe ratio,
        expressed in the same frequency as the other parameters.

    Returns
    -------
    float, pd.Series

    Notes
    -----
    minTRL = minimum of returns/samples needed (with same SR and SR_STD) to accomplish a PSR(SR*) > `prob`
    PSR(SR*) = probability that SR^ > SR*
    SR^ = sharpe ratio estimated with `returns`, or `sr`
    SR* = `sr_benchmark`

    https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643
    """
    if returns is None and any(param is None for param in (n, sr, sr_std)):
        raise ValueError("min_track_record_length requires n, sr, and sr_std when returns is None")
    if not 0 < prob < 1:
        raise ValueError("min_track_record_length requires 0 < prob < 1")
    if not _is_finite_value(sr_benchmark):
        raise ValueError("min_track_record_length requires finite sr_benchmark")

    if n is None:
        n = len(returns)
    if not _is_integer_like(n):
        raise ValueError("min_track_record_length requires integer n")
    n = int(n)
    if n <= 1:
        raise ValueError("min_track_record_length requires n > 1")
    if sr is not None and not _is_finite_value(sr):
        raise ValueError("min_track_record_length requires finite sr")
    if sr is None:
        sr = estimated_sharpe_ratio(returns)
    if sr_std is None:
        sr_std = estimated_sharpe_ratio_stdev(returns, sr=sr)
    if np.any(~np.isfinite(np.asarray(sr_std))) or np.any(np.asarray(sr_std) <= 0):
        raise ValueError("min_track_record_length requires finite sr_std > 0")

    min_trl = 1 + (sr_std**2 * (n - 1)) * (scipy_stats.norm.ppf(prob) / (sr - sr_benchmark)) ** 2

    if isinstance(returns, pd.DataFrame):
        min_trl = pd.Series(min_trl, index=returns.columns)
    elif type(min_trl) not in (float, np.float64):
        min_trl = min_trl.iloc[0] if isinstance(min_trl, pd.Series) else min_trl[0]

    return min_trl


def num_independent_trials(trials_returns=None, *, m=None, p=None):
    """
    Calculate the number of independent trials.

    Parameters
    ----------
    trials_returns: pd.DataFrame
        All trials returns, not only the independent trials.

    m: int
        Number of total trials.

    p: float
        Average correlation between all the trials.

    Returns
    -------
    int
    """
    if trials_returns is None and any(param is None for param in (m, p)):
        raise ValueError(
            "num_independent_trials requires trials_returns when m or p is not provided"
        )
    if m is not None and not _is_integer_like(m):
        raise ValueError("num_independent_trials requires integer m")
    if m is not None:
        m = int(m)
    if m is not None and m <= 0:
        raise ValueError("num_independent_trials requires m > 0")

    if m is None:
        m = trials_returns.shape[1]

    if p is None:
        p = _average_upper_triangle_correlation(trials_returns)
    else:
        if isinstance(p, (bool, np.bool_)) or not np.isscalar(p):
            raise ValueError("num_independent_trials requires scalar p")
        try:
            p = float(p)
        except (TypeError, ValueError):
            raise ValueError("num_independent_trials requires scalar p") from None
        if not np.isfinite(p):
            p = 0.0
        elif not -1 <= p <= 1:
            raise ValueError("num_independent_trials requires -1 <= p <= 1")

    n = p + (1 - p) * m

    n = int(n) + 1  # round up

    return n


def expected_maximum_sr(
    trials_returns=None, expected_mean_sr=0.0, *, independent_trials=None, trials_sr_std=None
):
    """
    Compute the expected maximum Sharpe ratio (Analytically)

    Parameters
    ----------
    trials_returns: pd.DataFrame
        All trials returns, not only the independent trials.

    expected_mean_sr: float
        Expected mean SR, usually 0. We assume that random startegies will have a mean SR of 0,
        expressed in the same frequency as the other parameters.

    independent_trials: int
        Number of independent trials must be between 1 and `trials_returns.shape[1]`

    trials_sr_std: float
        Standard deviation for the Estimated sharpe ratios of all trials,
        expressed in the same frequency as the other parameters.

    Returns
    -------
    float
    """
    emc = 0.5772156649  # Euler-Mascheroni constant
    if not _is_finite_value(expected_mean_sr):
        raise ValueError("expected_maximum_sr requires finite expected_mean_sr")

    if independent_trials is None:
        if trials_returns is None:
            raise ValueError("expected_maximum_sr requires trials_returns or independent_trials")
        independent_trials = num_independent_trials(trials_returns)

    if not _is_integer_like(independent_trials):
        raise ValueError("expected_maximum_sr requires integer independent_trials")
    independent_trials = int(independent_trials)
    if independent_trials < 1:
        raise ValueError("expected_maximum_sr requires independent_trials >= 1")
    if trials_returns is not None and independent_trials > trials_returns.shape[1]:
        raise ValueError(
            "expected_maximum_sr requires independent_trials <= number of trial return columns"
        )

    if independent_trials <= 1:
        return expected_mean_sr

    if trials_sr_std is None:
        if trials_returns is None:
            raise ValueError(
                "expected_maximum_sr requires trials_returns or trials_sr_std when independent_trials > 1"
            )
        srs = estimated_sharpe_ratio(trials_returns)
        trials_sr_std = srs.std()
    if np.any(np.isfinite(np.asarray(trials_sr_std)) & (np.asarray(trials_sr_std) < 0)):
        raise ValueError("expected_maximum_sr requires trials_sr_std >= 0")

    if not np.isfinite(trials_sr_std):
        return expected_mean_sr

    max_z = (1 - emc) * scipy_stats.norm.ppf(
        1 - 1.0 / independent_trials
    ) + emc * scipy_stats.norm.ppf(1 - 1.0 / (independent_trials * np.e))
    expected_max_sr = expected_mean_sr + (trials_sr_std * max_z)

    return expected_max_sr


def deflated_sharpe_ratio(
    trials_returns=None,
    returns_selected=None,
    expected_mean_sr=0.0,
    independent_trials=10,
    expected_max_sr=None,
):
    """
    Calculate the Deflated Sharpe Ratio (PSR).

    Parameters
    ----------
    trials_returns: pd.DataFrame
        All trials returns, not only the independent trials.

    returns_selected: pd.Series

    expected_mean_sr: float
        Expected mean SR, usually 0. We assume that random startegies will have a mean SR of 0,
        expressed in the same frequency as the other parameters.

    expected_max_sr: float
        The expected maximum sharpe ratio expected after running all the trials,
        expressed in the same frequency as the other parameters.
    independent_trials: int

    Returns
    -------
    float

    Notes
    -----
    DFS = PSR(SR⁰) = probability that SR^ > SR⁰
    SR^ = sharpe ratio estimated with `returns`, or `sr`
    SR⁰ = `max_expected_sr`

    https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
    """
    if returns_selected is None:
        raise ValueError("deflated_sharpe_ratio requires returns_selected")
    if expected_max_sr is None and trials_returns is None:
        raise ValueError(
            "deflated_sharpe_ratio requires trials_returns when expected_max_sr is None"
        )
    if expected_max_sr is not None and not _is_finite_value(expected_max_sr):
        raise ValueError("deflated_sharpe_ratio requires finite expected_max_sr")

    if expected_max_sr is None:
        effective_independent_trials = independent_trials
        if trials_returns is not None:
            effective_independent_trials = min(
                effective_independent_trials, trials_returns.shape[1]
            )

        expected_max_sr = expected_maximum_sr(
            trials_returns=trials_returns,
            expected_mean_sr=expected_mean_sr,
            independent_trials=effective_independent_trials,
        )

    dsr = probabilistic_sharpe_ratio(returns=returns_selected, sr_benchmark=expected_max_sr)

    return dsr
