# -*- coding: utf-8 -*-
"""
analysis/fundamental.py —— 基本面排雷
======================================
为中线/长线模型补充基本面验证（手册要求"行业景气 + 现金流健康"），
对候选股输出财务指标与预警标签，避免踩雷。

数据源（AkShare，24 小时缓存）：
  stock_individual_info_em(symbol)      个股基本信息（市值/行业）
  stock_financial_abstract_ths(symbol)  同花顺财务摘要（ROE/净利增速/负债率等）

预警规则（启发式，仅作排雷参考）：
  净利润同比 < 0        → 业绩下滑
  净资产收益率 < 5%     → 盈利能力弱
  资产负债率 > 70%      → 高负债
  净利润 < 0            → 亏损
  总市值 < 30 亿        → 小盘风险
  无任何预警            → 财务未见明显雷点
"""
from __future__ import annotations

import time

import pandas as pd

import akshare as ak

from data import market_data as md

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 24 * 3600  # 财务数据 24 小时缓存


def _cached(key: str, producer) -> dict | None:
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    try:
        d = producer()
        if d:
            _cache[key] = (now, d)
            return d
    except Exception:  # noqa: BLE001
        pass
    return None


def _info_em(code: str) -> dict:
    """个股基本信息（市值/行业）。东财失败时用全市场快照补市值。"""
    try:
        df = ak.stock_individual_info_em(symbol=code)
        if df is not None and not df.empty and "item" in df.columns:
            m = dict(zip(df["item"].astype(str), df["value"]))
            out = {}
            for k in ("总市值", "流通市值", "行业", "上市时间"):
                if k in m:
                    try:
                        out[k] = float(m[k]) if k in ("总市值", "流通市值") else str(m[k])
                    except Exception:  # noqa: BLE001
                        out[k] = str(m[k])
            if out:
                return out
    except Exception:  # noqa: BLE001
        pass
    # 降级：全市场快照补总市值/流通市值
    try:
        spot = md.get_all_stock_spot()
        if spot is not None and not spot.empty:
            m = spot[spot["代码"].astype(str).str.zfill(6) == code]
            if not m.empty:
                r = m.iloc[0]
                out = {}
                if "mktcap" in r.index and pd.notna(r["mktcap"]):
                    out["总市值"] = float(r["mktcap"]) * 1e4   # 快照单位为万元 → 元
                if "nmc" in r.index and pd.notna(r["nmc"]):
                    out["流通市值"] = float(r["nmc"]) * 1e4
                return out
    except Exception:  # noqa: BLE001
        pass
    return {}


def _parse(v) -> float | None:
    """解析同花顺财务字符串：'54.27%'→54.27，'1.47亿'→147000000，False→None。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace("%", "")
        if not s or s.lower() in ("false", "nan", "-"):
            return None
        mul = 1.0
        if s.endswith("亿"):
            mul, s = 1e8, s[:-1]
        elif s.endswith("万"):
            mul, s = 1e4, s[:-1]
        try:
            return float(s) * mul
        except Exception:  # noqa: BLE001
            return None
    return None


def _abstract_ths(code: str) -> dict:
    df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
    if df is None or df.empty:
        return {}
    # 报告期按时间倒序（最新在最后），取最后一期
    row = df.iloc[-1]
    out = {}
    for k in ("净利润", "净利润同比增长率", "扣非净利润同比增长率",
              "营业总收入", "营业总收入同比增长率", "净资产收益率",
              "销售毛利率", "销售净利率", "资产负债率"):
        if k in df.columns:
            v = _parse(row[k])
            out[k] = round(v, 2) if v is not None else None
    return out


# 高负债豁免：银行/保险/券商等金融股负债率高是行业特性，不视为雷点
_FINANCIAL_CODES = {
    "600000", "600015", "600016", "600036", "600908", "600919", "600926",
    "600928", "601009", "601077", "601128", "601166", "601169", "601187",
    "601288", "601328", "601398", "601528", "601577", "601658", "601665",
    "601818", "601825", "601838", "601860", "601916", "601939", "601963",
    "601988", "601995", "601997", "603323", "000001", "001227", "001236",
    "002142", "002807", "002839", "002936", "002948", "002958", "002966",
    "300033", "601688", "600030", "600837", "601788", "601211", "601881",
    "601066", "601108", "601878", "601377", "601990", "601236", "601901",
    "600999", "600958", "600109", "601375", "601162", "601696", "600906",
    "601136", "601456", "601555", "600061",
}


def _warnings(info: dict, fin: dict, code: str) -> list[str]:
    w = []
    try:
        if fin.get("净利润") is not None and float(fin["净利润"]) < 0:
            w.append("亏损（净利润为负）")
    except Exception:  # noqa: BLE001
        pass
    g = fin.get("净利润同比增长率")
    if g is not None and g < 0:
        w.append(f"业绩下滑（净利同比 {g:.1f}%）")
    roe = fin.get("净资产收益率")
    if roe is not None and roe < 5:
        w.append(f"盈利能力弱（ROE {roe:.1f}%）")
    debt = fin.get("资产负债率")
    if debt is not None and debt > 70 and code not in _FINANCIAL_CODES:
        w.append(f"高负债（负债率 {debt:.0f}%）")
    mv = info.get("总市值")
    if mv is not None and float(mv) < 30e8:
        w.append("小盘风险（总市值 < 30 亿）")
    return w


def fundamental_snapshot(code: str) -> dict:
    """返回 {info, fin, warnings, ok}。接口失败返回空字典与 ok=False。"""
    code = md.normalize_code(code)

    def producer() -> dict | None:
        info = _info_em(code)
        fin = _abstract_ths(code)
        if not info and not fin:
            return None
        return {"info": info, "fin": fin,
                "warnings": _warnings(info, fin, code), "ok": True}

    r = _cached(f"fund:{code}", producer)
    if r is None:
        return {"info": {}, "fin": {}, "warnings": [], "ok": False}
    return r
