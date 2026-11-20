"""Regression tests for Iteration 71 Batch 1 (R71-117) and Batch 2c (R71-118..R71-121)."""

from __future__ import annotations

import datetime
import io
import logging
import math
import subprocess
import sys
from unittest import mock
from urllib import error as urllib_error

import pytest

import backtrader as bt
import backtrader.utils.py3 as py3
from backtrader.bokeh.analyzers.recorder import RecorderAnalyzer
from backtrader.notifications.adapters import TELEGRAM_SPEC, WECOM_APP_SPEC
from backtrader.notifications.channels import (
    CHANNEL_SPECS,
    DeclarativeDriver,
    Notification,
    compose_text,
    truncate,
)
from backtrader.notifications.security import mask_text, mask_url
from backtrader.notifications.transport import (
    HttpRequest,
    SmtpError,
    TransportError,
    UrllibTransport,
)
from backtrader.utils import log_message
from backtrader.utils.redaction import (
    SENSITIVE_KEYS,
    is_sensitive_key,
    masked_copy,
    redact_diagnostic,
)

# ---------------------------------------------------------------------------
# R71-117: backtrader.btrun import & yahoocsv_unreversed consistency
# ---------------------------------------------------------------------------


def test_r71_117_btrun_import_and_yahoocsv_unreversed_getdatas(tmp_path):
    """btrun imports cleanly and maps yahoocsv_unreversed to YahooFinanceCSVData(reverse=True)."""
    import importlib

    import backtrader.btrun as btrun_pkg
    from backtrader.feeds.yahoo import YahooFinanceCSVData

    btrun_mod = importlib.import_module("backtrader.btrun.btrun")

    assert callable(btrun_pkg.btrun)
    assert btrun_mod.DATAFORMATS["yahoocsv_unreversed"] is YahooFinanceCSVData

    csv_file = tmp_path / "sample_yahoo.csv"
    csv_file.write_text(
        "Date,Open,High,Low,Close,Adj Close,Volume\n"
        "2024-01-02,10,11,9,10.5,10.5,1000\n"
        "2024-01-01,9,10,8,9.5,9.5,900\n",
        encoding="utf-8",
    )

    args_unrev = btrun_mod.parse_args(
        ["--data", str(csv_file), "--format", "yahoocsv_unreversed"]
    )
    datas_unrev = btrun_mod.getdatas(args_unrev)
    assert len(datas_unrev) == 1
    assert isinstance(datas_unrev[0], YahooFinanceCSVData)
    assert datas_unrev[0].p.reverse is True

    args_rev = btrun_mod.parse_args(["--data", str(csv_file), "--format", "yahoocsv"])
    datas_rev = btrun_mod.getdatas(args_rev)
    assert len(datas_rev) == 1
    assert isinstance(datas_rev[0], YahooFinanceCSVData)
    assert datas_rev[0].p.reverse is False


