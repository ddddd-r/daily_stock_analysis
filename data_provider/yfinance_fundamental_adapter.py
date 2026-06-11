# -*- coding: utf-8 -*-
"""
yfinance 基本面 adapter —— 专为港股 / 美股提供估值、增长与股息数据。

服务于「投资组合监控」框架(提案第 2、4 类指标):
  - 前瞻 / 历史 P/E、PEG
  - P/B(市净率)
  - 预测盈利增长率、营收增长率
  - 股息率、派息比率
  - CAPEX 占营收百分比、所属行业

设计原则:
  - Fail-open:对调用方永不抛错;缺失字段保持 None。
  - 自带短 TTL 内存缓存,避免同一次分析重复请求 yfinance(.info / 财报较慢)。
  - 仅处理港股(.HK)与美股代码;A 股仍走 AkshareFundamentalAdapter。

关于单位约定(基于实测的 yfinance 返回值):
  - dividendYield:已是百分数(如 AAPL 0.37 表示 0.37%),直接使用。
  - payoutRatio / earningsGrowth / revenueGrowth:0~1 小数,乘以 100 转百分数。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> Optional[float]:
    """尽力转换为 float;无法转换或为 NaN 时返回 None。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # NaN check without importing numpy
    if f != f:
        return None
    return f


def _to_yf_symbol(stock_code: str) -> str:
    """
    将内部股票代码转换为 yfinance 符号(仅港股 / 美股)。

    Examples:
        'HK00700' -> '0700.HK'
        '00700'   -> '0700.HK'(5 位纯数字按港股处理)
        '0700.HK' -> '0700.HK'
        'AAPL'    -> 'AAPL'
        'BRK.B'   -> 'BRK.B'
    """
    code = (stock_code or "").strip().upper()
    if not code:
        return code

    # 已是 .HK 后缀:归一化港股代码到 4 位(yfinance 需 0700.HK 而非 00700.HK)
    if code.endswith(".HK"):
        digits = code[:-3].lstrip("0") or "0"
        return f"{digits.zfill(4)}.HK"

    # 港股:HK 前缀
    if code.startswith("HK"):
        digits = code[2:].lstrip("0") or "0"
        return f"{digits.zfill(4)}.HK"

    # 5 位纯数字按港股处理(00700)
    if code.isdigit() and len(code) == 5:
        digits = code.lstrip("0") or "0"
        return f"{digits.zfill(4)}.HK"

    # 其余按美股代码原样返回(AAPL、BRK.B、^GSPC 等)
    return code


