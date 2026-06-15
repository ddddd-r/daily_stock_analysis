# -*- coding: utf-8 -*-
"""
Tests for YfinanceFetcher transient-error retry classification.

Yahoo Finance rate-limits shared IPs (HTTP 429) and drops connections; those
are wrapped into DataFetchError. The retry predicate must treat those as
retriable while letting genuine "no data" results fail fast.
"""

import sys
import unittest
from unittest.mock import MagicMock

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()

from data_provider.yfinance_fetcher import _is_retriable_yf_error
from data_provider.base import DataFetchError


class RetryPredicateTest(unittest.TestCase):
    def test_raw_connection_errors_retry(self):
        self.assertTrue(_is_retriable_yf_error(ConnectionError("reset")))
        self.assertTrue(_is_retriable_yf_error(TimeoutError("slow")))

    def test_wrapped_rate_limit_and_dropped_connection_retry(self):
        self.assertTrue(_is_retriable_yf_error(
            DataFetchError("Yahoo Finance 获取数据失败: 429 Client Error: Too Many Requests")
        ))
        self.assertTrue(_is_retriable_yf_error(
            DataFetchError("Yahoo Finance 获取数据失败: ('Connection aborted.', "
                           "RemoteDisconnected('Remote end closed connection without response'))")
        ))
        self.assertTrue(_is_retriable_yf_error(
            DataFetchError("... Max retries exceeded with url ...")
        ))

    def test_genuine_missing_data_fails_fast(self):
        self.assertFalse(_is_retriable_yf_error(
            DataFetchError("Yahoo Finance 未查询到 HK06869 的数据")
        ))
        self.assertFalse(_is_retriable_yf_error(ValueError("unrelated bug")))


if __name__ == "__main__":
    unittest.main()
