# -*- coding: utf-8 -*-
"""投资组合监控框架单元测试(规则评估 + 技术指标计算)。"""

import numpy as np
import pandas as pd
import pytest

from src.monitoring.evaluator import compute_technical_indicators, evaluate_monitoring
from src.monitoring.rules import MONITORING_RULES, TIERS
from data_provider.yfinance_fundamental_adapter import _to_yf_symbol


# --------------------------- yfinance 代码转换 ---------------------------
def test_hk_symbol_normalization_to_4_digits():
    # 港股各种写法都应归一化为 yfinance 的 4 位 .HK 格式
    assert _to_yf_symbol("00700.HK") == "0700.HK"   # 规范化 5 位 .HK(关键回归)
    assert _to_yf_symbol("0700.HK") == "0700.HK"
    assert _to_yf_symbol("HK00700") == "0700.HK"
    assert _to_yf_symbol("00700") == "0700.HK"
    assert _to_yf_symbol("09988.HK") == "9988.HK"
    # 美股原样
    assert _to_yf_symbol("AAPL") == "AAPL"
    assert _to_yf_symbol("BRK.B") == "BRK.B"


def _make_df(closes, volumes=None, opens=None, highs=None, pcts=None):
    n = len(closes)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": opens if opens is not None else closes,
        "high": highs if highs is not None else closes,
        "low": closes,
        "close": closes,
        "volume": volumes if volumes is not None else [100] * n,
        "pct_chg": pcts if pcts is not None else [0.0] * n,
    })


# --------------------------- 技术指标计算 ---------------------------
def test_rsi_overbought_on_monotonic_rise():
    df = _make_df(list(np.linspace(10, 50, 40)))
    tech = compute_technical_indicators(df)
    assert tech["rsi14"] is not None
    assert tech["rsi14"] > 70  # 单边上涨 -> 超买


def test_volume_ratio_and_long_ma_with_enough_history():
    closes = list(np.linspace(10, 30, 210))
    volumes = [100] * 209 + [400]
    df = _make_df(closes, volumes=volumes)
    tech = compute_technical_indicators(df)
    assert tech["n_bars"] == 210
    assert tech["ma"]["sma200"] is not None  # 足够历史 -> 200 周期均线可算
    assert round(tech["vol_ratio_20"], 2) == 4.0  # 末根 400 / 前 20 日均 100


def test_insufficient_history_marks_unavailable():
    df = _make_df([10, 11, 12, 13, 14])  # 仅 5 根
    res = evaluate_monitoring(df, fundamentals={}, tier="low")
    tech_inds = {i["key"]: i for c in res["categories"] for i in c["indicators"]}
    assert tech_inds["rsi"]["status"] == "unavailable"
    assert tech_inds["ma_cross"]["status"] == "unavailable"
    assert tech_inds["volume_spike"]["status"] == "unavailable"


def test_volume_spike_high_tier_any_context():
    closes = list(np.linspace(10, 30, 25))
    volumes = [100] * 24 + [400]  # 4.0x
    df = _make_df(closes, volumes=volumes)
    res = evaluate_monitoring(df, fundamentals={}, tier="high")
    vol = next(i for c in res["categories"] for i in c["indicators"] if i["key"] == "volume_spike")
    assert vol["alert"] is True  # high 档 >3.5x 任意上下文


# --------------------------- 基本面 / 股息规则 ---------------------------
@pytest.fixture
def fund():
    return {
        "forward_pe": 30.0, "trailing_pe": 35.0, "peg": 2.5, "pb": 6.0,
        "earnings_growth_pct": 10.0, "dividend_yield_pct": 1.0,
        "payout_ratio_pct": 80.0, "capex_pct_revenue": 25.0,
        "capex_yoy_change_pct": 40.0,            # >30 -> 中档同比告警
        "pe_hist_mean": 20.0, "pe_hist_std": 5.0, "pe_hist_n": 4,  # 历史 P/E 区间
    }


def _inds(res):
    return {i["key"]: i for c in res["categories"] for i in c["indicators"]}


def test_low_tier_fundamentals(fund):
    inds = _inds(evaluate_monitoring(None, fund, tier="low"))
    assert inds["forward_pe"]["alert"] is True             # 30 > 5年均值20 + 1SD5 = 25
    assert inds["pb"]["alert"] is True                     # 6 > 2.5
    assert inds["forecast_growth"]["alert"] is False       # 10 不 < 5
    assert inds["capex_pct"]["alert"] is True              # 25 > 20
    assert inds["dividend_yield"]["alert"] is True         # 1.0 < 3.5
    assert inds["payout_ratio"]["alert"] is True           # 80 > 75


def test_medium_tier_fundamentals(fund):
    inds = _inds(evaluate_monitoring(None, fund, tier="medium"))
    assert inds["forward_pe"]["alert"] is True             # 30 > 5年均值20
    assert inds["pb"]["alert"] is True                     # 6 > 5
    assert inds["forecast_growth"]["alert"] is True        # 10 < 15
    assert inds["capex_pct"]["alert"] is True              # 同比40 > 30
    assert inds["dividend_yield"]["alert"] is True         # 1.0 < 1.5
    assert inds["payout_ratio"]["alert"] is True           # 80 > 50


def test_forward_pe_below_history_no_alert():
    # 前瞻 P/E 低于历史均值时不应告警(对应腾讯:前瞻远低于 5 年均值)
    fund = {"forward_pe": 12.0, "pe_hist_mean": 21.0, "pe_hist_std": 2.4, "pe_hist_n": 4}
    inds = _inds(evaluate_monitoring(None, fund, tier="medium"))
    assert inds["forward_pe"]["status"] == "ok"
    assert inds["forward_pe"]["alert"] is False


def test_forward_pe_unavailable_without_history():
    fund = {"forward_pe": 30.0}  # 无历史 P/E 数据
    inds = _inds(evaluate_monitoring(None, fund, tier="medium"))
    assert inds["forward_pe"]["status"] == "unavailable"


def test_high_tier_fundamentals(fund):
    inds = _inds(evaluate_monitoring(None, fund, tier="high"))
    assert inds["forward_pe"]["alert"] is True             # PEG 2.5 > 2.0
    assert inds["pb"]["alert"] is False                    # 6 不 > 10
    assert inds["forecast_growth"]["alert"] is True        # 10 < 25
    assert inds["capex_pct"]["alert"] is False             # 25 不 < 5
    assert inds["dividend_yield"]["status"] == "ignored"   # high 档忽略股息
    assert inds["payout_ratio"]["alert"] is False          # 80 不 > 90


def test_invalid_tier_falls_back_to_medium(fund):
    res = evaluate_monitoring(None, fund, tier="nonsense")
    assert res["tier"] == "medium"


def test_summary_and_deferred(fund):
    res = evaluate_monitoring(None, fund, tier="low")
    assert res["summary"]["alerts"] == len(res["alerts"])
    assert res["deferred"] and res["deferred"][0]["key"] == "derivative"


def test_rules_cover_all_tiers():
    for key, spec in MONITORING_RULES.items():
        for tier in TIERS:
            assert tier in spec["tiers"], f"{key} 缺少 {tier} 档规则"
            assert spec["tiers"][tier]["text"]
