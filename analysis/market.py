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


# ---------------- 每日行情分析（自动快评） ----------------
_brief_cache: dict[str, tuple[float, dict]] = {}
_BRIEF_TTL = 300  # 每日快评缓存 5 分钟


def daily_brief(force: bool = False) -> dict:
    """
    每日行情分析：整合大盘阶段 + 市场结构 + 情绪面 + 主线识别，
    自动生成结构化快评（指数 / 情绪 / 主线 / 操作提示），供"每日行情分析"区块展示。
    结果缓存 5 分钟，避免页面 rerun 重复触发主线识别（~38s）。
    """
    import time
    now = time.time()
    hit = _brief_cache.get("brief")
    if hit and now - hit[0] < _BRIEF_TTL and not force:
        return hit[1]

    from analysis import sentiment
    from analysis import mainline

    out = {"sections": {}, "text": "", "errors": []}

    ov = market_overview()
    out["errors"].extend(ov.get("errors", []))
    emo = None
    try:
        emo = sentiment.sentiment_snapshot()
        out["errors"].extend(emo.get("errors", []))
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"情绪面失败: {e}")

    # 1) 指数
    idx_text, idx_rows = "", []
    idx = ov.get("indexes")
    if idx is not None and not idx.empty:
        idx_rows = idx.to_dict("records")
        parts = [f"{r['名称']} {r['最新价']:.2f}（{r['涨跌幅']:+.2f}%）" for r in idx_rows[:4]]
        idx_text = "、".join(parts)
    out["sections"]["指数"] = idx_text

    # 2) 市场结构与阶段
    phase = ov.get("phase", {})
    struct = ov.get("structure", {})
    phase_text = f"大盘阶段：**{phase.get('phase', '数据不足')}**（{phase.get('desc', '')}）→ 建议仓位 {phase.get('position', '空仓防御')}"
    if struct:
        ratio = struct.get("涨跌比")
        bias = "多方占优" if ratio and ratio > 1.2 else ("空方占优" if ratio and ratio < 0.8 else "多空均衡")
        phase_text += (f"；上涨 {struct.get('上涨')} / 下跌 {struct.get('下跌')} 家，涨跌比 {ratio or '-'}（{bias}），"
                       f"两市成交 {struct.get('两市成交额(亿)', 0):,.0f} 亿")
    out["sections"]["大盘"] = phase_text

    # 3) 情绪面
    emo_text = "情绪面数据暂不可达"
    if emo is not None:
        if emo.get("情绪评分") is not None:
            sc = emo["情绪评分"]
            emo_text = (f"情绪评分 **{sc}**/100（涨停 {emo.get('涨停家数')} 家 / 最高连板 {emo.get('最高连板')} 板 / "
                        f"炸板率 {emo.get('炸板率')}% / 昨日涨停今均涨 {emo.get('昨日涨停今平均涨幅')}%）")
            if sc >= 70:
                emo_text += " → 情绪偏热，注意高潮兑现"
            elif sc >= 40:
                emo_text += " → 情绪中性，做主线不做杂毛"
            else:
                emo_text += " → 情绪低迷，接近冰点，等右侧信号"
    out["sections"]["情绪"] = emo_text

    # 4) 主线
    main_text = "主线数据暂不可达"
    try:
        ml = mainline.mainline_ranking(top_n=5)
        if ml.get("ranking") is not None and not ml["ranking"].empty:
            df = ml["ranking"]
            strong = "、".join(ml.get("strong", [])) or "无"
            trend_parts = []
            for _, r in df.head(5).iterrows():
                trend_parts.append(
                    f"{r['板块名称']}（涨10日 {r['涨10日']}% / 阳线率 {r['10日阳线率']}% / "
                    f"趋势 {r['强度趋势']} / {r['生命周期']}）")
            main_text = (f"强主线：**{strong}**\n\n" + "\n".join(
                f"- {t}" for t in trend_parts))
        out["errors"].extend(ml.get("errors", []))
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"主线失败: {e}")
    out["sections"]["主线"] = main_text

    # 5) 操作提示（基于阶段 + 情绪）
    tips = []
    ph = phase.get("phase")
    sc = emo.get("情绪评分") if emo is not None else None
    if ph == "强势" and sc is not None and sc >= 70:
        tips.append("强势+情绪热：顺势持主线龙头，但警惕高潮期最后一棒，兑现加速品种。")
    elif ph in ("强势", "震荡"):
        tips.append("结构市：只做主线内强于大盘的龙头，弱票一律不碰（铁律：主线内选股）。")
    elif ph in ("弱势", "冰点"):
        tips.append("弱势/冰点：禁止短线与右侧开仓（系统已自动封禁），空仓或极小仓试错超跌，等右侧信号。")
    else:
        tips.append("阶段数据不足：按弱势对待，控制仓位，优先看主线与情绪确认方向。")
    out["sections"]["操作提示"] = "；".join(tips)
    out["text"] = "\n\n".join(f"**【{k}】** {v}" for k, v in out["sections"].items())
    _brief_cache["brief"] = (now, out)
    return out
