# -*- coding: utf-8 -*-
"""
测试发送:把最近一条分析报告(优先港股/美股,含投资组合监控)发送到已配置的通知渠道。

报告内容会经统一发送入口转为繁体(香港标准)。
用法:python scripts/send_test_report.py [record_id]
"""
import sys
import os
import sqlite3
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import setup_env, get_config
from src.logging_config import setup_logging


def main() -> int:
    setup_env()
    setup_logging(log_prefix="test_send")
    cfg = get_config()

    from src.notification import NotificationService
    from src.services.history_service import HistoryService

    notifier = NotificationService()
    if not notifier.is_available():
        print("❌ 没有可用的通知渠道。请在 .env 配置 EMAIL_SENDER / EMAIL_PASSWORD / EMAIL_RECEIVERS(或其他渠道)。")
        print(f"   当前:email_sender={cfg.email_sender} receivers={cfg.email_receivers} has_password={bool(cfg.email_password)}")
        return 1

    # 选取报告记录:命令行指定 record_id,否则取最新一条
    record_id = sys.argv[1] if len(sys.argv) > 1 else None
    con = sqlite3.connect("data/stock_analysis.db")
    cur = con.cursor()
    if record_id:
        cur.execute("SELECT id, code FROM analysis_history WHERE id=?", (record_id,))
    else:
        cur.execute("SELECT id, code FROM analysis_history ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    con.close()
    if not row:
        print("❌ 数据库中没有分析记录,请先在网页分析一只股票。")
        return 1
    rid, code = row
    print(f"使用分析记录 id={rid} code={code}")

    # 重建 AnalysisResult 并生成完整报告(含投资组合监控)
    svc = HistoryService()
    result = svc._rebuild_analysis_result(
        json.loads(_raw_result(rid)), _record(rid)
    )
    if result is None:
        print("❌ 无法重建分析结果。")
        return 1

    report_md = notifier.generate_dashboard_report([result])
    print(f"报告已生成({len(report_md)} 字),正在发送到渠道:{notifier.get_channel_names()} ...")

    ok = notifier.send(report_md, email_stock_codes=[code], email_send_to_all=True)
    print("✅ 发送成功" if ok else "❌ 发送失败,请查看日志")
    return 0 if ok else 1


def _raw_result(rid):
    con = sqlite3.connect("data/stock_analysis.db")
    cur = con.cursor()
    cur.execute("SELECT raw_result FROM analysis_history WHERE id=?", (rid,))
    raw = cur.fetchone()[0]
    con.close()
    return raw


def _record(rid):
    """返回最小可用的 record 对象(_rebuild_analysis_result 需要的字段)。"""
    from src.storage import get_db
    db = get_db()
    rec = db.get_analysis_history_by_id(rid) if hasattr(db, "get_analysis_history_by_id") else None
    if rec is not None:
        return rec
    # 退化:用 SimpleNamespace 兜底
    from types import SimpleNamespace
    con = sqlite3.connect("data/stock_analysis.db")
    cur = con.cursor()
    cur.execute("SELECT code, name, analysis_summary, operation_advice, trend_prediction, sentiment_score, news_content FROM analysis_history WHERE id=?", (rid,))
    code, name, summ, op, trend, score, news = cur.fetchone()
    con.close()
    return SimpleNamespace(code=code, name=name, analysis_summary=summ, operation_advice=op,
                           trend_prediction=trend, sentiment_score=score, news_content=news)


if __name__ == "__main__":
    raise SystemExit(main())