def test_r71_117_btrun_cli_help_smoke():
    """CLI --help smoke succeeds and advertises yahoocsv_unreversed."""
    proc = subprocess.run(
        [sys.executable, "-m", "backtrader.btrun.btrun", "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "yahoocsv_unreversed" in proc.stdout
    assert "yahoo_unreversed" not in proc.stdout


# ---------------------------------------------------------------------------
# R71-118: RecorderAnalyzer IndType & per-instance indicator/observer keys
# ---------------------------------------------------------------------------


def _write_btcsv(tmp_path, closes):
    path = tmp_path / "prices.csv"
    lines = ["Date,Open,High,Low,Close,Volume,OpenInterest"]
    start = datetime.date(2024, 1, 1)
    for idx, close in enumerate(closes):
        day = start + datetime.timedelta(days=idx)
        lines.append(f"{day.isoformat()},{close},{close},{close},{close},100,0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_r71_118_recorder_records_distinct_same_class_indicators_and_unnamed_data(tmp_path):
    """Default indicators=True records real indicator values without overwriting same-class instances."""
    closes = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    csv_path = _write_btcsv(tmp_path, closes)

    class DualSMAStrategy(bt.Strategy):
        def __init__(self):
            self.sma_fast = bt.indicators.SimpleMovingAverage(self.data.close, period=3)
            self.sma_slow = bt.indicators.SimpleMovingAverage(self.data.close, period=5)

    cerebro = bt.Cerebro()
    data = bt.feeds.BacktraderCSVData(dataname=str(csv_path))
    cerebro.adddata(data, name="")
    cerebro.addstrategy(DualSMAStrategy)
    cerebro.addanalyzer(RecorderAnalyzer, _name="recorder")

    results = cerebro.run()
    strat = results[0]
    analysis = strat.analyzers.recorder.get_analysis()

    # Unnamed data feed (_name == "") is still recorded under data0 (prenext + next cover all 8 bars)
    assert "data0" in analysis["data"]
    assert len(analysis["data"]["data0"]["close"]) == len(closes)

    indicators = analysis["indicators"]
    fast_key = f"{strat.sma_fast.__class__.__name__}#{id(strat.sma_fast)}"
    slow_key = f"{strat.sma_slow.__class__.__name__}#{id(strat.sma_slow)}"
    assert fast_key != slow_key
    assert fast_key in indicators
    assert slow_key in indicators

    fast_vals = indicators[fast_key]["sma"]
    slow_vals = indicators[slow_key]["sma"]
    assert len(fast_vals) == len(closes)
    assert len(slow_vals) == len(closes)

    # On closes[4..7] = 50, 60, 70, 80:
    # SMA(3) = 40, 50, 60, 70; SMA(5) = 30, 40, 50, 60
    for got, exp in zip(fast_vals[-4:], [40.0, 50.0, 60.0, 70.0]):
        assert math.isclose(got, exp, rel_tol=1e-9)
    for got, exp in zip(slow_vals[-4:], [30.0, 40.0, 50.0, 60.0]):
        assert math.isclose(got, exp, rel_tol=1e-9)


def test_r71_118_recorder_records_observers_via_obstype(tmp_path):
    """observers=True records observer lines under distinct per-instance keys."""
    csv_path = _write_btcsv(tmp_path, [10.0, 11.0, 12.0, 13.0, 14.0])

    class EmptyStrategy(bt.Strategy):
        pass

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(csv_path)), name="TEST")
    cerebro.addstrategy(EmptyStrategy)
    cerebro.addanalyzer(RecorderAnalyzer, indicators=False, observers=True, _name="recorder")

    strat = cerebro.run()[0]
    analysis = strat.analyzers.recorder.get_analysis()

    assert "indicators" not in analysis
    observers = analysis["observers"]
    assert len(observers) >= 1
    for obs_lines in observers.values():
        assert any(len(series) == 5 for series in obs_lines.values())


# ---------------------------------------------------------------------------
# R71-119: Convergent, exact truncate() for byte-limited and char-limited channels
# ---------------------------------------------------------------------------


def _assert_truncation_invariants(text, limit, byte_limited):
    out, truncated = truncate(text, limit, byte_limited=byte_limited)
    if limit is None:
        assert out == text and truncated is False
        return out
    size = len(out.encode("utf-8")) if byte_limited else len(out)
    orig_size = len(text.encode("utf-8")) if byte_limited else len(text)
    if orig_size <= limit:
        assert out == text and truncated is False
        return out
    assert truncated is True
    assert size <= max(limit, 0), f"size {size} > limit {limit} for byte_limited={byte_limited}"
    out.encode("utf-8").decode("utf-8")
    if "\n…（已截断 " in out:
        head, tail = out.rsplit("\n…（已截断 ", 1)
        reported = int(tail.split(" ", 1)[0])
        assert text.startswith(head)
        assert reported == len(text) - len(head), (
            f"reported={reported} != actual={len(text) - len(head)} "
            f"(limit={limit}, byte_limited={byte_limited})"
        )
    else:
        assert text.startswith(out)
    return out


@pytest.mark.parametrize("byte_limited", [False, True])
@pytest.mark.parametrize(
    "text",
    [
        "a" * 69,
        "a" * 150,
        "a" * 1500,
        "中" * 30,
        "中" * 1200,
        "🚀" * 20,
        "🚀" * 600,
        "混合ABC中文字🚀🔥!" * 150,
    ],
)
@pytest.mark.parametrize("limit", [-5, 0, 1, 2, 3, 4, 10, 13, 14, 20, 28, 29, 30, 31, 32, 60, 120])
def test_r71_119_truncate_invariants_across_limits_and_encodings(text, limit, byte_limited):
    """truncate() never exceeds limit and always reports exact dropped character count."""
    _assert_truncation_invariants(text, limit, byte_limited)


def test_r71_119_truncate_digit_crossing_boundaries():
    """Crossing 9->10, 99->100, and 999->1000 dropped chars converges without exceeding limit."""
    # Byte-limited 9 -> 10 crossing: initial removed=9 (28B marker), after cutting removed=38 (29B)
    out = _assert_truncation_invariants("a" * 69, 60, byte_limited=True)
    assert len(out.encode("utf-8")) == 60
    assert "已截断 38 字符" in out

    # Byte-limited emoji 9 -> 10 crossing at WeCom 2048 bytes
    out_emoji = _assert_truncation_invariants("🚀" * 515, 2048, byte_limited=True)
    assert len(out_emoji.encode("utf-8")) <= 2048
    assert "已截断 11 字符" in out_emoji

    # Byte-limited 99 -> 100 crossing
    out_100 = _assert_truncation_invariants("a" * 159, 60, byte_limited=True)
    assert len(out_100.encode("utf-8")) == 60
    assert "已截断 129 字符" in out_100

    # Char-limited 9 -> 10 crossing
    out_char_10 = _assert_truncation_invariants("x" * 29, 20, byte_limited=False)
    assert len(out_char_10) == 20
    assert "已截断 22 字符" in out_char_10

    # Char-limited 99 -> 100 crossing
    out_char_100 = _assert_truncation_invariants("x" * 119, 20, byte_limited=False)
    assert len(out_char_100) == 20
    assert "已截断 113 字符" in out_char_100

    # Char-limited 999 -> 1000 crossing
    out_char_1000 = _assert_truncation_invariants("x" * 1019, 20, byte_limited=False)
    assert len(out_char_1000) == 20
    assert "已截断 1014 字符" in out_char_1000


def test_r71_119_channel_specs_respect_limits_for_cjk_emoji_and_ascii():
    """All length-limited channels strictly obey their byte/char caps via compose_text."""
    payload = "中🚀A" * 2500
    note = Notification(text=payload, title="Alert", level="warning")

    for spec in (CHANNEL_SPECS["wecom_bot"], WECOM_APP_SPEC):
        text, truncated = compose_text(note, spec)
        assert truncated is True
        assert len(text.encode("utf-8")) <= 2048
        text.encode("utf-8").decode("utf-8")

    discord_text, discord_trunc = compose_text(note, CHANNEL_SPECS["discord"])
    assert discord_trunc is True
    assert len(discord_text) <= 2000

    slack_text, slack_trunc = compose_text(note, CHANNEL_SPECS["slack"])
    assert slack_trunc is True
    assert len(slack_text) <= 4000

    tg_text, tg_trunc = compose_text(note, TELEGRAM_SPEC)
    assert tg_trunc is True
    assert len(tg_text) <= 4096

    dt_text, dt_trunc = compose_text(note, CHANNEL_SPECS["dingtalk"])
    assert dt_trunc is False
    assert payload in dt_text


# ---------------------------------------------------------------------------
# R71-120: Path-embedded webhook secrets & transport error masking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,secret",
    [
        ("https://api.telegram.org/bot123456:TG_SECRET_XYZ/sendMessage", "TG_SECRET_XYZ"),
        ("https://api.telegram.org/file/bot123456:TG_FILE_SECRET/photo.jpg?a=1#h", "TG_FILE_SECRET"),
        ("https://tg-proxy.internal:8443/bot987654:SELF_TG_SEC/sendMessage?parse_mode=MarkdownV2#f", "SELF_TG_SEC"),
        ("https://proxy.example.com/tg/bot987654%3AENC_TG_SEC/sendMessage", "ENC_TG_SEC"),
        ("https://hooks.slack.com/services/T/B/SLACK_SHORT_SEC", "SLACK_SHORT_SEC"),
        ("https://hooks.slack.com/services/T00000000/B00000000/SLACK_MAIN_SEC?foo=1#frag", "SLACK_MAIN_SEC"),
        ("https://hooks.slack-gov.com/services/T111/B222/SLACK_GOV_SEC", "SLACK_GOV_SEC"),
        ("https://slack-proxy.corp/services/T12345/B67890/SLACK_CUSTOM_SEC?x=1#top", "SLACK_CUSTOM_SEC"),
        ("https://proxy.corp/slack/services/E123/C456/SLACK_ENT_SEC", "SLACK_ENT_SEC"),
        ("https://discord.com/api/webhooks/1234567890/DISCORD_MAIN_SEC?wait=true#frag", "DISCORD_MAIN_SEC"),
        ("https://canary.discord.com/api/webhooks/123456/DISCORD_CANARY_SEC/slack", "DISCORD_CANARY_SEC"),
        ("https://ptb.discordapp.com/api/webhooks/123456/DISCORD_PTB_SEC", "DISCORD_PTB_SEC"),
        ("https://discord-proxy.internal/api/webhooks/123456789/DISCORD_SELF_SEC?wait=true#f", "DISCORD_SELF_SEC"),
        ("https://proxy.internal/discord/api/v10/webhooks/987654/DISCORD_V10_SEC", "DISCORD_V10_SEC"),
        ("https://open.feishu.cn/open-apis/bot/v2/hook/FEISHU_HOOK_SEC", "FEISHU_HOOK_SEC"),
    ],
)
def test_r71_120_mask_url_and_mask_text_hide_path_webhook_secrets(url, secret):
    """Telegram/Slack/Discord/Feishu path secrets are masked in both mask_url and mask_text."""
    masked_u = mask_url(url)
    assert secret not in masked_u
    assert "***" in masked_u

    # Preserve query / fragment markers when present
    if "?wait=true#frag" in url:
        assert masked_u.endswith("?wait=true#frag")
    if "?foo=1#frag" in url:
        assert masked_u.endswith("?foo=1#frag")

    wrapped = f"failed POST ('{url}') status=500"
    masked_t = mask_text(wrapped)
    assert secret not in masked_t
    assert "('https://" in masked_t
    assert "') status=500" in masked_t


