# -*- coding: utf-8 -*-
"""
analysis/signal_scan.py —— 盘后信号扫描
========================================
对"自选股池 + 强主线板块成分股 + 用户额外代码"自动跑全部六大模型，
输出今日信号清单（含大盘阶段约束），是决策页的核心升级：
从"手动单股查询"变为"一键扫描全池"。

输出字段：代码 / 名称 / 模型 / 状态 / 命中 / 未命中 / 买点 / 卖点 / 止损 / 建议仓位
性能：并发拉取历史（缓存命中后极快），每只股票指标只算一次。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

import config
from analysis import decision, mainline
from analysis.stock import calc_indicators
from data import market_data as md

_MODEL_ORDER = ["短线", "波段", "中线", "长线", "超跌反弹", "右侧交易"]


def _pool_codes(extra_codes: list[str] | None = None, top_strong: int = 4) -> dict:
    """收集代码池：{code: name}。自选股优先，再补强主线成分股。"""
    pool: dict[str, str] = {}
    # 1) 自选股池
    try:
        from analysis.watchlist import load_watchlist
        wl = load_watchlist()
        if not wl.empty:
            for _, r in wl.iterrows():
                pool[str(r["code"]).zfill(6)] = str(r.get("name", ""))
    except Exception:  # noqa: BLE001
        pass
    # 2) 强主线成分股（补漏，去重）
    try:
        ml = mainline.mainline_ranking(top_n=top_strong)
        for ind in ml.get("strong", []):
            cons = md.get_industry_cons(ind)
            if cons is None or cons.empty:
                continue
            for _, r in cons.head(30).iterrows():
                code = str(r["代码"]).zfill(6)
                pool.setdefault(code, str(r.get("名称", "")))
    except Exception:  # noqa: BLE001
        pass
    # 3) 用户额外代码
    for c in (extra_codes or []):
        code = md.normalize_code(c)
        if code and code.isdigit() and len(code) == 6:
            pool.setdefault(code, "")
    return pool


def _scan_one(code: str, name: str, phase: str | None) -> list[dict]:
    """单只股票跑全部模型，返回信号列表（仅保留非'回避（无信号）'）。"""
    try:
        hist = md.get_stock_hist(code, days=250)
        if hist is None or len(hist) < 20:
            return []
        i = calc_indicators(hist)
    except Exception:  # noqa: BLE001
        return []

    out = []
    for m_name in _MODEL_ORDER:
        r = decision._model_hit(m_name, i)
        prices = decision._suggest_price(m_name, i)
        hit_n = len(r["命中"])
        total_n = hit_n + len(r["未命中"])

        env_block = None
        if phase in ("弱势", "冰点") and m_name in ("短线", "右侧交易"):
            env_block = f"大盘{phase}禁止{['短线','右侧交易'][0]}"

        if env_block:
            status = "回避（大盘环境不允许）"
        elif hit_n >= 2 and total_n >= 2 and hit_n / total_n >= 0.6:
            status = "符合入场条件"
        elif hit_n == 0:
            continue  # 无信号直接跳过
        else:
            status = "等待"

        m = config.MODELS.get(m_name, {})
        out.append({
            "代码": code, "名称": name, "模型": m_name,
            "状态": status, "命中": "；".join(r["命中"]) or "-",
            "未命中": "；".join(r["未命中"]) or "-",
            "买点": prices.get("买点参考"), "卖点": prices.get("卖点参考"),
            "止损": prices.get("止损参考"),
            "建议仓位": m.get("position", ""),
            "信号强度": round(hit_n / total_n * 100, 0) if total_n else 0,
        })
    # 一只票只套一个模型（铁律四）：保留状态最优的 1 条；同状态按信号强度
    best = None
    for s in out:
        if best is None:
            best = s
            continue
        prio = {"符合入场条件": 0, "等待": 1, "回避（大盘环境不允许）": 2}
        if prio.get(s["状态"], 3) < prio.get(best["状态"], 3):
            best = s
        elif prio.get(s["状态"], 3) == prio.get(best["状态"], 3) and s["信号强度"] > best["信号强度"]:
            best = s
    return [best] if best is not None else []


def scan_signals(phase: str | None = None, extra_codes: list[str] | None = None,
                 max_workers: int = 8) -> dict:
    """
    扫描全池，返回：
    - table: 信号清单（符合 > 等待；同状态按信号强度排序）
    - ready: 符合入场条件的条数
    - waiting: 等待中的条数
    - blocked: 被大盘环境封禁的条数
    - errors: 提示信息
    """
    out = {"table": None, "ready": 0, "waiting": 0, "blocked": 0,
           "pool_size": 0, "errors": []}
    pool = _pool_codes(extra_codes)
    if not pool:
        out["errors"].append("代码池为空：请先添加自选股，或等主线识别出强主线")
        return out
    out["pool_size"] = len(pool)

    rows = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_scan_one, c, n, phase): c for c, n in pool.items()}
        for f in as_completed(futs):
            try:
                rows.extend(f.result())
            except Exception:  # noqa: BLE001
                continue

    if not rows:
        out["errors"].append("扫描完成但未产生任何信号")
        return out

    df = pd.DataFrame(rows)
    # 排序：符合 > 等待 > 回避；同状态按信号强度降序
    order = {"符合入场条件": 0, "等待": 1, "回避（大盘环境不允许）": 2}
    df["_o"] = df["状态"].map(order).fillna(3)
    df = df.sort_values(["_o", "信号强度"], ascending=[True, False]).drop(columns="_o")
    df = df.reset_index(drop=True)

    out["table"] = df
    out["ready"] = int((df["状态"] == "符合入场条件").sum())
    out["waiting"] = int((df["状态"] == "等待").sum())
    out["blocked"] = int((df["状态"] == "回避（大盘环境不允许）").sum())
    return out
