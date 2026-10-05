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

# 行业下拉：同花顺 90 细分行业（强主线置顶并带生命周期标签）
try:
    industries = md.get_all_industries()
    if not industries:
        st.error("行业板块列表获取失败，请检查网络后重试。")
        st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"行业板块列表获取失败：{e}")
    st.stop()

# 强主线 + 生命周期（来自主线分析；细分行业名 → 宽行业名映射后匹配）
_mainline_meta = {}
try:
    from analysis import mainline as ml
    _ml = ml.mainline_ranking(top_n=8)
    if _ml.get("ranking") is not None and not _ml["ranking"].empty:
        for _, r in _ml["ranking"].iterrows():
            _mainline_meta[str(r["板块名称"])] = str(r["生命周期"])
except Exception:  # noqa: BLE001
    pass

from data.market_data import THS_TO_WIDE


def _wide(x):
    return THS_TO_WIDE.get(x, x)


labelled = []
for i in industries:
    w = _wide(i)
    tag = _mainline_meta.get(w, "")
    labelled.append(f"{i}（{tag}）" if tag else i)

_strong = [i for i in industries if _wide(i) in _mainline_meta and _mainline_meta[_wide(i)] in ("启动", "发酵")]
_default_idx = 0
if _strong:
    _default_idx = industries.index(_strong[0])
    st.caption(f"当前强主线（启动/发酵）：{'、'.join(_strong)}，下拉已默认选中第一个")
sel_label = st.selectbox("选择行业板块（同花顺细分行业，共 %d 个）" % len(industries), labelled, index=_default_idx)
industry = sel_label.split("（")[0]

top_n = st.slider("展示前 N 名", 5, 30, 10, step=5)
only_strong = st.checkbox("只看「强信号 / 中等」候选（过滤观望）", value=False)

if st.button("执行选股打分", type="primary"):
    with st.spinner("正在拉取成分股与历史数据并打分……"):
        res = stk.screen_industry(industry, top_n=top_n)
    for err in res.get("errors", []):
        st.warning(err)

    table = res.get("table")
    if table is None or table.empty:
        st.stop()

    if only_strong and "标签" in table.columns:
        table = table[table["标签"] != "观望"].reset_index(drop=True)
        if table.empty:
            st.info("该板块无强信号/中等候选，按「观望」处理，建议不做。")

    st.subheader(f"「{industry}」选股打分排名")
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption("总分 = 动量(30) + 右侧(25) + 十日线战法(25) + 超跌(20)。标签：≥60 强信号，40-59 中等，<40 观望。"
               "右侧基本面列为排雷参考：ROE/净利同比/负债率来自最新报告期，预警如'亏损/业绩下滑/高负债/小盘'。")

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