class YfinanceFundamentalAdapter:
    """从 yfinance 拉取港股 / 美股基本面与股息指标(fail-open + 缓存)。"""

    def __init__(self, cache_ttl_seconds: int = 600):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = max(0, int(cache_ttl_seconds))

    # ---- 缓存 ----
    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        if self._ttl <= 0:
            return None
        with self._lock:
            item = self._cache.get(key)
            if item and (time.time() - item["ts"]) <= self._ttl:
                return item["data"]
        return None

    def _cache_put(self, key: str, data: Dict[str, Any]) -> None:
        if self._ttl <= 0:
            return
        with self._lock:
            self._cache[key] = {"ts": time.time(), "data": data}

    # ---- CAPEX 占营收 + 同比变化 ----
    @staticmethod
    def _capex_metrics(ticker: Any):
        """
        返回 (capex_pct_revenue, capex_yoy_change_pct):
          - capex_pct_revenue:最新一年 |CAPEX| / 营收 * 100
          - capex_yoy_change_pct:最新一年相对上一年的 |CAPEX| 变化百分比
        从 yfinance 现金流量表(多年)与利润表计算;失败时对应项为 None。
        """
        capex_pct = None
        capex_yoy = None
        try:
            cf = ticker.cashflow
            capex_series = None
            if cf is not None and not cf.empty:
                for label in ("Capital Expenditure", "Capital Expenditures"):
                    if label in cf.index:
                        capex_series = [_safe_float(x) for x in cf.loc[label].tolist()]
                        break
            if capex_series:
                capex_series = [c for c in capex_series if c is not None]
            fin = ticker.financials
            revenue = None
            if fin is not None and not fin.empty:
                for label in ("Total Revenue", "TotalRevenue"):
                    if label in fin.index:
                        revenue = _safe_float(fin.loc[label].iloc[0])
                        break
            if capex_series:
                if revenue and revenue != 0:
                    capex_pct = abs(capex_series[0]) / revenue * 100.0
                if len(capex_series) >= 2 and capex_series[1] not in (None, 0):
                    prev = abs(capex_series[1])
                    if prev != 0:
                        capex_yoy = (abs(capex_series[0]) - prev) / prev * 100.0
        except Exception as exc:  # noqa: BLE001 - fail-open
            logger.debug("CAPEX 估算失败: %s", exc)
        return capex_pct, capex_yoy

    # ---- 历史 P/E 区间(5 年,均值/标准差)----
    @staticmethod
    def _pe_history_band(ticker: Any):
        """
        返回 (pe_hist_mean, pe_hist_std, pe_hist_n):基于年度 EPS 与对应财年末价格
        估算近 5 年历史 P/E 的均值与总体标准差。数据不足(<2 点)时返回 (None, None, 0)。
        """
        try:
            import statistics
            import pandas as pd

            inc = ticker.income_stmt
            eps_row = None
            if inc is not None and not inc.empty:
                for label in ("Diluted EPS", "Basic EPS"):
                    if label in inc.index:
                        eps_row = inc.loc[label]
                        break
            if eps_row is None:
                return None, None, 0

            hist = ticker.history(period="5y", interval="1mo")
            if hist is None or hist.empty or "Close" not in hist.columns:
                return None, None, 0
            closes = hist["Close"].dropna()
            if closes.empty:
                return None, None, 0
            idx = closes.index
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)

            pe_points = []
            for date, eps in eps_row.items():
                eps_f = _safe_float(eps)
                if eps_f is None or eps_f <= 0:
                    continue
                target = pd.Timestamp(date)
                if target.tz is not None:
                    target = target.tz_localize(None)
                pos = idx.get_indexer([target], method="nearest")[0]
                if pos < 0:
                    continue
                price = _safe_float(closes.iloc[pos])
                if price is None or price <= 0:
                    continue
                pe_points.append(price / eps_f)

            if len(pe_points) >= 2:
                mean = statistics.mean(pe_points)
                std = statistics.pstdev(pe_points)
                return mean, std, len(pe_points)
        except Exception as exc:  # noqa: BLE001 - fail-open
            logger.debug("历史 P/E 区间估算失败: %s", exc)
        return None, None, 0

    def get_metrics(self, stock_code: str, include_capex: bool = True) -> Dict[str, Any]:
        """
        返回归一化的基本面 / 股息指标(扁平结构,fail-open)。

        返回字段:
            name, sector, currency,
            forward_pe, trailing_pe, peg, pb,
            earnings_growth_pct, revenue_growth_pct,
            dividend_yield_pct, payout_ratio_pct, capex_pct_revenue,
            status('ok'|'partial'|'failed'), errors(list)
        """
        yf_symbol = _to_yf_symbol(stock_code)
        cache_key = f"{yf_symbol}|{int(include_capex)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        result: Dict[str, Any] = {
            "symbol": yf_symbol,
            "name": None,
            "sector": None,
            "currency": None,
            "forward_pe": None,
            "trailing_pe": None,
            "peg": None,
            "pb": None,
            "earnings_growth_pct": None,
            "revenue_growth_pct": None,
            "dividend_yield_pct": None,
            "payout_ratio_pct": None,
            "capex_pct_revenue": None,
            "capex_yoy_change_pct": None,
            "pe_hist_mean": None,
            "pe_hist_std": None,
            "pe_hist_n": 0,
            "status": "failed",
            "errors": [],
        }

        try:
            import yfinance as yf
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"import_yfinance:{type(exc).__name__}")
            self._cache_put(cache_key, result)
            return result

        try:
            ticker = yf.Ticker(yf_symbol)
            info = ticker.info or {}
        except Exception as exc:  # noqa: BLE001 - fail-open
            result["errors"].append(f"ticker_info:{type(exc).__name__}")
            self._cache_put(cache_key, result)
            return result

        result["name"] = info.get("longName") or info.get("shortName")
        result["sector"] = info.get("sector")
        result["currency"] = info.get("currency")
        result["forward_pe"] = _safe_float(info.get("forwardPE"))
        result["trailing_pe"] = _safe_float(info.get("trailingPE"))
        result["peg"] = _safe_float(info.get("trailingPegRatio") or info.get("pegRatio"))
        result["pb"] = _safe_float(info.get("priceToBook"))

        # dividendYield 已是百分数;payout / growth 为 0~1 小数 -> 百分数
        result["dividend_yield_pct"] = _safe_float(info.get("dividendYield"))
        payout = _safe_float(info.get("payoutRatio"))
        result["payout_ratio_pct"] = payout * 100.0 if payout is not None else None
        eg = _safe_float(info.get("earningsGrowth"))
        if eg is None:
            eg = _safe_float(info.get("earningsQuarterlyGrowth"))
        result["earnings_growth_pct"] = eg * 100.0 if eg is not None else None
        rg = _safe_float(info.get("revenueGrowth"))
        result["revenue_growth_pct"] = rg * 100.0 if rg is not None else None

        if include_capex:
            capex_pct, capex_yoy = self._capex_metrics(ticker)
            result["capex_pct_revenue"] = capex_pct
            result["capex_yoy_change_pct"] = capex_yoy
            pe_mean, pe_std, pe_n = self._pe_history_band(ticker)
            result["pe_hist_mean"] = pe_mean
            result["pe_hist_std"] = pe_std
            result["pe_hist_n"] = pe_n

        # 状态判定:任一核心字段拿到即 partial/ok
        core_fields = [
            result["forward_pe"], result["trailing_pe"], result["pb"],
            result["dividend_yield_pct"], result["payout_ratio_pct"],
            result["earnings_growth_pct"],
        ]
        present = [v for v in core_fields if v is not None]
        if not present:
            result["status"] = "failed"
        elif len(present) >= 4:
            result["status"] = "ok"
        else:
            result["status"] = "partial"

        self._cache_put(cache_key, result)
        return result