@pytest.mark.parametrize(
    "safe_url",
    [
        "https://example.com/services/health",
        "https://example.com/services/billing/data/report",
        "https://example.com/botany",
        "https://example.com/bot/health",
        "https://example.com/api/webhooks/docs",
        "https://example.com/api/webhooks/docs/getting-started",
    ],
)
def test_r71_120_ordinary_non_sensitive_urls_not_falsely_masked(safe_url):
    """Ordinary URLs like /services/health, /botany, /api/webhooks/docs stay intact."""
    assert mask_url(safe_url) == safe_url
    assert mask_text(f"GET {safe_url}") == f"GET {safe_url}"


def test_r71_120_mask_text_masks_embedded_url_query_secrets():
    """mask_text also masks secret query parameters inside embedded URLs."""
    text = (
        "POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=WECOM_KEY_99 "
        "and https://oapi.dingtalk.com/robot/send?access_token=DT_TOK&sign=DT_SIG&timestamp=123"
    )
    masked = mask_text(text)
    for secret in ("WECOM_KEY_99", "DT_TOK", "DT_SIG"):
        assert secret not in masked
    assert "timestamp=123" in masked


def test_r71_120_transport_and_driver_never_leak_webhook_secrets():
    """UrllibTransport, TransportError, SmtpError and DeclarativeDriver mask all error paths."""
    tg_url = "https://api.telegram.org/bot123456:TG_LEAK_SECRET/sendMessage?chat_id=1"
    slack_url = "https://hooks.slack.com/services/T123/B456/SLACK_LEAK_SECRET?a=1#h"
    discord_url = "https://discord-proxy.internal/api/webhooks/123456/DISCORD_LEAK_SECRET"

    # 1. Direct TransportError / SmtpError construction masks defensively
    direct_err = TransportError("network", url=tg_url, reason=f"redirect to {slack_url}")
    assert "TG_LEAK_SECRET" not in direct_err.url
    assert "TG_LEAK_SECRET" not in str(direct_err)
    assert "SLACK_LEAK_SECRET" not in (direct_err.reason or "")
    assert "SLACK_LEAK_SECRET" not in str(direct_err)

    smtp_err = SmtpError("auth", detail=f"failed with {discord_url} bot_token=BT_SEC")
    assert "DISCORD_LEAK_SECRET" not in str(smtp_err)
    assert "BT_SEC" not in str(smtp_err)

    # 2. UrllibTransport URLError where exc.reason itself embeds secret URLs
    exc = urllib_error.URLError(OSError(f"cannot reach {tg_url} or {discord_url}"))
    with mock.patch.object(py3, "urlopen", side_effect=exc), pytest.raises(TransportError) as info:
        UrllibTransport().send(HttpRequest(method="POST", url=slack_url))
    err_str = str(info.value)
    for secret in ("TG_LEAK_SECRET", "SLACK_LEAK_SECRET", "DISCORD_LEAK_SECRET"):
        assert secret not in err_str
        assert secret not in info.value.url
        assert secret not in (info.value.reason or "")

    # 3. DeclarativeDriver -> Attempt masks TransportError on Discord/Slack
    class FailingTransport:
        def send(self, request):
            raise TransportError("network", request.url, f"refused {request.url}")

    driver = DeclarativeDriver(
        CHANNEL_SPECS["discord"],
        {"webhook_url": discord_url},
        transport=FailingTransport(),
    )
    attempt = driver.deliver(Notification(text="hello"))
    assert attempt.ok is False
    assert "DISCORD_LEAK_SECRET" not in (attempt.error or "")


