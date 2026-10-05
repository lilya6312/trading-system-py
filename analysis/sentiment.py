# -*- coding: utf-8 -*-
"""
analysis/sentiment.py —— 情绪面指标（赚钱效应）
================================================
判断"冰点 / 退潮 / 回暖"的量化核心，供超跌反弹买点与空仓决策参考。

数据源（AkShare 东财，失败自动降级到全市场快照精确判定）：
  stock_zt_pool_em(date)         涨停池（含连板数/涨停原因）
  stock_zt_pool_zbgc_em(date)    炸板池
  stock_zt_pool_dtgc_em(date)    跌停池
  stock_zt_pool_previous_em()    昨日涨停股今日表现（打板溢价）

输出指标：
  涨停家数 / 跌停家数 / 最高连板 / 连板梯队(2板,3板+,5板+) / 炸板率 /
  昨日涨停今平均涨幅(打板溢价) / 红盘率 / 晋级率 / 情绪评分(0-100)
"""
from __future__ import annotations

import time

import pandas as pd

import akshare as ak

import config
from analysis import limit
from data import market_data as md


def _today() -> str:
    return time.strftime("%Y%m%d")


def _prev_trade_date() -> str | None:
    """最近一个交易日（< 今天），失败返回 None。"""
    try:
        cal = ak.tool_trade_date_hist_sina()
        today = pd.Timestamp(_today())
        prev = cal[cal["trade_date"] < today]["trade_date"]
        if not prev.empty:
            return str(prev.iloc[-1].date()).replace("-", "")
    except Exception:  # noqa: BLE001
        pass
    # 降级：用上证指数日线的倒数第二个交易日（最近交易日的前一个）
    try:
        daily = md.get_index_daily("sh000001", days=30)
        if daily is not None and len(daily) >= 2:
            return str(pd.Timestamp(daily["date"].iloc[-2]).date()).replace("-", "")
    except Exception:  # noqa: BLE001
        pass
    return None


def _prev_zt() -> pd.DataFrame | None:
    """昨日涨停股今日表现；主接口失败时用昨日涨停池+今日快照降级。"""
    try:
        df = ak.stock_zt_pool_previous_em()
        if df is not None and not df.empty:
            return df
    except Exception:  # noqa: BLE001
        pass
    # 降级：昨日涨停池 + 今日全市场快照
    prev_date = _prev_trade_date()
    if not prev_date:
        return None
    try:
        yz = ak.stock_zt_pool_em(date=prev_date)
        if yz is None or yz.empty:
            return None
        spot = md.get_all_stock_spot()
        if spot is None or spot.empty:
            return None
        codes = set(yz["代码"].astype(str).str.zfill(6))
        s2 = spot.copy()
        s2["代码"] = s2["代码"].astype(str).str.zfill(6)
        sub = s2[s2["代码"].isin(codes)].copy()
        if sub.empty:
            return None
        sub["是否连板"] = pd.to_numeric(sub["涨跌幅"], errors="coerce") >= 9.5
        return sub[["代码", "名称", "涨跌幅", "是否连板"]]
    except Exception:  # noqa: BLE001
        return None


def _zt_pool(date: str | None = None) -> pd.DataFrame | None:
    try:
        return ak.stock_zt_pool_em(date=date or _today())
    except Exception:  # noqa: BLE001
        try:
            return ak.stock_zt_pool_em()
        except Exception:  # noqa: BLE001
            return None


def _zbgc_pool(date: str | None = None) -> pd.DataFrame | None:
    try:
        return ak.stock_zt_pool_zbgc_em(date=date or _today())
    except Exception:  # noqa: BLE001
        try:
            return ak.stock_zt_pool_zbgc_em()
        except Exception:  # noqa: BLE001
            return None


def _dtgc_pool(date: str | None = None) -> pd.DataFrame | None:
    try:
        return ak.stock_zt_pool_dtgc_em(date=date or _today())
    except Exception:  # noqa: BLE001
        try:
            return ak.stock_zt_pool_dtgc_em()
        except Exception:  # noqa: BLE001
            return None


def _num(df: pd.DataFrame, col: str, default=0.0) -> float:
    s = pd.to_numeric(df[col], errors="coerce")
    return float(s.mean()) if s.notna().any() else default


