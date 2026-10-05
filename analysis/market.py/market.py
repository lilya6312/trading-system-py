# -*- coding: utf-8 -*-
"""
analysis/market.py —— 大盘研判
================================
输入：指数快照 / 全市场快照 / 上证指数日线
输出：指数行情表、市场结构（涨跌家数、近似涨停数、成交额）、大盘阶段与对应仓位建议。
全部指标为简化启发式，用于交易系统内部决策参考，不构成投资建议。
"""
from __future__ import annotations

import pandas as pd

import config
from data import market_data as md


# ---------------- 技术指标 ----------------
def ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def _phase_from_index(daily: pd.DataFrame) -> dict:
    """根据上证指数日线判断大盘阶段（简化规则，可对照 config.MARKET_PHASE_RULES 调参）。"""
    close = daily["close"]
    ma20 = ma(close, 20).dropna()
    if len(ma20) < 25:
        return {"phase": "数据不足", "desc": "指数历史数据不足 25 个交易日", "position": "空仓防御 0-2 成"}

    cur_close = float(close.iloc[-1])
    cur_ma20 = float(ma20.iloc[-1])
    ma20_prev = float(ma20.iloc[-6]) if len(ma20) >= 6 else cur_ma20
    ma20_up = cur_ma20 > ma20_prev

    vol = daily["volume"]
    vol5 = float(vol.tail(5).mean()) if len(vol) >= 5 else 0.0
    vol20 = float(vol.tail(20).mean()) if len(vol) >= 20 else vol5
    high20 = float(close.tail(20).max())

    if cur_close > cur_ma20 and ma20_up:
        phase = "强势"
    elif cur_close < cur_ma20 and not ma20_up:
        # 弱势 + 快速回撤 + 缩量 → 冰点
        if high20 > 0 and (high20 - cur_close) / high20 > 0.08 and vol5 < vol20 * 0.85:
            phase = "冰点"
        else:
            phase = "弱势"
    else:
        phase = "震荡"

    rule = config.MARKET_PHASE_RULES.get(phase, {})
    return {
        "phase": phase,
        "desc": rule.get("desc", ""),
        "position": rule.get("position", ""),
        "close": round(cur_close, 2),
        "ma20": round(cur_ma20, 2),
        "ma20_up": ma20_up,
        "high20": round(high20, 2),
        "drawdown_from_high20": round((high20 - cur_close) / high20 * 100, 2) if high20 else 0.0,
        "vol5_vs_vol20": round(vol5 / vol20, 2) if vol20 else 0.0,
    }


# ---------------- 大盘总览 ----------------
def market_overview() -> dict:
    """
    汇总大盘数据：
    - indexes: 各指数 名称/代码/最新价/涨跌幅
    - structure: 上涨/下跌/平盘家数、近似涨停数、两市成交额(亿)
    - phase: 阶段判断（含仓位建议）
    任一数据源失败时对应字段置 None，由页面提示，不影响其余部分。
    """
    result = {"indexes": None, "structure": None, "phase": None, "errors": []}

    # 1) 指数行情
    try:
        spot = md.get_index_spot()
        if spot is not None and not spot.empty:
            rows = []
            for name, (series, _code) in config.INDEX_WATCHLIST.items():
                m = spot[spot["名称"] == name]
                if m.empty:
                    # 名称不匹配时按代码前缀兜底
                    m = spot[spot["代码"].astype(str).str.endswith(_code[2:])]
                if not m.empty:
                    row = m.iloc[0]
                    rows.append({
                        "名称": name,
                        "代码": str(row["代码"]),
                        "最新价": float(row["最新价"]),
                        "涨跌幅": float(row["涨跌幅"]),
                        "成交额(亿)": round(float(row["成交额"]) / 1e8, 2),
                    })
            result["indexes"] = pd.DataFrame(rows)
        else:
            result["errors"].append("指数实时接口无数据")
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"指数接口失败: {e}")

    # 2) 市场结构
    try:
        spot_a = md.get_all_stock_spot()
        if spot_a is not None and not spot_a.empty:
            chg = spot_a["涨跌幅"].astype(float)
            up = int((chg > 0).sum())
            down = int((chg < 0).sum())
            flat = int((chg == 0).sum())
            limit_up = int((chg >= config.LIMIT_UP_RATIO * 100).sum())  # 接口涨跌幅单位为 %
            turnover = round(float(spot_a["成交额"].sum()) / 1e8, 2)   # 亿元
            result["structure"] = {
                "上涨": up, "下跌": down, "平盘": flat,
                "近似涨停": limit_up,
                "两市成交额(亿)": turnover,
                "涨跌比": round(up / down, 2) if down else None,
            }
        else:
            result["errors"].append("全市场快照无数据")
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"全市场接口失败: {e}")

    # 3) 阶段判断
    try:
        daily = md.get_index_daily("sh000001", days=120)
        if daily is not None and not daily.empty:
            result["phase"] = _phase_from_index(daily)
        else:
            result["errors"].append("上证指数日线无数据")
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"指数日线接口失败: {e}")

    return result
