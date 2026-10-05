# -*- coding: utf-8 -*-
"""
pages/2_主线行情个股分析.py —— 每日行情分析 + 主线行情 + 个股搜索分析
"""
import pandas as pd
import streamlit as st

import config
from analysis import decision, fundamental, mainline
from analysis import market as mkt

st.set_page_config(page_title="主线行情个股分析", page_icon="🔥", layout="wide")
st.title("主线行情个股分析")

tab_brief, tab_mainline, tab_stock = st.tabs(["每日行情分析", "主线行情", "个股搜索分析"])

# ---------------- 每日行情分析 ----------------
with tab_brief:
    st.subheader("每日行情分析（自动快评）")
    with st.spinner("整合指数 / 情绪 / 主线数据……"):
        brief = mkt.daily_brief()
    for err in brief.get("errors", []):
        st.caption(f"⚠️ {err}")
    for k, v in brief.get("sections", {}).items():
        if not v:
            continue
        if k == "主线":
            st.markdown(f"**【{k}】**")
            for line in str(v).split("\n"):
                st.markdown(line)
        else:
            st.markdown(f"**【{k}】** {v}")

# ---------------- 主线行情 ----------------
with tab_mainline:
    res = mainline.mainline_ranking(top_n=8)
    for err in res.get("errors", []):
        st.warning(err)

    if res["strong"]:
        st.success("**当前强主线候选**：" + " / ".join(res["strong"]))
    else:
        st.info("暂无明显强主线（板块内涨停 < 2 家且无 2 连板），建议空仓或小仓观望。")

    st.subheader("板块强度排行（RPS + 10 日强度序列 + 生命周期）")
    df = res.get("ranking")
    if df is not None and not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
        with st.expander("如何看懂主线评分、10日强度与生命周期"):
            st.markdown(
                "**主线评分** = 25%×当日涨幅 + 20%×板块内涨停家数 + 15%×上涨家数占比 + 10%×板块容量 + 30%×持续性\n\n"
                "**最近 10 个交易日板块强度（主线强度核心）**：\n"
                "1. 涨3日/涨5日/涨10日：板块指数近 N 日累计涨幅（%），多头趋势应逐级为正；\n"
                "2. 10日阳线率：10 日中上涨天数占比（≥70% 属强持续）；\n"
                "3. 10日日均涨幅：平均每日涨跌幅（绝对动能）；\n"
                "4. 强度趋势：近 3 日 vs 前 7 日日均涨幅 → 增强（加速）/持平/减弱（退潮前兆）；\n"
                "5. 近10日RS：相对全市场的 10 日强弱比值，>1 跑赢大盘；\n"
                "6. 距20日高点%：回撤越小越强势；站上MA10：短中期趋势完好。\n\n"
                "**生命周期四阶段**：\n"
                "- 🚀 启动：刚点火/低位放量，涨停家数初现 → 试错仓跟进龙头；\n"
                "- 🔥 发酵：连板梯队扩散、RPS 抬升 → 主升仓（6-8 成）；\n"
                "- ⚠️ 高潮：涨停潮+高换手+加速 → 只做龙头不接力、准备兑现；\n"
                "- 📉 退潮：炸板率升高、RPS 转弱、跌破 MA10 → 停止参与，等下一轮点火。\n\n"
                "**操作纪律**：只做「启动/发酵」期强主线，回避「退潮」；趋势由「增强」转「减弱」时减仓。\n"
                "**新主线三特征**：容量大、新板块或调整很久的老板块、指数调整时跌幅可控低位点火。"
            )
    else:
        st.error("板块数据获取失败，请检查网络后重试。")