def _score(s: dict) -> int:
    """简易情绪评分 0-100：涨停多、连板高、炸板少、溢价正 → 高分（赚钱效应好）。"""
    sc = 0.0
    zt = s.get("涨停家数") or 0
    lb = s.get("最高连板") or 0
    zb = s.get("炸板率")
    prem = s.get("昨日涨停今平均涨幅")
    sc += min(25, zt / 4)                       # 涨停 >=100 得满分 25
    sc += min(25, lb * 5)                       # 连板高度 >=5 得满分 25
    if zb is not None:
        sc += max(0, 25 - zb * 1.5)             # 炸板率 0% 得 25，>16% 归零
    if prem is not None:
        sc += max(0, min(25, 10 + prem * 4))    # 溢价 >3.75% 得满分
    else:
        sc += 12.5
    return int(round(sc))


def sentiment_snapshot(force: bool = False) -> dict:
    """汇总情绪面快照；任一数据源失败时对应字段置 None，页面标注。
    结果缓存 10 分钟（TTL），页面 rerun 不再重复拉涨停池/炸板池等接口。"""
    now = time.time()
    hit = _snap_cache.get("snapshot")
    if hit and now - hit[0] < _SNAP_TTL and not force:
        return hit[1]

    out = {
        "涨停家数": None, "跌停家数": None,
        "最高连板": None, "二板": None, "三板以上": None, "五板以上": None,
        "炸板家数": None, "炸板率": None,
        "昨日涨停今平均涨幅": None, "红盘率": None, "晋级率": None,
        "情绪评分": None, "date": None, "errors": [],
    }

    zt = _zt_pool()
    if zt is not None and not zt.empty:
        out["date"] = str(zt.iloc[0].get("日期", "") or "")
        out["涨停家数"] = int(len(zt))
        if "连板数" in zt.columns:
            lb = pd.to_numeric(zt["连板数"], errors="coerce").fillna(0)
            out["最高连板"] = int(lb.max())
            out["二板"] = int((lb >= 2).sum())
            out["三板以上"] = int((lb >= 3).sum())
            out["五板以上"] = int((lb >= 5).sum())
        out["涨停股"] = zt[["代码", "名称"]].to_dict("records")
    else:
        out["errors"].append("涨停池接口不可达，改用快照近似")

    zb = _zbgc_pool()
    if zb is not None and not zb.empty:
        out["炸板家数"] = int(len(zb))
        zt_n = out["涨停家数"] or 0
        total = len(zb) + zt_n
        if total:
            out["炸板率"] = round(len(zb) / total * 100, 1)
    else:
        out["errors"].append("炸板池接口不可达")

    dt = _dtgc_pool()
    if dt is not None and not dt.empty:
        out["跌停家数"] = int(len(dt))
    else:
        out["errors"].append("跌停池接口不可达，改用快照近似")

    prev = _prev_zt()
    if prev is not None and not prev.empty:
        chg = pd.to_numeric(prev["涨跌幅"], errors="coerce")
        if chg.notna().any():
            out["昨日涨停今平均涨幅"] = round(float(chg.mean()), 2)
            out["红盘率"] = round(float((chg > 0).mean()) * 100, 1)
        if "是否连板" in prev.columns:
            lb = pd.to_numeric(prev["是否连板"], errors="coerce")
            out["晋级率"] = round(float((lb == 1).sum()) / len(prev) * 100, 1) if len(prev) else None
    else:
        out["errors"].append("昨日涨停表现接口不可达")

    # ---- 降级补全：全市场快照精确判定涨停/跌停 ----
    if out["涨停家数"] is None or out["跌停家数"] is None:
        try:
            spot = md.get_all_stock_spot()
            if spot is not None and not spot.empty:
                if out["涨停家数"] is None:
                    out["涨停家数"] = limit.count_limit(spot, up=True)
                if out["跌停家数"] is None:
                    out["跌停家数"] = limit.count_limit(spot, up=False)
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"降级统计失败: {e}")

    out["情绪评分"] = _score(out)
    _snap_cache["snapshot"] = (now, out)
    return out


# 情绪面快照缓存（TTL 10 分钟）
_snap_cache: dict[str, tuple[float, dict]] = {}
_SNAP_TTL = 600
