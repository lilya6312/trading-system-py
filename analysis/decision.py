# -*- coding: utf-8 -*-
"""
analysis/decision.py —— 交易系统决策
======================================
两大功能：
1) 模型匹配：输入个股代码 + 六大模型之一，拉历史 K 线计算指标，
   按 config.MODELS 的规则判断"符合 / 等待 / 回避"，给出买点/卖点/止损建议。
2) 仓位计算：按"单笔亏损预算 ≤ 总资金×风险比例"反推可买股数与占用仓位，
   并对照五档仓位校验。
"""
from __future__ import annotations

import math

import pandas as pd

from analysis.market import ma
from analysis.stock import calc_indicators
from data import market_data as md
import config


# ---------------- 模型命中判定 ----------------
def _model_hit(model_name: str, i: dict) -> dict:
    """返回 {命中: [条件], 未命中: [条件]}，条件文案尽量可读。"""
    hit, miss = [], []
    last = i["last"]

    def check(ok: bool, text: str):
        (hit if ok else miss).append(text)

    if model_name == "短线":
        check(last > i["ma20"] and i["vol_ratio_5d"] > 1.3, "放量突破 MA20（量比>1.3）")
        check(i["retrace_ma10"] and i["vol_ratio_5d"] < 1.1, "大涨后缩量回踩 MA10 企稳")
        check(i["big_up_recent"], "近 5 日有过 >=7% 的放量大涨")
    elif model_name == "波段":
        check(last > i["ma20"], "收盘价站上 MA20")
        check(i["ma20"] > 0 and i["chg_pct"] > 0, "MA20 拐头向上（价格在均线上方）")
        check(i["vol_ratio_5d"] > 1.0, "量能温和放大")
    elif model_name == "中线":
        check(last > i["ma60"], "收盘价站上 MA60")
        check(i["ma60"] > 0 and i["chg_pct"] > 0, "MA60 走平或向上")
        check(i["bull_alignment"], "中期均线多头排列")
    elif model_name == "长线":
        check(last > i["ma60"], "收盘价在年线（近似 MA250，用 MA60 代理）之上")
        check(i["ma60"] > 0 and i["chg_pct"] > 0, "长期均线向上")
    elif model_name == "超跌反弹":
        check(i["drawdown_60"] >= 25, f"距 60 日高点回撤 ≥25%（当前 {i['drawdown_60']}%）")
        check(i["chg_pct"] > 0, "今日收阳（止跌信号）")
        check(i["vol_ratio_5d"] >= 1.0, "今日放量（资金进场）")
    elif model_name == "右侧交易":
        check(i["bull_alignment"], "MA5>MA10>MA20 多头排列")
        check(i["vol_ratio_5d"] > 1.2, "量比>1.2，量能持续放大")
        check(last >= i["high60"] * 0.97, "接近/突破 60 日高点平台")
    else:
        miss.append("未知模型")

    return {"命中": hit, "未命中": miss}


def _suggest_price(model_name: str, i: dict) -> dict:
    """基于当前价位给出买/卖/止损参考价（机械规则，只作参考）。"""
    last = i["last"]
    if model_name in ("短线", "右侧交易"):
        buy = round(i["ma10"], 2)
        stop = round(min(last * 0.95, i["ma10"] * 0.97), 2)
        sell = round(max(last * 1.08, i["ma20"] * 1.05), 2)
    elif model_name in ("波段", "中线"):
        anchor = i["ma20"] if model_name == "波段" else i["ma60"]
        buy = round(anchor, 2)
        stop = round(min(last * 0.92, anchor * 0.95), 2)
        sell = round(last * 1.15, 2)
    elif model_name == "长线":
        buy = round(min(i["ma60"], last), 2)
        stop = round(last * 0.85, 2)
        sell = round(last * 1.30, 2)
    else:  # 超跌反弹
        buy = round(last, 2)
        stop = round(last * 0.97, 2)
        sell = round(min(i["ma10"], i["ma20"]), 2)
    return {"买点参考": buy, "卖点参考": sell, "止损参考": stop}


def decide(code: str, model_name: str) -> dict:
    """综合决策：指标 + 模型命中 + 价位建议 + 状态。"""
    out = {"ok": False, "error": "", "model": model_name, "indicators": None,
           "hit": [], "miss": [], "prices": None, "status": "等待", "cycle": "", "position": ""}
    hist = md.get_stock_hist(code, days=250)
    if hist is None or len(hist) < 20:
        out["error"] = "无法获取足够历史数据（代码可能错误或未上市）"
        return out

    i = calc_indicators(hist)
    out["indicators"] = i
    m = config.MODELS.get(model_name)
    out["cycle"] = m["cycle"]
    out["position"] = m["position"]

    r = _model_hit(model_name, i)
    out["hit"] = r["命中"]
    out["miss"] = r["未命中"]

    hit_n = len(r["命中"])
    total_n = hit_n + len(r["未命中"])
    if hit_n >= 2 and total_n >= 2 and hit_n / total_n >= 0.6:
        out["status"] = "符合入场条件"
    elif hit_n == 0:
        out["status"] = "回避（无信号，禁止逆势硬做）"
    else:
        out["status"] = "等待（条件部分满足，继续跟踪）"

    out["prices"] = _suggest_price(model_name, i)
    out["ok"] = True
    return out


# ---------------- 仓位计算 ----------------
def position_calc(total_capital: float, risk_ratio: float,
                  buy_price: float, stop_price: float,
                  tier: str | None = None) -> dict:
    """
    仓位计算器：
    - 单笔最大亏损 = 总资金 × risk_ratio
    - 每股风险 = buy_price - stop_price
    - 可买股数 = floor(单笔最大亏损 / 每股风险 / 100) × 100（整手）
    - 占用资金 / 占总资金比例，并与五档仓位校验
    """
    if buy_price <= 0 or stop_price <= 0 or buy_price <= stop_price:
        return {"error": "买入价必须大于止损价，且均为正数"}

    risk_per_share = buy_price - stop_price
    max_loss = total_capital * risk_ratio
    shares = math.floor(max_loss / risk_per_share / 100) * 100
    if shares <= 0:
        return {"error": f"按 {risk_ratio:.1%} 亏损预算与止损差 {risk_per_share:.2f} 元，连一手都买不了，建议提高预算或收紧止损"}

    cost = shares * buy_price
    ratio = cost / total_capital if total_capital else 0
    warn = ""
    if tier and tier in config.POSITION_TIERS:
        lo, hi, desc = config.POSITION_TIERS[tier]
        if ratio > hi:
            warn = f"占用 {ratio:.0%} 超出「{tier}」档上界 {hi:.0%}，请降低预算比例或换更小止损差"

    return {
        "shares": shares,
        "cost": round(cost, 2),
        "ratio": round(ratio, 4),
        "max_loss": round(max_loss, 2),
        "risk_per_share": round(risk_per_share, 3),
        "warn": warn,
    }
