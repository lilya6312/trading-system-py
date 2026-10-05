# -*- coding: utf-8 -*-
"""
analysis/stock.py —— 行业主线个股选股对比
==========================================
输入：行业板块名称
流程：板块成分股 → 合并全市场快照（量比/60日涨幅等）→ 过滤 ST/涨停板 → 打分排序 → 对候选补算技术指标。
打分维度（满分 100，均为启发式信号，供决策参考）：
  - 动量（30）：60 日涨幅为正且居前
  - 右侧（25）：MA5>MA10>MA20 多头排列 + 站上 MA20 + 量比>1.2
  - 十日线战法（25）：近 5 日放量大涨后缩量回踩 MA10 附近（经典买点）
  - 超跌反弹（20）：距 60 日高点回撤 ≥25% 且今日收阳
"""
from __future__ import annotations

import pandas as pd

from analysis.market import ma
from data import market_data as md
import config


# ---------------- 指标 ----------------
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    diff = close.diff()
    gain = diff.clip(lower=0).rolling(n).mean()
    loss = (-diff.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, pd.NA)
    return (100 - 100 / (1 + rs)).fillna(50)


def _pick(df: pd.DataFrame, *names) -> pd.Series:
    """多源列名兼容：akshare 东财返回中文列，新浪返回英文列，统一按首匹配取。"""
    for n in names:
        if n in df.columns:
            return df[n]
    raise KeyError(f"数据缺少列: {names}")


def calc_indicators(daily: pd.DataFrame) -> dict:
    """由个股日线计算一组决策指标。"""
    close = _pick(daily, "close", "收盘").astype(float)
    vol = _pick(daily, "volume", "成交量").astype(float)
    high = _pick(daily, "high", "最高").astype(float)
    chg = _pick(daily, "涨跌幅", "pct_chg", "changepercent")
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else last
    vol5 = float(vol.tail(5).mean()) if len(vol) >= 5 else float(vol.iloc[-1])
    vol20 = float(vol.tail(20).mean()) if len(vol) >= 20 else vol5

    ma5 = float(ma(close, 5).iloc[-1]) if len(close) >= 5 else last
    ma10 = float(ma(close, 10).iloc[-1]) if len(close) >= 10 else last
    ma20 = float(ma(close, 20).iloc[-1]) if len(close) >= 20 else last
    ma60 = float(ma(close, 60).iloc[-1]) if len(close) >= 60 else last

    high60 = float(high.tail(60).max()) if len(high) >= 5 else last
    drawdown = (high60 - last) / high60 * 100 if high60 else 0.0

    # 近 5 日是否有单日大涨（>=7%）
    big_up = float(chg.tail(5).max()) >= 7 if len(chg) >= 2 else False

    return {
        "last": last,
        "chg_pct": (last - prev) / prev * 100 if prev else 0.0,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "vol_ratio": vol5 / vol20 if vol20 else 1.0,
        "vol_ratio_5d": float(vol.iloc[-1]) / vol5 if vol5 else 1.0,
        "drawdown_60": round(drawdown, 2),
        "high60": high60,
        "rsi14": float(rsi(close).iloc[-1]) if len(close) > 14 else 50.0,
        "bull_alignment": ma5 > ma10 > ma20,
        "big_up_recent": big_up,
        "near_ma10": abs(last - ma10) / ma10 * 100 if ma10 else 99.0,
        "retrace_ma10": last >= ma10 * 0.97 and last <= ma10 * 1.05,
    }


