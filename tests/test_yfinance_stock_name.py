# -*- coding: utf-8 -*-
"""
Tests for YfinanceFetcher.get_stock_name.

HK realtime (akshare/eastmoney) is flaky and no other fetcher can name an HK
stock when it's down, so HK names fell through to "" and the UI showed
"Unknown". YfinanceFetcher now resolves names from Yahoo Finance as a fallback.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()

from data_provider.yfinance_fetcher import YfinanceFetcher


def _fake_yf_module(info: dict):
    """Build a stand-in yfinance module whose Ticker(...).info == info."""
    mod = types.ModuleType("yfinance")
    ticker = MagicMock()
    ticker.info = info
    mod.Ticker = MagicMock(return_value=ticker)
    return mod


class YfinanceStockNameTest(unittest.TestCase):
    def test_method_exists(self):
        # Manager.get_stock_name only calls fetchers that expose get_stock_name.
        self.assertTrue(hasattr(YfinanceFetcher, "get_stock_name"))

    def test_resolves_hk_name_from_short_name(self):
        with patch.dict(sys.modules, {"yfinance": _fake_yf_module({"shortName": "KB LAMINATES"})}):
            self.assertEqual(YfinanceFetcher().get_stock_name("HK01888"), "KB LAMINATES")

    def test_falls_back_to_long_name(self):
        with patch.dict(sys.modules, {"yfinance": _fake_yf_module({"longName": "Apple Inc."})}):
            self.assertEqual(YfinanceFetcher().get_stock_name("AAPL"), "Apple Inc.")

    def test_meaningless_name_returns_none(self):
        # A name equal to the code is not meaningful -> None (keep degrading).
        with patch.dict(sys.modules, {"yfinance": _fake_yf_module({"shortName": "AAPL"})}):
            self.assertIsNone(YfinanceFetcher().get_stock_name("AAPL"))

    def test_network_error_returns_none(self):
        mod = types.ModuleType("yfinance")
        mod.Ticker = MagicMock(side_effect=ConnectionError("boom"))
        with patch.dict(sys.modules, {"yfinance": mod}):
            self.assertIsNone(YfinanceFetcher().get_stock_name("HK06869"))


if __name__ == "__main__":
    unittest.main()