# ---------------------------------------------------------------------------
# R71-121: redaction.py & log_message.py extended credential key coverage
# ---------------------------------------------------------------------------


R71_121_KEYS = [
    "bot_token",
    "context_token",
    "appsecret",
    "corpsecret",
    "app_secret",
    "corp_secret",
    "app-secret",
    "corp-secret",
    "bot-token",
    "context-token",
]


@pytest.mark.parametrize("key", R71_121_KEYS)
def test_r71_121_redaction_module_covers_all_keys_and_formats(key):
    """SENSITIVE_KEYS, is_sensitive_key, masked_copy, and redact_diagnostic mask all 10 forms."""
    secret = "VAL_S3CR3T_9988"
    secret_with_space = "VAL S3CR3T SPACE"

    assert is_sensitive_key(key)
    assert key.replace("-", "_") in SENSITIVE_KEYS

    # Mapping / dict redaction
    assert redact_diagnostic({key: secret, "safe": "ok"}) == {key: "***", "safe": "ok"}
    assert masked_copy({key: secret, "safe": "ok"}) == {key: "***", "safe": "ok"}

    # Plain key=value, quoted with spaces, JSON, and query string
    samples = [
        f"{key}={secret}",
        f"{key}='{secret_with_space}'",
        f'{key}="{secret_with_space}"',
        f'{{"{key}": "{secret}", "safe": "ok"}}',
        f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=ww1&{key}={secret}&keep=ok",
    ]
    for sample in samples:
        for fn in (redact_diagnostic, masked_copy):
            redacted = fn(sample)
            assert secret not in redacted, f"leaked in {sample!r} -> {redacted!r}"
            assert secret_with_space not in redacted, f"leaked in {sample!r} -> {redacted!r}"
            assert "***" in redacted
            if "&keep=ok" in sample:
                assert "&keep=ok" in redacted


