# -*- coding: utf-8 -*-
"""
监控规则评估器。

职责:
  1. compute_technical_indicators(df):从日线 OHLCV 计算监控所需的技术指标
     (RSI14、SMA/EMA 金叉死叉、20 日量比、下跌日 / 突破上下文)。
  2. evaluate_monitoring(df, fundamentals, tier):按选定风险档位,对三大类指标
     逐项套用规则,输出结构化的告警结果。

设计:fail-open。任何指标数据不足时标记 status="unavailable" 并附原因,绝不抛错。
单位约定与 yfinance_fundamental_adapter 对齐(股息率 / 增长 / 派息均为百分数)。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from .rules import (
    MONITORING_RULES,
    CATEGORY_ORDER,
    CATEGORY_LABELS,
    TIER_LABELS,
    DEFAULT_TIER,
    DEFERRED_CATEGORIES,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _get_series(df: pd.DataFrame, candidates: List[str]) -> Optional[pd.Series]:
    """按候选列名(忽略大小写)取出数值序列。"""
    lower = {str(c).lower(): c for c in df.columns}
    for name in candidates:
        col = lower.get(name.lower())
        if col is not None:
            return pd.to_numeric(df[col], errors="coerce")
    return None


def _fmt(value: Optional[float], suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}{suffix}"


def _cross(fast_prev: float, fast_cur: float, slow_prev: float, slow_cur: float, direction: str) -> bool:
    """判断 fast 线相对 slow 线在最新一根 K 是否发生交叉。"""
    down = fast_prev >= slow_prev and fast_cur < slow_cur
    up = fast_prev <= slow_prev and fast_cur > slow_cur
    if direction == "down":
        return down
    if direction == "up":
        return up
    return down or up


# ---------------------------------------------------------------------------
# 技术指标计算
# ---------------------------------------------------------------------------
def compute_technical_indicators(df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """
    从日线数据计算监控所需技术指标。返回字段在数据不足时为 None。

    返回:
        rsi14, n_bars,
        sma50/sma200/ema5/ema10/ema30 (latest + prev),
        vol_ratio_20, is_down_day, is_breakout
    """
    out: Dict[str, Any] = {
        "n_bars": 0,
        "rsi14": None,
        "ma": {},          # name -> {"cur":..., "prev":...}
        "vol_ratio_20": None,
        "is_down_day": None,
        "is_breakout": None,
        "close": None,
    }
    if df is None or len(df) == 0:
        return out

    df = df.copy()
    # 按日期升序,使最新一根在末尾
    date_col = next((c for c in df.columns if str(c).lower() in ("date", "日期", "trade_date")), None)
    if date_col is not None:
        try:
            df = df.sort_values(by=date_col).reset_index(drop=True)
        except Exception:
            pass

    close = _get_series(df, ["close", "收盘", "收盘价"])
    open_ = _get_series(df, ["open", "开盘", "开盘价"])
    high = _get_series(df, ["high", "最高", "最高价"])
    volume = _get_series(df, ["volume", "成交量", "vol"])
    pct = _get_series(df, ["pct_chg", "涨跌幅", "change_pct"])

    if close is not None:
        close = close.dropna()
    if close is None or len(close) == 0:
        return out

    out["n_bars"] = int(len(close))
    out["close"] = float(close.iloc[-1])

    # RSI(14) —— 标准 Wilder 近似(简单滚动均值版本)
    if len(close) >= 15:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        last_gain = gain.iloc[-1]
        last_loss = loss.iloc[-1]
        if last_loss is not None and not pd.isna(last_loss):
            if last_loss == 0:
                out["rsi14"] = 100.0
            elif not pd.isna(last_gain):
                rs = last_gain / last_loss
                out["rsi14"] = float(100.0 - 100.0 / (1.0 + rs))

    # 均线(SMA / EMA)最新值与前一根,用于交叉检测
    def _ma(kind: str, window: int):
        if len(close) < window + 1:
            return None
        series = close.ewm(span=window, adjust=False).mean() if kind == "ema" else close.rolling(window).mean()
        cur, prev = series.iloc[-1], series.iloc[-2]
        if pd.isna(cur) or pd.isna(prev):
            return None
        return {"cur": float(cur), "prev": float(prev)}

    out["ma"] = {
        "sma50": _ma("sma", 50),
        "sma200": _ma("sma", 200),
        "ema5": _ma("ema", 5),
        "ema10": _ma("ema", 10),
        "ema30": _ma("ema", 30),
    }

    # 成交量:今日 vs 过去 20 日均量(不含今日)
    if volume is not None and len(volume.dropna()) >= 21:
        vol = volume.dropna()
        avg20 = vol.iloc[-21:-1].mean()
        today_vol = vol.iloc[-1]
        if avg20 and avg20 > 0:
            out["vol_ratio_20"] = float(today_vol / avg20)

    # 下跌日 / 突破 上下文
    if pct is not None and not pd.isna(pct.iloc[-1]):
        out["is_down_day"] = bool(pct.iloc[-1] < 0)
    elif open_ is not None and not pd.isna(open_.iloc[-1]):
        out["is_down_day"] = bool(close.iloc[-1] < open_.iloc[-1])

    if high is not None and len(high.dropna()) >= 21:
        prior_high = high.dropna().iloc[-21:-1].max()
        out["is_breakout"] = bool(close.iloc[-1] > prior_high)

    return out


# ---------------------------------------------------------------------------
# 单指标评估
# ---------------------------------------------------------------------------
def _result(key: str, display: str, value_str: str, rule: str,
            status: str, alert: bool, note: str = "") -> Dict[str, Any]:
    return {
        "key": key,
        "display": display,
        "value_str": value_str,
        "rule": rule,
        "status": status,        # alert | ok | unavailable | ignored
        "alert": alert,
        "note": note,
    }


def _unavailable(key, display, rule, note) -> Dict[str, Any]:
    return _result(key, display, "—", rule, "unavailable", False, note)


def _eval_rsi(tech, p, rule, key, display):
    rsi = tech.get("rsi14")
    if rsi is None:
        return _unavailable(key, display, rule, "历史不足 15 根 K 线,无法计算 RSI(14)")
    oversold, overbought = p.get("oversold"), p.get("overbought")
    alert = (oversold is not None and rsi < oversold) or (overbought is not None and rsi > overbought)
    return _result(key, display, _fmt(rsi), rule, "alert" if alert else "ok", alert)


def _eval_ma_cross(tech, p, rule, key, display):
    fast_name = {5: "ema5", 10: "ema10", 30: "ema30", 50: "sma50", 200: "sma200"}
    fk = ("ema" if p["kind"] == "ema" else "sma") + str(p["fast"])
    sk = ("ema" if p["kind"] == "ema" else "sma") + str(p["slow"])
    fast, slow = tech["ma"].get(fk), tech["ma"].get(sk)
    if not fast or not slow:
        need = p["slow"] + 1
        return _unavailable(key, display, rule, f"历史不足 {need} 根 K 线,无法计算 {p['slow']} 周期均线")
    triggered = _cross(fast["prev"], fast["cur"], slow["prev"], slow["cur"], p["direction"])
    rel = "上方" if fast["cur"] >= slow["cur"] else "下方"
    vstr = f"{p['fast']}{p['kind'].upper()}={fast['cur']:.2f} 位于 {p['slow']}{p['kind'].upper()}={slow['cur']:.2f} {rel}"
    return _result(key, display, vstr, rule, "alert" if triggered else "ok", triggered,
                   note="" if triggered else "最新一根未发生该交叉")


def _eval_volume(tech, p, rule, key, display):
    ratio = tech.get("vol_ratio_20")
    if ratio is None:
        return _unavailable(key, display, rule, "历史不足 21 根 K 线,无法计算 20 日均量")
    mult = p["mult"]
    ctx = p["context"]
    over = ratio > mult
    if ctx == "down_day":
        ctx_ok = bool(tech.get("is_down_day"))
        ctx_label = "下跌日" if ctx_ok else "非下跌日"
    elif ctx == "breakout":
        ctx_ok = bool(tech.get("is_breakout"))
        ctx_label = "突破" if ctx_ok else "未突破"
    else:
        ctx_ok = True
        ctx_label = ""
    alert = over and ctx_ok
    vstr = f"{ratio:.2f}x 均量" + (f"({ctx_label})" if ctx_label else "")
    return _result(key, display, vstr, rule, "alert" if alert else "ok", alert)


def _eval_forward_pe(fund, p, rule, key, display):
    basis = p.get("basis")
    fpe = fund.get("forward_pe")
    if basis == "peg":
        peg = fund.get("peg")
        if peg is None:
            return _unavailable(key, display, rule, "缺少 PEG 数据")
        alert = peg > p["peg_max"]
        return _result(key, display, f"PEG={peg:.2f}(前瞻 P/E={_fmt(fpe)})", rule,
                       "alert" if alert else "ok", alert)

    # 基于 5 年历史 P/E 区间(均值 / 均值+1SD)评估
    mean = fund.get("pe_hist_mean")
    std = fund.get("pe_hist_std") or 0.0
    n = fund.get("pe_hist_n") or 0
    if fpe is None or mean is None or n < 2:
        return _unavailable(key, display, rule, "历史 P/E 数据不足(需年度 EPS 与价格历史)")
    if basis == "hist_band_1sd":
        threshold = mean + std
        vstr = f"前瞻 P/E={fpe:.2f}(5年均值 {mean:.1f} ±{std:.1f})"
    else:  # hist_band_mean
        threshold = mean
        vstr = f"前瞻 P/E={fpe:.2f}(5年均值 {mean:.1f})"
    alert = fpe > threshold
    return _result(key, display, vstr, rule, "alert" if alert else "ok", alert)


def _eval_max(fund, field, p, rule, key, display, suffix=""):
    val = fund.get(field)
    if val is None:
        return _unavailable(key, display, rule, "缺少数据")
    alert = val > p["max"]
    return _result(key, display, _fmt(val, suffix), rule, "alert" if alert else "ok", alert)


def _eval_min(fund, field, p, rule, key, display, suffix=""):
    val = fund.get(field)
    if val is None:
        return _unavailable(key, display, rule, "缺少数据")
    alert = val < p["min"]
    return _result(key, display, _fmt(val, suffix), rule, "alert" if alert else "ok", alert)


def _eval_capex(fund, p, rule, key, display):
    if p.get("basis") == "yoy_change_30pct":
        yoy = fund.get("capex_yoy_change_pct")
        if yoy is None:
            return _unavailable(key, display, rule, "缺少 CAPEX 同比数据")
        capex_pct = fund.get("capex_pct_revenue")
        alert = abs(yoy) > 30.0
        vstr = f"同比 {yoy:+.1f}%" + (f"(占营收 {capex_pct:.1f}%)" if capex_pct is not None else "")
        return _result(key, display, vstr, rule, "alert" if alert else "ok", alert)
    if "max" in p:
        return _eval_max(fund, "capex_pct_revenue", p, rule, key, display, "%")
    return _eval_min(fund, "capex_pct_revenue", p, rule, key, display, "%")


def _eval_dividend_yield(fund, p, rule, key, display):
    if p.get("ignore"):
        val = fund.get("dividend_yield_pct")
        return _result(key, display, _fmt(val, "%"), rule, "ignored", False, "该档位按规则忽略股息率")
    return _eval_min(fund, "dividend_yield_pct", p, rule, key, display, "%")


def _evaluate_indicator(ind_key, tier, tech, fund) -> Dict[str, Any]:
    spec = MONITORING_RULES[ind_key]
    display = spec["display"]
    tier_rule = spec["tiers"][tier]
    rule = tier_rule["text"]
    p = tier_rule["params"]

    if ind_key == "rsi":
        return _eval_rsi(tech, p, rule, ind_key, display)
    if ind_key == "ma_cross":
        return _eval_ma_cross(tech, p, rule, ind_key, display)
    if ind_key == "volume_spike":
        return _eval_volume(tech, p, rule, ind_key, display)
    if ind_key == "forward_pe":
        return _eval_forward_pe(fund, p, rule, ind_key, display)
    if ind_key == "pb":
        return _eval_max(fund, "pb", p, rule, ind_key, display, "x")
    if ind_key == "forecast_growth":
        return _eval_min(fund, "earnings_growth_pct", p, rule, ind_key, display, "%")
    if ind_key == "capex_pct":
        return _eval_capex(fund, p, rule, ind_key, display)
    if ind_key == "dividend_yield":
        return _eval_dividend_yield(fund, p, rule, ind_key, display)
    if ind_key == "payout_ratio":
        return _eval_max(fund, "payout_ratio_pct", p, rule, ind_key, display, "%")
    return _unavailable(ind_key, display, rule, "未知指标")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def evaluate_monitoring(
    df: Optional[pd.DataFrame],
    fundamentals: Optional[Dict[str, Any]],
    tier: str = DEFAULT_TIER,
) -> Dict[str, Any]:
    """
    按选定风险档位评估全部监控指标,返回结构化结果。

    Args:
        df: 日线 OHLCV(需足够历史以计算长周期均线)。
        fundamentals: 扁平基本面字典(来自 YfinanceFundamentalAdapter.get_metrics)。
        tier: 'low' | 'medium' | 'high'。

    Returns:
        {tier, tier_label, categories[], alerts[], deferred[], summary{}}
    """
    if tier not in TIER_LABELS:
        tier = DEFAULT_TIER
    tech = compute_technical_indicators(df)
    fund = fundamentals or {}

    categories: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]] = []
    n_eval = n_alert = n_unavail = 0

    for cat_key, ind_keys in CATEGORY_ORDER.items():
        indicators = []
        for ind_key in ind_keys:
            res = _evaluate_indicator(ind_key, tier, tech, fund)
            indicators.append(res)
            if res["status"] == "unavailable":
                n_unavail += 1
            elif res["status"] in ("ok", "alert"):
                n_eval += 1
            if res["alert"]:
                n_alert += 1
                alerts.append({"category": cat_key, **res})
        categories.append({
            "key": cat_key,
            "label": CATEGORY_LABELS[cat_key],
            "indicators": indicators,
        })

    return {
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "n_bars": tech.get("n_bars", 0),
        "categories": categories,
        "alerts": alerts,
        "deferred": DEFERRED_CATEGORIES,
        "summary": {
            "evaluated": n_eval,
            "alerts": n_alert,
            "unavailable": n_unavail,
        },
    }
