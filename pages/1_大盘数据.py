# -*- coding: utf-8 -*-
"""
pages/1_大盘数据.py —— 每日大盘数据
"""
import pandas as pd
import streamlit as st

import config
from analysis import market as mkt

st.set_page_config(page_title="大盘数据", page_icon="📊", layout="wide")
st.title("每日大盘数据")

overview = mkt.market_overview()
for err in overview.get("errors", []):
    st.warning(err)

# ---- 指数行情 ----
st.subheader("主要指数")
idx = overview.get("indexes")
if idx is not None and not idx.empty:
    cols = st.columns(len(idx))
    for col, (_, r) in zip(cols, idx.iterrows()):
        chg = r["涨跌幅"]
        delta = f"{chg:+.2f}%"
        col.metric(r["名称"], f"{r['最新价']:.2f}", delta)
    with st.expander("查看指数明细表"):
        st.dataframe(idx, use_container_width=True, hide_index=True)
else:
    st.error("指数行情获取失败，请检查网络或稍后重试。")

# ---- 市场结构 ----
st.subheader("市场结构")
struct = overview.get("structure")
if struct:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("上涨家数", struct["上涨"])
    c2.metric("下跌家数", struct["下跌"])
    c3.metric("平盘", struct["平盘"])
    c4.metric("近似涨停（≥9.8%）", struct["近似涨停"], help="按涨幅近似统计，精确涨停请以涨停池为准")
    c5.metric("两市成交额(亿)", f"{struct['两市成交额(亿)']:,.0f}")
    if struct.get("涨跌比"):
        st.caption(f"涨跌比 {struct['涨跌比']} ：{'多方占优' if struct['涨跌比'] > 1.2 else ('空方占优' if struct['涨跌比'] < 0.8 else '多空均衡')}")
else:
    st.error("市场结构数据获取失败。")

# ---- 情绪面（赚钱效应） ----
st.subheader("情绪面（赚钱效应）")
from analysis import sentiment as sent

emo = sent.sentiment_snapshot()
for err in emo.get("errors", []):
    st.caption(f"⚠️ {err}")
if emo.get("情绪评分") is not None:
    e1, e2, e3, e4, e5, e6 = st.columns(6)
    e1.metric("情绪评分", emo["情绪评分"], help="0-100：涨停多/连板高/炸板少/溢价正 → 高分")
    e2.metric("涨停家数", emo["涨停家数"] or "-")
    e3.metric("最高连板", emo["最高连板"] or "-")
    e4.metric("炸板率", f"{emo['炸板率']}%" if emo["炸板率"] is not None else "-")
    e5.metric("昨日涨停今平均涨幅", f"{emo['昨日涨停今平均涨幅']}%" if emo["昨日涨停今平均涨幅"] is not None else "-")
    e6.metric("晋级率", f"{emo['晋级率']}%" if emo["晋级率"] is not None else "-")
    sc = emo["情绪评分"]
    if sc >= 70:
        st.success(f"情绪偏热（{sc}）：赚钱效应强，可积极跟踪主线，但注意高潮期别追最后一棒。")
    elif sc >= 40:
        st.info(f"情绪中性（{sc}）：结构性行情，做主线龙头、少碰杂毛。")
    else:
        st.warning(f"情绪低迷（{sc}）：接近冰点，超跌反弹候选增多，但左侧不抄底、等右侧信号。")
    if emo.get("涨停股"):
        with st.expander(f"今日涨停股清单（{len(emo['涨停股'])} 家）"):
            import pandas as pd
            st.dataframe(pd.DataFrame(emo["涨停股"]), use_container_width=True, hide_index=True)
else:
    st.error("情绪面数据获取失败（涨停池/快照均不可达）。")

# ---- 大盘阶段 ----
st.subheader("大盘阶段判断")
phase = overview.get("phase")
if phase:
    c1, c2, c3 = st.columns([1, 2, 1])
    c1.metric("阶段", phase["phase"])
    c2.markdown(f"**判断依据**：{phase['desc']}")
    c3.markdown(f"**对应仓位**：{phase['position']}")
    m1, m2, m3 = st.columns(3)
    m1.metric("上证收盘", phase["close"])
    m2.metric("MA20", phase["ma20"], help="20 日均线")
    m3.metric("距20日高点回撤", f"{phase['drawdown_from_high20']:.2f}%")
    # 上证日线图
    daily = None
    try:
        from data import market_data as md
        daily = md.get_index_daily("sh000001", days=90)
    except Exception:
        pass
    if daily is not None and not daily.empty:
        chart = daily.copy()
        chart["MA20"] = chart["close"].rolling(20).mean()
        chart["MA60"] = chart["close"].rolling(60).mean()
        chart = chart.set_index("date")[["close", "MA20", "MA60"]]
        st.line_chart(chart, height=360)
else:
    st.error("大盘阶段判断失败。")

st.markdown("---")
st.caption("数据来源：AkShare（东方财富/新浪公开行情）。指标为简化启发式规则，不构成投资建议。")
