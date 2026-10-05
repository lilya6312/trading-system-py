# -*- coding: utf-8 -*-
"""
analysis/watchlist.py —— 自选股池存储
========================================
自选股以 JSON 持久化到 data/watchlist.json（相对项目根目录），
添加时自动从全市场快照补名称；行情展示时与全市场快照合并实时数据。
"""
from __future__ import annotations

import json
import os
from datetime import date

import pandas as pd

from data import market_data as md

WATCH_FIELDS = ["code", "name", "added_date", "note"]


def _path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "watchlist.json")


def load_watchlist() -> pd.DataFrame:
    p = _path()
    if not os.path.exists(p):
        return pd.DataFrame(columns=WATCH_FIELDS)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        df = pd.DataFrame(data, columns=WATCH_FIELDS)
        return df if not df.empty else pd.DataFrame(columns=WATCH_FIELDS)
    except Exception:
        return pd.DataFrame(columns=WATCH_FIELDS)


def _save(df: pd.DataFrame) -> None:
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(df.to_dict("records"), f, ensure_ascii=False, indent=2)


def _fetch_name(code: str) -> str:
    """从全市场快照自动补名称，取不到返回空串。"""
    try:
        spot = md.get_all_stock_spot()
        if spot is None or spot.empty:
            return ""
        m = spot[spot["代码"].astype(str).str.zfill(6) == code]
        return str(m.iloc[0]["名称"]) if not m.empty else ""
    except Exception:
        return ""


def add_watch(code: str, note: str = "") -> tuple[bool, str]:
    """添加自选股（自动补名称、自动去重）。返回 (是否成功, 提示)。"""
    code = md.normalize_code(code)
    if not code.isdigit() or len(code) != 6:
        return False, "代码格式应为 6 位数字"
    df = load_watchlist()
    if not df.empty and (df["code"].astype(str) == code).any():
        return False, f"{code} 已在自选股池中"
    name = _fetch_name(code)
    row = pd.DataFrame([{"code": code, "name": name, "added_date": str(date.today()), "note": note}],
                       columns=WATCH_FIELDS)
    _save(pd.concat([df, row], ignore_index=True))
    return True, f"已加入自选股：{code} {name}"


def remove_watch(code: str) -> tuple[bool, str]:
    df = load_watchlist()
    if df.empty:
        return False, "自选股池为空"
    before = len(df)
    df = df[df["code"].astype(str) != code]
    if len(df) == before:
        return False, f"{code} 不在自选股池中"
    _save(df.reset_index(drop=True))
    return True, f"已删除 {code}"


def watch_quotes() -> pd.DataFrame:
    """自选股实时行情表：合并全市场快照，取不到行情的标标注为数据缺失。"""
    df = load_watchlist()
    if df.empty:
        return df
    try:
        spot = md.get_all_stock_spot()
    except Exception:
        spot = None

    if spot is not None and not spot.empty:
        spot2 = spot.copy()
        spot2["code"] = spot2["代码"].astype(str).str.zfill(6)
        keep = ["code", "最新价", "涨跌幅", "成交量", "成交额", "换手率"]
        keep = [c for c in keep if c in spot2.columns]
        df = df.merge(spot2[keep], on="code", how="left")
        df["最新价"] = df["最新价"].astype(float).round(2)
        df["涨跌幅"] = df["涨跌幅"].astype(float).round(2)
        df["换手率"] = df["换手率"].astype(float).round(2)
        df["成交额(亿)"] = (df["成交额"].astype(float) / 1e8).round(2)
    else:
        df["最新价"] = pd.NA
        df["涨跌幅"] = pd.NA
        df["换手率"] = pd.NA
        df["成交额(亿)"] = pd.NA
    return df
