# -*- coding: utf-8 -*-
"""
analysis/risk.py —— 组合级风控
===============================
在单笔仓位计算器之上增加组合级约束：
  1) 总仓位 ≤ 大盘阶段对应的五档上限（phase → 允许仓位）
  2) 单主线集中度：同一行业/主线持仓合计占比上限
  3) 账户回撤熔断：累计盈亏从高点回撤 ≥ 阈值 → 强制空仓 N 日
  4) 连续亏损降档：最近连亏 N 笔 → 仓位减半/停手

输入全部来自页面（总资金、当前持仓市值、持仓行业）与复盘记录；
所有规则为启发式风控建议，仅供个人交易纪律执行参考。
"""
from __future__ import annotations

import pandas as pd

import config

# 阶段 → 允许总仓位上限（与 config.MARKET_PHASE_RULES / POSITION_TIERS 联动）
_PHASE_CAP = {
    "强势": 0.80,   # 主升档上界
    "震荡": 0.50,   # 启动档上界
    "弱势": 0.20,   # 空仓防御上界
    "冰点": 0.30,   # 试错档上界（超跌专用）
    "数据不足": 0.20,
}

# 单主线集中度上限（同一行业合计占总资金比例）
MAX_LINE_CONCENTRATION = 0.40
# 账户回撤熔断：累计盈亏回撤超过该比例 → 建议空仓
DRAWDOWN_TRIGGER = 0.10
# 连续亏损降档：连亏笔数达到该值 → 建议仓位减半
LOSS_STREAK_TRIGGER = 3


def phase_cap(phase: str | None) -> dict:
    """大盘阶段 → 允许仓位上限与推荐档位说明。"""
    ph = phase or "数据不足"
    cap = _PHASE_CAP.get(ph, 0.20)
    rule = config.MARKET_PHASE_RULES.get(ph, {})
    return {
        "phase": ph,
        "cap": cap,
        "recommend": rule.get("position", "空仓防御 0-2 成"),
        "desc": rule.get("desc", ""),
    }


def total_position_check(total_capital: float, holdings_value: float,
                         phase: str | None) -> dict:
    """总仓位检查：当前总持仓市值 / 总资金 vs 阶段上限。"""
    if not total_capital or total_capital <= 0:
        return {"ok": True, "ratio": None, "warn": "未输入总资金，跳过总仓位检查"}
    ratio = holdings_value / total_capital
    cap_info = phase_cap(phase)
    over = ratio > cap_info["cap"] + 1e-9
    return {
        "ok": not over,
        "ratio": round(ratio, 3),
        "cap": cap_info["cap"],
        "phase": cap_info["phase"],
        "warn": (f"总仓位 {ratio:.0%} 超出「{cap_info['phase']}」阶段上限 "
                 f"{cap_info['cap']:.0%}，请减仓至 {cap_info['cap']:.0%} 以内")
        if over else "",
        "recommend": cap_info["recommend"],
    }


def concentration_check(holdings: list[dict]) -> dict:
    """单主线集中度：按行业聚合持仓市值占比。holdings: [{"market_value":, "industry":}]"""
    if not holdings:
        return {"ok": True, "items": [], "warn": ""}
    from collections import defaultdict
    agg: dict[str, float] = defaultdict(float)
    for h in holdings:
        ind = str(h.get("industry", "") or "未分类")
        agg[ind] += float(h.get("market_value", 0) or 0)
    total = sum(agg.values())
    if total <= 0:
        return {"ok": True, "items": [], "warn": ""}
    items = []
    warns = []
    for ind, v in sorted(agg.items(), key=lambda x: -x[1]):
        r = v / total
        items.append({"行业": ind, "市值": round(v, 0), "占比": round(r, 3)})
        if r > MAX_LINE_CONCENTRATION:
            warns.append(f"「{ind}」集中度 {r:.0%} 超过上限 {MAX_LINE_CONCENTRATION:.0%}，同主线仓位过重")
    return {"ok": not warns, "items": items, "warn": "；".join(warns)}


def drawdown_check(reviews: pd.DataFrame, total_capital: float) -> dict:
    """账户回撤熔断：按复盘累计盈亏相对高点回撤。"""
    if reviews is None or reviews.empty:
        return {"ok": True, "dd": 0.0, "warn": "", "triggered": False}
    pnl = pd.to_numeric(reviews["pnl_pct"], errors="coerce").fillna(0)
    # 用总资金×单笔盈亏% 近似金额（简化：盈亏% 为占总资金比例时直接累加）
    cum = pnl.cumsum()
    peak = cum.cummax()
    if float(peak.iloc[-1]) <= 0:
        return {"ok": True, "dd": 0.0, "warn": "累计盈亏尚未创新高", "triggered": False}
    dd = float((peak.iloc[-1] - cum.iloc[-1]) / max(peak.iloc[-1], 1e-9))
    triggered = dd >= DRAWDOWN_TRIGGER
    return {
        "ok": not triggered,
        "dd": round(dd * 100, 1),
        "triggered": triggered,
        "warn": (f"累计盈亏已从高点回撤 {dd:.1%} ≥ {DRAWDOWN_TRIGGER:.0%}，"
                 f"触发熔断：建议空仓 {config.RISK_COOLDOWN_DAYS} 个交易日，只复盘不开仓")
        if triggered else "",
    }


def losing_streak_check(reviews: pd.DataFrame) -> dict:
    """连续亏损降档：最近连亏笔数达到阈值 → 建议减半仓位。"""
    if reviews is None or reviews.empty:
        return {"ok": True, "streak": 0, "warn": ""}
    df = reviews.sort_values("date", ascending=False)
    pnl = pd.to_numeric(df["pnl_pct"], errors="coerce").fillna(0)
    streak = 0
    for v in pnl:
        if v < 0:
            streak += 1
        else:
            break
    triggered = streak >= LOSS_STREAK_TRIGGER
    return {
        "ok": not triggered,
        "streak": int(streak),
        "triggered": triggered,
        "warn": (f"最近连续亏损 {streak} 笔 ≥ {LOSS_STREAK_TRIGGER}，"
                 f"触发降档：新开仓仓位减半，直到出现盈利单")
        if triggered else "",
    }


def full_risk_report(phase: str | None, total_capital: float,
                     holdings: list[dict], reviews: pd.DataFrame) -> dict:
    """汇总风控报告（页面展示）。"""
    hv = sum(float(h.get("market_value", 0) or 0) for h in holdings)
    return {
        "phase": phase_cap(phase),
        "total": total_position_check(total_capital, hv, phase),
        "concentration": concentration_check(holdings),
        "drawdown": drawdown_check(reviews, total_capital),
        "streak": losing_streak_check(reviews),
        "holdings_value": round(hv, 0),
    }
