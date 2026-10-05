# -*- coding: utf-8 -*-
"""
analysis/mainline.py —— 主线识别
==================================
输入：行业板块行情（腾讯/东财）+ 板块成分股 + 全市场快照
输出：主线候选排行（板块强度评分）+ 强主线名单。

评分口径（简化启发式，连板数据在降级通道下不可得时该项权重并入容量）：
  板块强度 = 40%×板块当日涨幅排名 + 30%×板块内涨停家数 + 20%×上涨家数占比 + 10%×容量/连板
对候选板块逐个拉成分股统计涨停与上涨占比，数据源缺失的字段按空处理并在页面标注。
"""
from __future__ import annotations

import pandas as pd

from data import market_data as md
import config

_TOP_SCAN = 10  # 对涨幅前 N 板块拉成分股做精确统计


def _board_internal_stats(industry: str, spot: pd.DataFrame) -> dict:
    """板块内部统计：股票数 / 涨停家数 / 上涨占比（成分股涨跌幅优先，缺失时用全市场快照匹配）。"""
    try:
        cons = md.get_industry_cons(industry)
    except Exception:  # noqa: BLE001
        cons = None
    if cons is None or cons.empty:
        return {"总数": 0, "涨停": 0, "上涨占比": 0.0}

    codes = cons["代码"].astype(str).str.zfill(6)
    sub = spot[spot["代码"].isin(codes)].copy() if spot is not None and not spot.empty else pd.DataFrame()
    if sub.empty:
        return {"总数": len(codes), "涨停": 0, "上涨占比": 0.0}

    chg = pd.to_numeric(sub["涨跌幅"], errors="coerce")
    limit_n = int((chg >= config.LIMIT_UP_RATIO * 100).sum())
    up_n = int((chg > 0).sum())
    ratio = up_n / len(chg) if len(chg) else 0.0
    return {"总数": len(chg), "涨停": limit_n, "上涨占比": round(ratio, 3)}


def mainline_ranking(top_n: int = 6) -> dict:
    out = {"ranking": None, "strong": [], "errors": []}

    try:
        ind = md.get_industry_spot()
        if ind is None or ind.empty:
            out["errors"].append("行业板块行情无数据（东财/腾讯均不可达）")
            return out
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"行业板块行情获取失败: {e}")
        return out

    # 全市场快照（用于板块内部统计与涨停近似）
    try:
        spot = md.get_all_stock_spot()
    except Exception:  # noqa: BLE001
        spot = None

    df = ind.copy()
    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce").fillna(0)
    df["涨幅分"] = df["涨跌幅"].rank(pct=True)
    df["容量分"] = pd.to_numeric(df["总市值"], errors="coerce").rank(pct=True).fillna(0.5)

    # 候选：涨幅分前 _TOP_SCAN 的板块拉成分股精算
    cand = df.sort_values("涨幅分", ascending=False).head(_TOP_SCAN).copy()
    stats = {}
    for _, r in cand.iterrows():
        industry = str(r["板块名称"])
        stats[industry] = _board_internal_stats(industry, spot)
    df["涨停家数"] = df["板块名称"].map(lambda x: stats.get(x, {}).get("涨停", 0))
    df["上涨占比"] = df["板块名称"].map(lambda x: stats.get(x, {}).get("上涨占比", 0.0))
    df["板块股票数"] = df["板块名称"].map(lambda x: stats.get(x, {}).get("总数", 0))

    # 评分
    max_zt = df["涨停家数"].max()
    zt_part = (df["涨停家数"] / max_zt).fillna(0) if max_zt else 0
    df["主线评分"] = (40 * df["涨幅分"] + 30 * zt_part + 20 * df["上涨占比"] + 10 * df["容量分"]).round(1)

    show_cols = ["板块名称", "涨跌幅", "总市值", "换手率", "领涨股票",
                 "领涨股票-涨跌幅", "板块股票数", "涨停家数", "上涨占比", "主线评分"]
    show_cols = [c for c in show_cols if c in df.columns]

    top = df.sort_values("主线评分", ascending=False).head(top_n).copy()
    top["排名"] = range(1, len(top) + 1)
    top["总市值"] = (pd.to_numeric(top["总市值"], errors="coerce") / 1e8).round(1)
    top["换手率"] = pd.to_numeric(top["换手率"], errors="coerce").round(2)
    top["上涨占比"] = (pd.to_numeric(top["上涨占比"], errors="coerce") * 100).round(1)

    out["ranking"] = top[["排名"] + show_cols].reset_index(drop=True)

    # 强主线：涨停家数 >= 2，或领涨股涨幅 >= 9.5%（近似连板/封板）
    for _, r in top.iterrows():
        lead_chg = pd.to_numeric(r.get("领涨股票-涨跌幅"), errors="coerce") or 0
        if r["涨停家数"] >= 2 or lead_chg >= 9.5:
            out["strong"].append(str(r["板块名称"]))
    return out
