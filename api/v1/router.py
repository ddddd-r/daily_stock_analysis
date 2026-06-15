# -*- coding: utf-8 -*-
"""
===================================
API v1 路由聚合
===================================

职责：
1. 聚合 v1 版本的所有 endpoint 路由
2. 统一添加 /api/v1 前缀
"""

from fastapi import APIRouter

from api.v1.endpoints import analysis, auth, history, stocks, backtest, system_config, agent, usage, portfolio, users

# 创建 v1 版本主路由
router = APIRouter(prefix="/api/v1")

router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"]
)

router.include_router(
    agent.router,
    prefix="/agent",
    tags=["Agent"]
)

router.include_router(
    analysis.router,
    prefix="/analysis",
    tags=["Analysis"]
)

router.include_router(
    # No prefix here: history routes carry the full "/history" path so the
    # collection endpoint is "/api/v1/history" with neither an empty route
    # path (which FastAPI rejects when the include prefix is empty) nor a
    # trailing slash (which the SPA catch-all would 404 before redirecting).
    history.router,
    tags=["History"]
)

router.include_router(
    stocks.router,
    prefix="/stocks",
    tags=["Stocks"]
)

router.include_router(
    backtest.router,
    prefix="/backtest",
    tags=["Backtest"]
)

router.include_router(
    system_config.router,
    prefix="/system",
    tags=["SystemConfig"]
)

router.include_router(
    usage.router,
    prefix="/usage",
    tags=["Usage"]
)

router.include_router(
    portfolio.router,
    prefix="/portfolio",
    tags=["Portfolio"]
)

router.include_router(
    # No prefix: routes carry the full "/users" path so the collection
    # endpoint avoids an empty route path (rejected by FastAPI) and a trailing
    # slash (404'd by the SPA catch-all). See history router above.
    users.router,
    tags=["Users"]
)