# ---------------- 个股搜索分析 ----------------
with tab_stock:
    st.subheader("个股搜索分析：代码或名称")
    st.caption("输入 6 位代码 / 代码前缀 / 股票名称，选择候选后自动跑：所属主线 + 技术指标 + 全模型匹配 + 基本面排雷 + K 线。")
    from data import market_data as md

    kw = st.text_input("搜索（如 600519 / 茅台 / 宁德）", value="", key="stock_search_kw")
    cand = md.search_stock(kw) if kw else pd.DataFrame()
    if kw and cand.empty:
        st.info("未找到匹配股票，换关键词试试。")
    pick = None
    if not cand.empty:
        opts = cand.astype(str).agg(lambda r: f"{r['代码']} {r['名称']}", axis=1).tolist()
        pick = st.selectbox("选择候选", opts, key="stock_search_pick")
    else:
        pick = st.query_params.get("code", "") or ""

    if pick and st.button("执行个股分析", type="primary"):
        code = str(pick).split(" ")[0]
        with st.spinner(f"分析 {code}……"):
            d_all = {}
            for m_name in list(config.MODELS.keys()):
                d_all[m_name] = decision.decide(code, m_name, phase=None)
            d_main = next((d for m, d in d_all.items() if d["ok"]), None)
            fd = fundamental.fundamental_snapshot(code)
            line = mainline.stock_in_line(code)
        if d_main is None:
            st.error("无法获取该标的历史数据（代码可能错误或未上市）")
        else:
            i = d_main["indicators"]
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("最新价", round(i["last"], 2))
            m2.metric("涨跌幅", f"{i['chg_pct']:+.2f}%")
            m3.metric("RSI14", round(i["rsi14"], 1))
            m4.metric("距60日高点回撤", f"{i['drawdown_60']:.1f}%")
            m5.metric("量比(今/5日均)", f"{i['vol_ratio_5d']:.2f}")

            # 所属主线
            if line:
                st.markdown("**所属主线**")
                l1, l2, l3, l4, l5 = st.columns(5)
                l1.metric("所属行业", line["所属行业"])
                l2.metric("生命周期", line["生命周期"])
                l3.metric("板块涨10日", f"{line['涨10日']}%" if line["涨10日"] is not None else "-")
                l4.metric("强度趋势", line["强度趋势"])
                l5.metric("主线评分", line["主线评分"])
                if line["生命周期"] in ("退潮", "数据不足"):
                    st.warning(f"该股所属「{line['所属行业']}」处于 {line['生命周期']}，主线层面不建议参与。")
                elif line["强度趋势"] == "减弱":
                    st.info(f"该股所属「{line['所属行业']}」强度趋势转弱，注意减仓节奏。")
            else:
                st.caption("未在强主线板块成分股中匹配到该个股（可能在非主线行业，或成分股接口未覆盖）。")

            # 全模型匹配
            st.markdown("**全模型匹配**（一只票只套一个模型，选择状态最优的模型执行）")
            md_rows = []
            for m_name, dd in d_all.items():
                if not dd["ok"]:
                    continue
                md_rows.append({
                    "模型": m_name, "状态": dd["status"],
                    "买点参考": dd["prices"]["买点参考"],
                    "卖点参考": dd["prices"]["卖点参考"],
                    "止损参考": dd["prices"]["止损参考"],
                    "命中": len(dd["hit"]),
                })
            mdf = pd.DataFrame(md_rows)
            st.dataframe(mdf, use_container_width=True, hide_index=True)
            best = mdf[mdf["状态"] == "符合入场条件"]
            if not best.empty:
                st.success(f"建议模型：**{best.iloc[0]['模型']}**（符合入场条件），"
                           f"买点 {best.iloc[0]['买点参考']} / 止损 {best.iloc[0]['止损参考']}")
            else:
                st.info("当前无模型符合入场条件，禁止逆势硬做，继续跟踪。")

            # 基本面排雷
            if fd["ok"]:
                fin, info = fd["fin"], fd["info"]
                st.markdown("**基本面排雷**")
                f1, f2, f3, f4 = st.columns(4)
                f1.metric("ROE", f"{fin['净资产收益率']}%" if fin.get("净资产收益率") is not None else "-")
                f2.metric("净利同比", f"{fin['净利润同比增长率']}%" if fin.get("净利润同比增长率") is not None else "-")
                f3.metric("资产负债率", f"{fin['资产负债率']}%" if fin.get("资产负债率") is not None else "-")
                f4.metric("总市值", f"{info['总市值'] / 1e8:.0f} 亿" if info.get("总市值") else "-")
                if fd["warnings"]:
                    st.warning("基本面预警：" + "；".join(fd["warnings"]))
                else:
                    st.success("基本面未见明显雷点。")
            else:
                st.caption("基本面数据暂不可达，跳过排雷。")

            # K 线 + 布林带
            st.markdown("**K 线速览（MA + BOLL 20,2）**")
            hist = md.get_stock_hist(code, days=120)
            if hist is not None and not hist.empty:
                try:
                    import plotly.graph_objects as go
                    from plotly.subplots import make_subplots
                except ImportError:
                    st.error("缺少 plotly，请执行: python -m pip install plotly")
                else:
                    h = hist.copy()
                    for n in (5, 10, 20):
                        h[f"MA{n}"] = h["收盘"].rolling(n).mean()
                    h["std20"] = h["收盘"].rolling(20).std(ddof=0)
                    h["BOLL上"] = h["MA20"] + 2 * h["std20"]
                    h["BOLL下"] = h["MA20"] - 2 * h["std20"]
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                        row_heights=[0.75, 0.25], vertical_spacing=0.03)
                    fig.add_trace(go.Candlestick(
                        x=h["日期"], open=h["开盘"], high=h["最高"], low=h["最低"],
                        close=h["收盘"], name="K线",
                        increasing_line_color="#d62728", decreasing_line_color="#2ca02c"), row=1, col=1)
                    for n, color in ((5, "#1f77b4"), (10, "#ff7f0e"), (20, "#9467bd")):
                        fig.add_trace(go.Scatter(x=h["日期"], y=h[f"MA{n}"],
                                                 name=f"MA{n}", line=dict(width=1, color=color)), row=1, col=1)
                    fig.add_trace(go.Scatter(x=h["日期"], y=h["BOLL下"], name="BOLL下轨",
                                             line=dict(width=1, color="#7f7f7f", dash="dot")), row=1, col=1)
                    fig.add_trace(go.Scatter(x=h["日期"], y=h["BOLL上"], name="BOLL上轨",
                                             line=dict(width=1, color="#7f7f7f", dash="dot"),
                                             fill="tonexty", fillcolor="rgba(127,127,127,0.08)"), row=1, col=1)
                    vol_colors = ["#d62728" if c >= 0 else "#2ca02c" for c in h["涨跌幅"]]
                    fig.add_trace(go.Bar(x=h["日期"], y=h["成交量"], name="成交量",
                                         marker_color=vol_colors, opacity=0.6), row=2, col=1)
                    fig.update_layout(title=f"{pick}", height=430, margin=dict(l=10, r=10, t=40, b=10),
                                      xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02))
                    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.caption("提示：在「行业主线选股对比」页选择一个板块，可对其成分股做打分选股与 K 线对比。")
