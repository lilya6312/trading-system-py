# -*- coding: utf-8 -*-
"""
pages/6_自选股池.py —— 自选股池
"""
import pandas as pd
import streamlit as st

from analysis import watchlist as wl

st.set_page_config(page_title="自选股池", page_icon="⭐", layout="wide")
st.title("自选股池")

# ---------------- 添加 ----------------
with st.form("add_watch_form"):
    c1, c2 = st.columns([1, 3])
    code = c1.text_input("股票代码（6 位）", value="")
    note = c2.text_input("备注（可选）", value="")
    submitted = st.form_submit_button("加入自选股", type="primary")
    if submitted:
        ok, msg = wl.add_watch(code, note)
        if ok:
            st.success(msg)
        else:
            st.warning(msg)

# ---------------- 行情表 ----------------
st.subheader("自选股行情")
df = wl.watch_quotes()
if df.empty:
    st.info("自选股池为空：输入代码加入第一只自选股。")
    st.stop()

show_cols = ["code", "name", "最新价", "涨跌幅", "换手率", "成交额(亿)", "added_date", "note"]
show_cols = [c for c in show_cols if c in df.columns]
st.dataframe(df[show_cols].reset_index(drop=True), use_container_width=True, hide_index=True)
st.caption("行情来自全市场实时快照；休市日显示最近交易日收盘数据。")

# ---------------- 操作：删除 / 去决策页 ----------------
st.subheader("操作")
options = df.apply(lambda r: f"{r['code']} {r['name']}（{r['added_date']}）", axis=1).tolist()
sel = st.selectbox("选择标的", options)

c1, c2 = st.columns(2)
if c1.button("删除该自选股"):
    code = str(sel).split(" ")[0]
    ok, msg = wl.remove_watch(code)
    if ok:
        st.success(msg)
        st.rerun()
    else:
        st.warning(msg)

if c2.button("前往决策页分析", type="primary"):
    code = str(sel).split(" ")[0]
    st.query_params["code"] = code
    st.switch_page("pages/4_交易系统决策.py")

# ---------------- 选中个股 K 线（含布林带） ----------------
st.subheader("K 线速览（BOLL 20,2）")
if st.button("显示 K 线", key="show_kline"):
    from data import market_data as md
    code = str(sel).split(" ")[0]
    with st.spinner(f"拉取 {code} 历史数据……"):
        hist = md.get_stock_hist(code, days=90)
    if hist is None or hist.empty:
        st.warning("无法获取该标的历史数据")
        st.stop()
    h = hist.copy()
    h["MA20"] = h["收盘"].rolling(20).mean()
    h["std20"] = h["收盘"].rolling(20).std(ddof=0)
    h["BOLL上"] = h["MA20"] + 2 * h["std20"]
    h["BOLL下"] = h["MA20"] - 2 * h["std20"]

    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        st.error("缺少 plotly，请执行: python -m pip install plotly")
        st.stop()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=h["日期"], open=h["开盘"], high=h["最高"], low=h["最低"], close=h["收盘"],
        name="K线", increasing_line_color="#d62728", decreasing_line_color="#2ca02c",
    ), row=1, col=1)
    for n, color in ((5, "#1f77b4"), (10, "#ff7f0e")):
        fig.add_trace(go.Scatter(x=h["日期"], y=h[f"MA{n}"], name=f"MA{n}",
                                 line=dict(width=1, color=color)), row=1, col=1)
    fig.add_trace(go.Scatter(x=h["日期"], y=h["BOLL下"], name="BOLL下轨",
                             line=dict(width=1, color="#7f7f7f", dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=h["日期"], y=h["BOLL上"], name="BOLL上轨",
                             line=dict(width=1, color="#7f7f7f", dash="dot"),
                             fill="tonexty", fillcolor="rgba(127,127,127,0.08)"), row=1, col=1)
    vol_colors = ["#d62728" if c >= 0 else "#2ca02c" for c in h["涨跌幅"]]
    fig.add_trace(go.Bar(x=h["日期"], y=h["成交量"], name="成交量",
                         marker_color=vol_colors, opacity=0.6), row=2, col=1)
    fig.update_layout(title=f"{sel}", height=430, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02))
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.caption("自选股保存在本地 data/watchlist.json，换机器不共享。")