# ---------------- 打分 ----------------
def score_stock(indi: dict) -> dict:
    """按四维度打分，返回各项得分与信号标签。"""
    s = {"动量": 0.0, "右侧": 0.0, "十日线": 0.0, "超跌": 0.0}

    # 动量：60 日涨幅（用 20 日涨幅近似，避免再拉长历史）
    # 用 drawdown 无法表达涨幅，这里以 rsi 与位置近似：强势票 rsi>55 且仍在高位
    if indi["rsi14"] >= 60:
        s["动量"] = 22 + min(8, (indi["rsi14"] - 60) / 5)
    elif indi["rsi14"] >= 50:
        s["动量"] = 15
    elif indi["rsi14"] >= 40:
        s["动量"] = 8
    else:
        s["动量"] = 3

    # 右侧
    if indi["bull_alignment"]:
        s["右侧"] += 15
        if indi["last"] > indi["ma20"]:
            s["右侧"] += 5
        if indi["vol_ratio_5d"] > 1.2:
            s["右侧"] += 5
    elif indi["last"] > indi["ma20"]:
        s["右侧"] = 8

    # 十日线战法：大涨后回踩 MA10 缩量
    if indi["big_up_recent"] and indi["retrace_ma10"]:
        s["十日线"] = 25 if indi["vol_ratio_5d"] < 1.1 else 18
    elif indi["retrace_ma10"] and indi["vol_ratio_5d"] < 1.0:
        s["十日线"] = 15

    # 超跌反弹
    if indi["drawdown_60"] >= 25 and indi["chg_pct"] > 0:
        s["超跌"] = 20
    elif indi["drawdown_60"] >= 20 and indi["chg_pct"] > 0:
        s["超跌"] = 12
    elif indi["drawdown_60"] >= 30:
        s["超跌"] = 8

    total = round(sum(s.values()), 1)
    if total >= 60:
        tag = "强信号"
    elif total >= 40:
        tag = "中等"
    else:
        tag = "观望"
    return {"总分": total, "标签": tag, **s}


# ---------------- 选股主流程 ----------------
def screen_industry(industry: str, top_n: int = 10) -> dict:
    """
    行业主线选股：返回
    - table: 打分对比表（含指标列）
    - detail: {代码: 指标字典}（供页面画 K 线用）
    - errors: 错误信息列表
    """
    out = {"table": None, "detail": {}, "errors": []}
    try:
        cons = md.get_industry_cons(industry)
        spot = md.get_all_stock_spot()
        if cons is None or cons.empty or spot is None or spot.empty:
            out["errors"].append("板块成分股或全市场快照无数据")
            return out
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"数据获取失败: {e}")
        return out

    cons = cons.copy()
    spot = spot.copy()
    spot["代码"] = spot["代码"].astype(str).str.zfill(6)
    cons["代码"] = cons["代码"].astype(str).str.zfill(6)

    # 成分股自带行情（腾讯 getBoardRankList），全市场快照仅补充量比/60日涨幅等缺失列
    merged = cons.copy()
    if spot is not None and not spot.empty:
        extra = ["量比", "60日涨跌幅", "年初至今涨跌幅", "成交额"]
        extra = [c for c in extra if c in spot.columns]
        merged = merged.merge(spot[["代码"] + extra], on="代码", how="left")

    # 过滤：ST / 退市 / 涨停买不进
    merged = merged[
        ~merged["名称"].astype(str).str.contains("|".join(config.ST_PATTERN), na=False)
    ]
    merged = merged[pd.to_numeric(merged["涨跌幅"], errors="coerce").fillna(0) < 9.5]

    if merged.empty:
        out["errors"].append("该板块成分股过滤后为空")
        return out

    # 打分
    rows = []
    for _, r in merged.head(60).iterrows():
        code = str(r["代码"]).zfill(6)
        try:
            hist = md.get_stock_hist(code, days=120)
            if hist is None or len(hist) < 20:
                continue
            indi = calc_indicators(hist)
            sc = score_stock(indi)
            rows.append({
                "代码": code,
                "名称": str(r["名称"]),
                "最新价": round(float(r["最新价"]), 2) if pd.notna(r["最新价"]) else None,
                "涨跌幅": round(float(r["涨跌幅"]), 2) if pd.notna(r["涨跌幅"]) else None,
                "量比": round(float(r["量比"]), 2) if pd.notna(r["量比"]) else None,
                "换手率": round(float(r["换手率"]), 2) if pd.notna(r["换手率"]) else None,
                "60日涨跌幅": round(float(r["60日涨跌幅"]), 2) if pd.notna(r["60日涨跌幅"]) else None,
                "总分": sc["总分"],
                "标签": sc["标签"],
                "动量": sc["动量"], "右侧": sc["右侧"],
                "十日线": sc["十日线"], "超跌": sc["超跌"],
                "距60日高回撤%": indi["drawdown_60"],
                "RSI14": round(indi["rsi14"], 1),
                "多头排列": "是" if indi["bull_alignment"] else "否",
            })
            out["detail"][code] = indi
        except Exception:  # noqa: BLE001
            continue

    if not rows:
        out["errors"].append("候选股均无法获取历史数据")
        return out

    table = pd.DataFrame(rows).sort_values("总分", ascending=False).reset_index(drop=True)
    table.insert(0, "排名", range(1, len(table) + 1))
    out["table"] = table.head(top_n)
    return out
