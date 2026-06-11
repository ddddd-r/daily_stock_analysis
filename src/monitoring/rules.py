# -*- coding: utf-8 -*-
"""
监控规则集 —— 提案四表的「低 / 中 / 高风险规则集」忠实编码。

本模块只承载「数据」:每个指标在三个风险档位下的规则文字(原文转译)与数值阈值。
实际的指标计算与规则评估逻辑见 evaluator.py。

风险档位语义(来自提案表头):
    low    -> Low Risk Rule Set (Value / Safety)        价值 / 安全
    medium -> Medium Risk Rule Set (Standard Trend)     标准趋势
    high   -> High Risk Rule Set (Aggressive / Volatility) 激进 / 波动
"""

from __future__ import annotations

from typing import Dict, List

TIERS: List[str] = ["low", "medium", "high"]
DEFAULT_TIER: str = "medium"

TIER_LABELS: Dict[str, str] = {
    "low": "低风险(价值/安全)",
    "medium": "中风险(标准趋势)",
    "high": "高风险(激进/波动)",
}

CATEGORY_LABELS: Dict[str, str] = {
    "technical": "技术分析与动量触发",
    "fundamental": "基本面与估值参数",
    "dividend": "股息与股东回报",
}

# 第 3 类:暂未实现,报告中以占位形式标注(用户选择本期跳过)
DEFERRED_CATEGORIES: List[Dict[str, str]] = [
    {
        "key": "derivative",
        "label": "衍生品与流动性指标",
        "reason": "Call/Put 比率、累积沽空、CBBC 庄家集中度(Max Pain)缺乏免费数据源,本期暂未实现。",
        "indicators": "Call/Put Volume Ratio、累积沽空 (Cumulative Short Interest)、Market Maker Concentration (CBBC)",
    },
]


# ----------------------------------------------------------------------------
# 指标元数据 + 各档位规则文字(原文转译)+ 数值阈值(params)
#
# params 字段含义随指标而定,evaluator 中对应解读。值为 None 表示该档位规则
# 依赖历史 / 同业数据(如 5 年 P/E 均值、行业均值、CAPEX 同比),免费数据源无法
# 直接取得 —— evaluator 将其标记为「数据不可用」。
# ----------------------------------------------------------------------------
MONITORING_RULES: Dict[str, Dict] = {
    # ===== 1. 技术分析与动量触发 =====
    "rsi": {
        "category": "technical",
        "display": "RSI(相对强弱)",
        "tiers": {
            "low": {"text": "RSI < 30(极度超卖)", "params": {"oversold": 30, "overbought": None}},
            "medium": {"text": "RSI < 40 或 > 70(趋势边界)", "params": {"oversold": 40, "overbought": 70}},
            "high": {"text": "RSI < 20 或 > 85(超买挤压)", "params": {"oversold": 20, "overbought": 85}},
        },
    },
    "ma_cross": {
        "category": "technical",
        "display": "均线金叉死叉(MA/EMA)",
        "tiers": {
            "low": {"text": "死亡交叉:50MA 下穿 200MA", "params": {"fast": 50, "slow": 200, "kind": "sma", "direction": "down"}},
            "medium": {"text": "趋势转向:10EMA 下穿 30EMA", "params": {"fast": 10, "slow": 30, "kind": "ema", "direction": "down"}},
            "high": {"text": "微观反转:5EMA 与 10EMA 交叉", "params": {"fast": 5, "slow": 10, "kind": "ema", "direction": "any"}},
        },
    },
    "volume_spike": {
        "category": "technical",
        "display": "成交量异动(vs 20 日均量)",
        "tiers": {
            "low": {"text": "下跌日成交量 > 1.5x 均量", "params": {"mult": 1.5, "context": "down_day"}},
            "medium": {"text": "突破时成交量 > 2.0x 均量", "params": {"mult": 2.0, "context": "breakout"}},
            "high": {"text": "成交量 > 3.5x 均量(机构大单/高潮)", "params": {"mult": 3.5, "context": "any"}},
        },
    },

    # ===== 2. 基本面与估值参数 =====
    "forward_pe": {
        "category": "fundamental",
        "display": "前瞻 P/E",
        "tiers": {
            # 以 yfinance 年度 EPS + 财年末价格估算的「5 年历史 P/E 区间」作比较基准
            "low": {"text": "前瞻 P/E > 5 年历史均值 + 1 个标准差", "params": {"basis": "hist_band_1sd"}},
            # 行业均值免费数据源不可得,改以自身 5 年历史均值近似
            "medium": {"text": "前瞻 P/E > 5 年历史均值(以自身历史近似行业均值)", "params": {"basis": "hist_band_mean"}},
            "high": {"text": "忽略 P/E,仅当 PEG > 2.0 触发", "params": {"basis": "peg", "peg_max": 2.0}},
        },
    },
    "pb": {
        "category": "fundamental",
        "display": "P/B(市净率)",
        "tiers": {
            "low": {"text": "P/B > 2.5x(资产较重行业)", "params": {"max": 2.5}},
            "medium": {"text": "P/B > 5x", "params": {"max": 5.0}},
            "high": {"text": "P/B > 10x(极端溢价)", "params": {"max": 10.0}},
        },
    },
    "forecast_growth": {
        "category": "fundamental",
        "display": "预测盈利增长率",
        "tiers": {
            "low": {"text": "预测增长跌破 < 5%", "params": {"min": 5.0}},
            "medium": {"text": "预测增长跌破 < 15%", "params": {"min": 15.0}},
            "high": {"text": "预测增长跌破 < 25%(增长减速)", "params": {"min": 25.0}},
        },
    },
    "capex_pct": {
        "category": "fundamental",
        "display": "CAPEX 占营收",
        "tiers": {
            "low": {"text": "CAPEX > 营收 20%(资本沉重)", "params": {"max": 20.0}},
            # 中档依赖同比变化 —— 免费数据源无法直接取得
            "medium": {"text": "CAPEX 同比变化 ±30%", "params": {"basis": "yoy_change_30pct"}},
            "high": {"text": "CAPEX < 5%(未能再投资)", "params": {"min": 5.0}},
        },
    },

    # ===== 4. 股息与股东回报 =====
    "dividend_yield": {
        "category": "dividend",
        "display": "股息率",
        "tiers": {
            "low": {"text": "股息率跌破 < 3.5%", "params": {"min": 3.5}},
            "medium": {"text": "股息率跌破 < 1.5%", "params": {"min": 1.5}},
            "high": {"text": "完全忽略(成长股/无股息配置)", "params": {"ignore": True}},
        },
    },
    "payout_ratio": {
        "category": "dividend",
        "display": "派息比率",
        "tiers": {
            "low": {"text": "派息比率 > 75%(股息不可持续)", "params": {"max": 75.0}},
            "medium": {"text": "派息比率 > 50%", "params": {"max": 50.0}},
            "high": {"text": "派息比率 > 90%(临近削减股息风险)", "params": {"max": 90.0}},
        },
    },
}

# 报告中各类别下指标的展示顺序
CATEGORY_ORDER: Dict[str, List[str]] = {
    "technical": ["rsi", "ma_cross", "volume_spike"],
    "fundamental": ["forward_pe", "pb", "forecast_growth", "capex_pct"],
    "dividend": ["dividend_yield", "payout_ratio"],
}
