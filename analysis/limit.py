# -*- coding: utf-8 -*-
"""
analysis/limit.py —— 精确涨跌停判定
=====================================
按上市板块与 ST 状态精确判定个股涨跌停阈值，替代 config.LIMIT_UP_RATIO 的统一近似。
规则（2025 年口径）：
  主板（60x/00x）           10%
  创业板（300/301）/ 科创板（688/689） 20%
  北交所（8x/4x/920）       30%
  ST / *ST                  5%（涨跌幅限制 5%）
涨停判定带 0.3 个百分点的容差（涨停价按前收四舍五入到分，实际涨幅可能略低于名义阈值）。
"""
from __future__ import annotations

import pandas as pd

_TOL = 0.3  # 涨停价四舍五入到分导致的容差（百分点）


def limit_ratio(code: str, name: str = "") -> float:
    """返回个股涨跌幅限制比例（如 0.10）。"""
    c = str(code).strip().lower()
    for p in ("sh", "sz", "bj"):
        c = c.replace(p, "")
    c = c.zfill(6)

    nm = str(name or "").upper()
    if "ST" in nm:                      # ST / *ST
        return 0.05
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    if c.startswith(("8", "4", "92")):
        return 0.30
    return 0.10


def is_limit_up(pct: float, code: str = "", name: str = "") -> bool:
    """涨幅 pct（%）是否达到涨停。pct 可为 None/NaN。"""
    if pct is None or pd.isna(pct):
        return False
    return float(pct) >= limit_ratio(code, name) * 100 - _TOL


def is_limit_down(pct: float, code: str = "", name: str = "") -> bool:
    """跌幅 pct（%）是否达到跌停。"""
    if pct is None or pd.isna(pct):
        return False
    return float(pct) <= -(limit_ratio(code, name) * 100 - _TOL)


def count_limit(df: pd.DataFrame, up: bool = True) -> int:
    """对全市场快照按行统计涨停/跌停家数（精确阈值，按个股板块判断）。
    df 必须含 代码/名称/涨跌幅 三列。
    """
    if df is None or df.empty:
        return 0
    n = 0
    for _, r in df.iterrows():
        pct = pd.to_numeric(r.get("涨跌幅"), errors="coerce")
        code = str(r.get("代码", "")).zfill(6)
        name = str(r.get("名称", ""))
        if up and is_limit_up(pct, code, name):
            n += 1
        elif not up and is_limit_down(pct, code, name):
            n += 1
    return n


def limit_up_names(df: pd.DataFrame) -> list[str]:
    """返回涨停股名称列表（用于页面展示）。"""
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.iterrows():
        pct = pd.to_numeric(r.get("涨跌幅"), errors="coerce")
        code = str(r.get("代码", "")).zfill(6)
        name = str(r.get("名称", ""))
        if is_limit_up(pct, code, name):
            out.append(str(name))
    return out
