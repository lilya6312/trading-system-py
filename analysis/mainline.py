# -*- coding: utf-8 -*-
"""
analysis/mainline.py —— 主线识别（增强版）
==========================================
输入：行业板块行情 + 板块成分股 + 全市场快照 + 板块指数历史（东财/同花顺双源）+ 涨停池
输出：主线候选排行（含多周期 RPS 与生命周期阶段）。

新增能力（v2）：
  1) 多周期 RPS：板块 3/5/10 日累计涨幅排名 + 相对大盘强弱（RS），过滤"一日游"
     板块历史接口不可达时，用成分股 60 日涨幅中位数作持续性代理
  2) 生命周期四阶段：启动 / 发酵 / 高潮 / 退潮（板块指数位置 + 板块内连板梯队）
  3) 评分升级：当日强度 25% + 涨停 20% + 上涨占比 15% + 容量 10% + 持续性 30%
  4) 连板梯队：按板块成分股代码匹配涨停池，解决行业名称口径不一致

数据源失败时对应字段置空并在页面标注，不阻塞其余部分。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

import akshare as ak

from analysis import sentiment, limit
from analysis.market import ma
from data import market_data as md
import config

_TOP_SCAN = 10   # 对涨幅前 N 板块做精确统计
_HIST_DAYS = 60  # 板块指数历史长度

# 东财宽行业名 → 同花顺行业名（同花顺接口仅认细分行业名，缺失时拉不到历史）
_THS_ALIAS = {
    "医药生物": "医药商业", "食品饮料": "食品加工制造", "汽车": "汽车整车",
    "美容护理": "美容护理", "银行": "银行", "房地产": "房地产",
    "公用事业": "电力", "交通运输": "公路铁路运输", "农林牧渔": "种植业与林业",
    "电力设备": "电网设备", "有色金属": "工业金属", "电子": "消费电子",
    "计算机": "软件开发", "通信": "通信设备", "传媒": "文化传媒",
    "国防军工": "军工装备", "机械设备": "通用设备", "基础化工": "化学制品",
    "钢铁": "钢铁", "煤炭": "煤炭开采加工", "石油石化": "石油加工贸易",
    "建筑装饰": "建筑装饰", "建筑材料": "建筑材料", "环保": "环境治理",
    "商贸零售": "零售", "社会服务": "旅游及酒店", "家用电器": "白色家电",
    "纺织服饰": "服装家纺", "轻工制造": "家居用品", "综合": "综合",
    "非银金融": "证券",
}


# ---------------- 板块指数历史（东财 → 同花顺 双源） ----------------
_hist_cache: dict[str, tuple[float, pd.DataFrame | None]] = {}


def get_board_hist(industry: str, days: int = _HIST_DAYS) -> pd.DataFrame | None:
    """板块指数日线。东财失败自动切同花顺；1 小时缓存。"""
    key = f"bh:{industry}"
    now = time.time()
    hit = _hist_cache.get(key)
    if hit and now - hit[0] < 3600:
        return hit[1]

    end = datetime.now()
    start = end - timedelta(days=days + 40)
    df = None
    # 源 1：东财
    try:
        df = ak.stock_board_industry_hist_em(
            symbol=industry, period="日k",
            start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"), adjust="")
    except Exception:  # noqa: BLE001
        df = None
    # 源 2：同花顺（细分行业名，需映射；字段：日期/收盘价）
    if df is None or df.empty:
        ths_name = _THS_ALIAS.get(industry, industry)
        try:
            df = ak.stock_board_industry_index_ths(
                symbol=ths_name,
                start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
        except Exception:  # noqa: BLE001
            df = None

    if df is not None and not df.empty:
        date_col = "日期" if "日期" in df.columns else df.columns[0]
        close_col = "收盘" if "收盘" in df.columns else ("收盘价" if "收盘价" in df.columns else None)
        if close_col is None:
            return None
        df = df.rename(columns={close_col: "收盘", date_col: "日期"})
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.tail(days).copy()
        _hist_cache[key] = (now, df)
        return df
    return None


def _board_periods(hist: pd.DataFrame) -> dict:
    """由板块历史计算多周期涨幅与位置指标。"""
    close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
    if len(close) < 6:
        return {}
    last = float(close.iloc[-1])

    def ret(n: int) -> float | None:
        if len(close) <= n:
            return None
        base = float(close.iloc[-1 - n])
        return round((last / base - 1) * 100, 2) if base else None

    ma5 = float(ma(close, 5).iloc[-1]) if len(close) >= 5 else last
    ma10 = float(ma(close, 10).iloc[-1]) if len(close) >= 10 else last
    ma20 = float(ma(close, 20).iloc[-1]) if len(close) >= 20 else last
    high20 = float(close.tail(20).max()) if len(close) >= 5 else last
    dd20 = round((high20 - last) / high20 * 100, 2) if high20 else 0.0

    out = {
        "涨3日": ret(3), "涨5日": ret(5), "涨10日": ret(10),
        "站上MA5": last > ma5, "站上MA10": last > ma10, "站上MA20": last > ma20,
        "距20日高点%": dd20,
    }
    out.update(_streak_10d(hist))
    return out


def _streak_10d(hist: pd.DataFrame) -> dict:
    """
    板块近 10 个交易日强度序列统计（主线强度核心）：
      - 10日阳线率：10 日中上涨天数占比（持续性）
      - 10日日均涨幅：平均每日涨跌幅（绝对动能）
      - 强度趋势：近 3 日日均涨幅 vs 前 7 日日均涨幅 → 增强/持平/减弱
    """
    close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
    if len(close) < 11:
        return {}
    chg = close.pct_change() * 100
    c = chg.tail(10).dropna()
    if len(c) < 10:
        return {}
    up_days = int((c > 0).sum())
    avg10 = float(c.mean())
    recent3 = float(c.tail(3).mean())
    prior7 = float(c.head(7).mean())
    if recent3 > prior7 + 0.15:
        trend = "增强"
    elif recent3 < prior7 - 0.15:
        trend = "减弱"
    else:
        trend = "持平"
    return {
        "10日阳线率": round(up_days / 10 * 100),
        "10日日均涨幅": round(avg10, 2),
        "强度趋势": trend,
    }


def _index_10d_ret() -> float | None:
    """上证指数近 10 日涨幅，用于相对强弱。"""
    try:
        daily = md.get_index_daily("sh000001", days=30)
        if daily is not None and len(daily) > 10:
            c = pd.to_numeric(daily["close"], errors="coerce")
            base = float(c.iloc[-11])
            return round((float(c.iloc[-1]) / base - 1) * 100, 2) if base else None
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------- 板块内连板梯队（成分股匹配涨停池） ----------------
def _zt_stats_for_codes(codes: set[str]) -> tuple[int, int]:
    """返回 (板块内涨停家数, 最高连板)。涨停池按成分股代码匹配，避免行业名称口径不一致。"""
    try:
        zt = sentiment._zt_pool()
    except Exception:  # noqa: BLE001
        zt = None
    if zt is None or zt.empty or not codes:
        return 0, 0
    sub = zt[zt["代码"].astype(str).str.zfill(6).isin(codes)]
    if sub.empty:
        return 0, 0
    lb = pd.to_numeric(sub.get("连板数", 0), errors="coerce").fillna(0)
    return int(len(sub)), int(lb.max()) if len(lb) else 0


# ---------------- 生命周期判定 ----------------
def _lifecycle(hist: pd.DataFrame, zt_n: int, max_lb: int) -> str:
    """四阶段判定（数据不足返回'数据不足'）。"""
    if hist is None or len(hist) < 20:
        return "数据不足"
    close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
    vol = pd.to_numeric(hist.get("成交量", hist.get("成交额")), errors="coerce").dropna()
    last = float(close.iloc[-1])
    ma5 = float(ma(close, 5).iloc[-1])
    ma10 = float(ma(close, 10).iloc[-1])
    ma20 = float(ma(close, 20).iloc[-1])
    high20 = float(close.tail(20).max())
    dd20 = (high20 - last) / high20 * 100 if high20 else 0.0
    v5 = float(vol.tail(5).mean()) if len(vol) >= 5 else float(vol.iloc[-1])
    vol_ratio = float(vol.iloc[-1]) / v5 if v5 else 1.0

    bull = ma5 > ma10 > ma20
    # 退潮：跌破 MA10 且非多头，或明显回撤
    if (last < ma10 and not bull) or dd20 > 8:
        return "退潮"
    # 高潮：连板高度 >= 6，或贴顶放巨量
    if max_lb >= 6 or (dd20 < 3 and vol_ratio > 1.8):
        return "高潮"
    # 发酵：多头排列 + 连板梯队 + 涨停 3 家以上
    if bull and max_lb >= 3 and zt_n >= 3:
        return "发酵"
    # 启动：站上 MA20 / 出现涨停
    if last > ma20 and zt_n >= 1:
        return "启动"
    return "数据不足"


# ---------------- 板块内部统计（成分股） ----------------
def _board_internal_stats(industry: str, spot: pd.DataFrame) -> dict:
    try:
        cons = md.get_industry_cons(industry)
    except Exception:  # noqa: BLE001
        cons = None
    if cons is None or cons.empty:
        return {"总数": 0, "涨停": 0, "上涨占比": 0.0, "codes": set(), "中位60日": None}

    codes = set(cons["代码"].astype(str).str.zfill(6))
    sub = spot[spot["代码"].isin(codes)].copy() if spot is not None and not spot.empty else pd.DataFrame()
    if sub.empty:
        return {"总数": len(codes), "涨停": 0, "上涨占比": 0.0, "codes": codes, "中位60日": None}

    chg = pd.to_numeric(sub["涨跌幅"], errors="coerce")
    limit_n = sum(1 for _, r in sub.iterrows()
                  if limit.is_limit_up(pd.to_numeric(r.get("涨跌幅"), errors="coerce"),
                                       str(r.get("代码", "")), str(r.get("名称", ""))))
    up_n = int((chg > 0).sum())
    ratio = up_n / len(chg) if len(chg) else 0.0
    # 成分股 60 日涨幅中位数（持续性代理）
    med60 = None
    if "60日涨跌幅" in sub.columns:
        s = pd.to_numeric(sub["60日涨跌幅"], errors="coerce")
        if s.notna().any():
            med60 = float(s.median())
    return {"总数": len(chg), "涨停": limit_n, "上涨占比": round(ratio, 3),
            "codes": codes, "中位60日": med60}


# ---------------- 主线评分主流程 ----------------
_rank_cache: dict[str, tuple[float, dict]] = {}
_RANK_TTL = 600  # 主线识别结果缓存 10 分钟


def mainline_ranking(top_n: int = 6, force: bool = False) -> dict:
    out = {"ranking": None, "strong": [], "errors": []}

    now = time.time()
    hit = _rank_cache.get("rank")
    if hit and now - hit[0] < _RANK_TTL and not force:
        return hit[1]

    try:
        ind = md.get_industry_spot()
        if ind is None or ind.empty:
            out["errors"].append("行业板块行情无数据（东财/腾讯均不可达）")
            return out
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"行业板块行情获取失败: {e}")
        return out

    try:
        spot = md.get_all_stock_spot()
    except Exception:  # noqa: BLE001
        spot = None

    df = ind.copy()
    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce").fillna(0)
    df["涨幅分"] = df["涨跌幅"].rank(pct=True)
    df["容量分"] = pd.to_numeric(df["总市值"], errors="coerce").rank(pct=True).fillna(0.5)

    cand = df.sort_values("涨幅分", ascending=False).head(_TOP_SCAN).copy()
    cand_names = [str(r["板块名称"]) for _, r in cand.iterrows()]

    # 并发：板块内部统计 + 板块历史
    with ThreadPoolExecutor(max_workers=6) as ex:
        fut_stats = {ex.submit(_board_internal_stats, nm, spot): nm for nm in cand_names}
        fut_hist = {ex.submit(get_board_hist, nm): nm for nm in cand_names}
        stats = {fut_stats[f].result() if f in fut_stats else None: fut_stats[f]
                 for f in fut_stats} if False else {}
        stats = {}
        for f in as_completed(fut_stats):
            stats[fut_stats[f]] = f.result()
        hists = {}
        for f in as_completed(fut_hist):
            hists[fut_hist[f]] = f.result()

    df["涨停家数"] = df["板块名称"].map(lambda x: stats.get(x, {}).get("涨停", 0))
    df["上涨占比"] = df["板块名称"].map(lambda x: stats.get(x, {}).get("上涨占比", 0.0))
    df["板块股票数"] = df["板块名称"].map(lambda x: stats.get(x, {}).get("总数", 0))
    df["中位60日涨幅%"] = df["板块名称"].map(lambda x: stats.get(x, {}).get("中位60日"))

    # 连板梯队（成分股匹配涨停池）
    zt_n_lb = {}
    for nm in cand_names:
        zt_n_lb[nm] = _zt_stats_for_codes(stats.get(nm, {}).get("codes", set()))
    df["最高连板"] = df["板块名称"].map(lambda x: zt_n_lb.get(x, (0, 0))[1])

    # 板块历史、多周期与生命周期
    idx_10d = _index_10d_ret()
    periods = {}
    lifecycles = {}
    hist_ok = 0
    for nm in cand_names:
        hist = hists.get(nm)
        p = _board_periods(hist) if hist is not None else {}
        if p:
            hist_ok += 1
        if idx_10d is not None and p.get("涨10日") is not None:
            p["近10日RS"] = round(p["涨10日"] - idx_10d, 2)
        periods[nm] = p
        lifecycles[nm] = _lifecycle(hist, zt_n_lb[nm][0], zt_n_lb[nm][1])

    df["涨3日"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("涨3日"))
    df["涨5日"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("涨5日"))
    df["涨10日"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("涨10日"))
    df["近10日RS"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("近10日RS"))
    df["距20日高点%"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("距20日高点%"))
    df["站上MA10"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("站上MA10"))
    df["10日阳线率"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("10日阳线率"))
    df["10日日均涨幅"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("10日日均涨幅"))
    df["强度趋势"] = df["板块名称"].map(lambda x: periods.get(x, {}).get("强度趋势"))
    df["生命周期"] = df["板块名称"].map(lambda x: lifecycles.get(x, "数据不足"))
    if hist_ok == 0:
        out["errors"].append("板块历史接口不可达，RPS/生命周期用成分股 60 日涨幅近似")

    # 评分：25%当日 + 20%涨停 + 15%上涨占比 + 10%容量 + 30%持续性
    max_zt = df["涨停家数"].max()
    zt_part = (df["涨停家数"] / max_zt).fillna(0) if max_zt else 0
    # 持续性：优先 5/10 日 RPS + RS；历史不可得时用成分股 60 日中位数
    df["涨5日分"] = pd.to_numeric(df["涨5日"], errors="coerce").rank(pct=True).fillna(0.5)
    df["涨10日分"] = pd.to_numeric(df["涨10日"], errors="coerce").rank(pct=True).fillna(0.5)
    df["RS分"] = pd.to_numeric(df["近10日RS"], errors="coerce").rank(pct=True).fillna(0.5)
    med60 = pd.to_numeric(df["中位60日涨幅%"], errors="coerce")
    if med60.notna().any():
        med60_part = med60.rank(pct=True).fillna(0.5)
        df["持续性分"] = ((df["涨5日分"] + df["涨10日分"] + df["RS分"]) / 3 * 0.6
                          + med60_part * 0.4)
    else:
        df["持续性分"] = (df["涨5日分"] + df["涨10日分"] + df["RS分"]) / 3
    df["主线评分"] = (
        25 * df["涨幅分"] + 20 * zt_part + 15 * df["上涨占比"]
        + 10 * df["容量分"] + 30 * df["持续性分"]).round(1)

    show_cols = ["板块名称", "涨跌幅", "总市值", "换手率", "领涨股票",
                 "领涨股票-涨跌幅", "板块股票数", "涨停家数", "最高连板",
                 "上涨占比", "涨3日", "涨5日", "涨10日", "近10日RS",
                 "10日阳线率", "10日日均涨幅", "强度趋势",
                 "中位60日涨幅%", "距20日高点%", "站上MA10", "生命周期", "主线评分"]
    show_cols = [c for c in show_cols if c in df.columns]

    top = df.sort_values("主线评分", ascending=False).head(top_n).copy()
    top["排名"] = range(1, len(top) + 1)
    top["总市值"] = (pd.to_numeric(top["总市值"], errors="coerce") / 1e8).round(1)
    top["换手率"] = pd.to_numeric(top["换手率"], errors="coerce").round(2)
    top["上涨占比"] = (pd.to_numeric(top["上涨占比"], errors="coerce") * 100).round(1)

    out["ranking"] = top[["排名"] + show_cols].reset_index(drop=True)

    # 强主线：涨停家数 >= 2 或领涨股近涨停，且生命周期非退潮/数据不足
    for _, r in top.iterrows():
        lead_chg = pd.to_numeric(r.get("领涨股票-涨跌幅"), errors="coerce") or 0
        life = str(r.get("生命周期", ""))
        if (r["涨停家数"] >= 2 or lead_chg >= 9.5) and life not in ("退潮", "数据不足"):
            out["strong"].append(str(r["板块名称"]))
    _rank_cache["rank"] = (now, out)
    return out


def stock_in_line(code: str) -> dict | None:
    """
    个股所属主线反查：在强主线板块（含候选 top8）成分股中匹配该个股，
    命中则返回所属板块与强度信息（生命周期/涨10日/强度趋势/主线评分），否则 None。
    用于"个股搜索分析"展示"个股属于哪条主线、这条线现在强不强"。
    """
    code = str(code).zfill(6)
    try:
        ml = mainline_ranking(top_n=8)
        ranking = ml.get("ranking")
        if ranking is None or ranking.empty:
            return None
        for _, r in ranking.iterrows():
            nm = str(r["板块名称"])
            try:
                cons = md.get_industry_cons(nm)
            except Exception:  # noqa: BLE001
                cons = None
            if cons is None or cons.empty:
                continue
            if code in set(cons["代码"].astype(str).str.zfill(6)):
                return {
                    "所属行业": nm,
                    "生命周期": str(r.get("生命周期", "")),
                    "涨10日": r.get("涨10日"),
                    "强度趋势": r.get("强度趋势"),
                    "主线评分": r.get("主线评分"),
                }
    except Exception:  # noqa: BLE001
        pass
    return None
