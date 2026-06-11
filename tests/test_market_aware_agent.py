# -*- coding: utf-8 -*-
"""
Tests for market-aware (A股/港股/美股) agent prompts and hint injection.

Verifies that the 问股 / report agent adapts to Hong Kong and US stocks:
- both system prompts cover all three markets and render via .format();
- _build_user_message injects a deterministic market hint when the stock
  code is known, with the correct currency symbol and chip-distribution rule;
- A-share behaviour is unchanged.
"""

import sys
import unittest
from unittest.mock import MagicMock

# Heavy / network-bound deps are stubbed so the module imports in isolation,
# mirroring tests/test_hk_realtime_routing.py.
if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
if "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider import market_tag, market_currency_symbol, market_display_name
from src.agent.executor import (
    AGENT_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT,
    MARKET_ADAPTATION_SECTION,
    AgentExecutor,
)


class MarketHelpersTest(unittest.TestCase):
    def test_market_tag_classification(self):
        cases = {
            "600519": "cn", "000001": "cn", "920748": "cn",
            "00700": "hk", "HK00700": "hk", "0700.HK": "hk",
            "AAPL": "us", "BRK.B": "us", "NVDA": "us",
        }
        for code, expected in cases.items():
            self.assertEqual(market_tag(code), expected, code)

    def test_currency_and_display_names(self):
        self.assertEqual(market_currency_symbol("cn"), "¥")
        self.assertEqual(market_currency_symbol("hk"), "HK$")
        self.assertEqual(market_currency_symbol("us"), "US$")
        self.assertEqual(market_display_name("cn"), "A股")
        self.assertEqual(market_display_name("hk"), "港股")
        self.assertEqual(market_display_name("us"), "美股")


class PromptRenderingTest(unittest.TestCase):
    def test_market_section_has_no_braces(self):
        # It is injected as a .format() value, so it must contain no braces.
        self.assertNotIn("{", MARKET_ADAPTATION_SECTION)
        self.assertNotIn("}", MARKET_ADAPTATION_SECTION)

    def test_both_prompts_render_and_cover_all_markets(self):
        for prompt in (AGENT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT):
            out = prompt.format(skills_section="SKILLS", market_section=MARKET_ADAPTATION_SECTION)
            for token in ("港股", "美股", "HK$", "US$", "市场识别与适配", "get_stock_info"):
                self.assertIn(token, out)

    def test_agent_prompt_preserves_ashare_logic(self):
        out = AGENT_SYSTEM_PROMPT.format(skills_section="", market_section=MARKET_ADAPTATION_SECTION)
        for token in ("get_chip_distribution", "多头排列", "乖离率", "决策仪表盘", '"stock_name"'):
            self.assertIn(token, out)


class MarketHintTest(unittest.TestCase):
    def test_ashare_hint_keeps_chip(self):
        hint = AgentExecutor._market_hint("600519")
        self.assertIn("A股", hint)
        self.assertIn("¥", hint)
        self.assertIn("筹码", hint)

    def test_hk_hint_skips_chip_uses_hkd(self):
        hint = AgentExecutor._market_hint("00700")
        self.assertIn("港股", hint)
        self.assertIn("HK$", hint)
        self.assertIn("跳过筹码", hint)

    def test_us_hint_skips_chip_uses_usd(self):
        hint = AgentExecutor._market_hint("AAPL")
        self.assertIn("美股", hint)
        self.assertIn("US$", hint)
        self.assertIn("跳过筹码", hint)

    def test_empty_code_yields_no_hint(self):
        self.assertEqual(AgentExecutor._market_hint(""), "")

    def test_build_user_message_injects_hint(self):
        executor = AgentExecutor.__new__(AgentExecutor)  # avoid LLM/registry setup
        msg = executor._build_user_message("分析", context={"stock_code": "00700"})
        self.assertIn("港股", msg)
        self.assertIn("HK$", msg)
        # A-share code should not leak HK/US currency
        msg_cn = executor._build_user_message("分析", context={"stock_code": "600519"})
        self.assertNotIn("HK$", msg_cn)
        self.assertNotIn("US$", msg_cn)


if __name__ == "__main__":
    unittest.main()