@pytest.mark.parametrize("key", R71_121_KEYS)
def test_r71_121_log_message_redacting_formatter_covers_all_keys_and_formats(key):
    """_RedactingFormatter redacts all 10 key variants in plain, quoted, JSON, and query forms."""
    secret = "LOG_S3CR3T_7766"
    secret_with_space = "LOG S3CR3T SPACE"
    formatter = log_message._RedactingFormatter("%(message)s")

    samples = [
        f"{key}={secret}",
        f"{key}='{secret_with_space}'",
        f'{key}="{secret_with_space}"',
        f'{{"{key}": "{secret}", "safe": "ok"}}',
        f"GET https://example.com/api?corpid=ww1&{key}={secret}&keep=ok",
    ]
    for sample in samples:
        record = logging.LogRecord(
            name="backtrader.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg=sample,
            args=(),
            exc_info=None,
        )
        rendered = formatter.format(record)
        assert secret not in rendered, f"leaked in {sample!r} -> {rendered!r}"
        assert secret_with_space not in rendered, f"leaked in {sample!r} -> {rendered!r}"
        assert "[REDACTED]" in rendered
        if "&keep=ok" in sample:
            assert "&keep=ok" in rendered


def test_r71_121_configure_logging_stream_redacts_end_to_end():
    """End-to-end logging through configure_logging redacts appsecret/corpsecret/bot_token/context_token."""
    buf = io.StringIO()
    try:
        bt.configure_logging(level="INFO", console=False)
        root = bt.get_logger()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(log_message._RedactingFormatter("%(message)s"))
        root.addHandler(handler)
        try:
            logger = bt.get_logger("iter71_redaction")
            logger.error(
                'appsecret=AS1 corpsecret=CS2 bot_token="BT 3" context-token=CT4 '
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=ww&corp_secret=CS5&ok=1"
            )
            output = buf.getvalue()
            for leaked in ("AS1", "CS2", "BT 3", "CT4", "CS5"):
                assert leaked not in output
            assert "&ok=1" in output
            assert "[REDACTED]" in output
        finally:
            root.removeHandler(handler)
    finally:
        log_message.reset_logging()
