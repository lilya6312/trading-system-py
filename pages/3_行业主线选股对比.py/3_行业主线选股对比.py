# -*- coding: utf-8 -*-
"""
pages/3_行业主线选股对比.py —— 行业主线个股选股对比
"""
import pandas as pd
import streamlit as st

from analysis import stock as stk
from data import market_data as md

st.set_page_config(page_title="行业主线选股对比", page_icon="🎯", layout="wide")
st.title("行业主线个股选股对比")

# 行业下拉
try:
    ind = md.get_industry_spot()
    if ind is None or ind.empty:
        st.error("行业板块数据获取失败，请检查网络后重试。")
        st.stop()
    industries = ind["板块名称"].astype(str).tolist()
except Exception as e:  # noqa: BLE001
    st.error(f"行业板块数据获取失败：{e}")
    st.stop()

industry = st.selectbox("选择行业板块", industries, index=0)

top_n = st.slider("展示前 N 名", 5, 30, 10, step=5)

if st.button("执行选股打分", type="primary"):
    with st.spinner("正在拉取成分股与历史数据并打分……"):
        res = stk.screen_industry(industry, top_n=top_n)
    for err in res.get("errors", []):
        st.warning(err)

    table = res.get("table")
    if table is None or table.empty:
        st.stop()

    st.subheader(f"「{industry}」选股打分排名")
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption("总分 = 动量(30) + 右侧(25) + 十日线战法(25) + 超跌(20)。标签：≥60 强信号，40-59 中等，<40 观望。")

    # K 线对比
    st.subheader("个股 K 线对比（选 2-4 只）")
    names = table[["代码", "名称"]].astype(str).agg(lambda r: f"{r['代码']} {r['名称']}", axis=1).tolist()
    picks = st.multiselect("选择要对比的个股", names, default=names[:2] if len(names) >= 2 else names[:1], max_selections=4)
    show_boll = st.checkbox("显示布林带（BOLL 20,2：MA20 ± 2×标准差）", value=True)

    if picks:
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            st.error("缺少 plotly，请执行: python -m pip install plotly")
            st.stop()

        for i in range(0, len(picks), 2):
            cols = st.columns(2)
            for col, pick in zip(cols, picks[i:i + 2]):
                code = pick.split(" ")[0]
                with col:
                    with st.spinner(f"绘制 {pick} K线……"):
                        hist = md.get_stock_hist(code, days=90)
                    if hist is None or hist.empty:
                        st.warning(f"{pick} 无历史数据")
                        continue
                    h = hist.copy()
                    for n in (5, 10, 20):
                        h[f"MA{n}"] = h["收盘"].rolling(n).mean()
                    if show_boll:
                        h["std20"] = h["收盘"].rolling(20).std(ddof=0)
                        h["BOLL上"] = h["MA20"] + 2 * h["std20"]
                        h["BOLL下"] = h["MA20"] - 2 * h["std20"]
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                        row_heights=[0.75, 0.25], vertical_spacing=0.03)
                    fig.add_trace(go.Candlestick(
                        x=h["日期"], open=h["开盘"], high=h["最高"],
                        low=h["最低"], close=h["收盘"], name="K线",
                        increasing_line_color="#d62728", decreasing_line_color="#2ca02c",
                    ), row=1, col=1)
                    for n, color in ((5, "#1f77b4"), (10, "#ff7f0e"), (20, "#9467bd")):
                        fig.add_trace(go.Scatter(x=h["日期"], y=h[f"MA{n}"],
                                                 name=f"MA{n}", line=dict(width=1, color=color)), row=1, col=1)
                    if show_boll:
                        fig.add_trace(go.Scatter(x=h["日期"], y=h["BOLL下"], name="BOLL下轨",
                                                 line=dict(width=1, color="#7f7f7f", dash="dot")), row=1, col=1)
                        fig.add_trace(go.Scatter(x=h["日期"], y=h["BOLL上"], name="BOLL上轨",
                                                 line=dict(width=1, color="#7f7f7f", dash="dot"),
                                                 fill="tonexty", fillcolor="rgba(127,127,127,0.08)"), row=1, col=1)
                    vol_colors = ["#d62728" if c >= 0 else "#2ca02c" for c in h["涨跌幅"]]
                    fig.add_trace(go.Bar(x=h["日期"], y=h["成交量"], name="成交量",
                                         marker_color=vol_colors, opacity=0.6), row=2, col=1)
                    fig.update_layout(
                        title=f"{pick}", height=430, margin=dict(l=10, r=10, t=40, b=10),
                        xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02),
                    )
                    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.caption("提示：选股打分仅基于公开行情与技术信号，先到「交易系统决策」页确认模型与止损，再谈仓位。")
