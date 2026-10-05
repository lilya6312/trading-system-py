# -*- coding: utf-8 -*-
"""
pages/5_每日复盘.py —— 每日复盘
"""
from datetime import date

import pandas as pd
import streamlit as st

import config
from analysis import review as rv

st.set_page_config(page_title="每日复盘", page_icon="📝", layout="wide")
st.title("每日复盘")

tab_input, tab_history, tab_stats = st.tabs(["录入复盘", "历史记录", "统计与改进"])

# ---------------- 录入 ----------------
with tab_input:
    st.subheader("新增一条复盘")
    with st.form("review_form"):
        c1, c2, c3, c4 = st.columns(4)
        d = c1.date_input("日期", value=date.today())
        code = c2.text_input("标的代码", value="")
        name = c3.text_input("标的名称", value="")
        industry = c4.text_input("所属板块/行业", value="")

        c5, c6 = st.columns(2)
        model = c5.selectbox("套用模型", ["超短/短线", "波段", "中线", "长线", "超跌反弹", "右侧交易", "无纪律操作"])
        position = c6.selectbox("仓位档", list(config.POSITION_TIERS.keys()) + ["<10%", "10-20%", "20-30%", "30-50%", "50-80%", ">80%"])

        buy_reason = st.text_area("买入依据（信号＋阶段，写具体：什么信号、什么阶段、为什么买）", height=80)
        c7, c8, c9 = st.columns(3)
        pnl_pct = c7.number_input("盈亏（%，正盈负亏）", min_value=-100.0, max_value=500.0, value=0.0, step=1.0)
        emotion = c8.slider("情绪评分（1-5，越高越冲动）", 1, 5, 3)
        sell_reason = c9.selectbox("卖出原因", config.SELL_CONDITIONS + ["未卖出/持有中"])

        lesson = st.text_area("教训 / 改进（框架问题还是偶然错判？下次怎么改）", height=80)

        submitted = st.form_submit_button("保存复盘", type="primary")
        if submitted:
            row = {
                "date": str(d), "code": code, "name": name, "industry": industry,
                "model": model, "buy_reason": buy_reason, "position": position,
                "sell_reason": sell_reason, "pnl_pct": pnl_pct,
                "emotion": emotion, "lesson": lesson,
            }
            rv.add_review(row)
            st.success("已保存。复盘的目的是区分框架问题与偶然错判。")

# ---------------- 历史 ----------------
with tab_history:
    st.subheader("历史复盘记录")
    df = rv.load_reviews()
    if df.empty:
        st.info("还没有复盘记录，先在上方录入第一条。")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            "导出 CSV", data=rv.to_csv(df), file_name=f"reviews_{date.today()}.csv",
            mime="text/csv",
        )

        # 复盘对接决策页：选择一条记录一键再分析
        st.markdown("---")
        st.subheader("复盘再分析")
        with_code = df[df["code"].astype(str).str.len() >= 6] if not df.empty else df
        if with_code.empty:
            st.info("暂无带标的代码的复盘记录，无法跳转决策页。")
        else:
            options = with_code.apply(
                lambda r: f"{r['date']} | {r['code']} {r['name']} | {r['model']}", axis=1
            ).tolist()
            sel = st.selectbox("选择一条复盘记录，前往决策页自动带入该标的", options)
            if st.button("前往决策页分析", type="primary"):
                code = str(sel).split("|")[1].strip().split(" ")[0]
                st.query_params["code"] = code
                st.switch_page("pages/4_交易系统决策.py")

# ---------------- 统计 ----------------
with tab_stats:
    st.subheader("统计与改进")
    df = rv.load_reviews()
    if df.empty:
        st.info("录入复盘后这里会展示胜率、盈亏与情绪分析。")
    else:
        stats = rv.review_stats(df)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("总笔数", stats["总笔数"])
        c2.metric("胜率", f"{stats['胜率']}%")
        c3.metric("累计盈亏%", f"{stats['累计盈亏%']:+.2f}")
        c4.metric("平均盈亏%", f"{stats['平均盈亏%']:+.2f}")

        if stats.get("模型胜率"):
            st.markdown("**各模型胜率**")
            mdf = pd.DataFrame(list(stats["模型胜率"].items()), columns=["模型", "胜率%"])
            st.bar_chart(mdf.set_index("模型"))

        if stats.get("冲动交易占比") is not None:
            st.markdown("**情绪影响**")
            st.markdown(
                f"- 冲动交易（情绪≥4）占比：**{stats['冲动交易占比']}%**，平均盈亏 "
                f"**{stats['冲动交易均盈亏%']:+.2f}%**\n"
                f"- 冷静交易平均盈亏 **{stats['冷静交易均盈亏%']:+.2f}%**"
            )

        st.markdown("**盯盘与信息清单**（每周对照检查一次）")
        for s in config.INFO_SOURCES:
            st.markdown(f"- ☐ {s}")

st.markdown("---")
st.caption("复盘数据保存在本地 data/reviews.json，换机器不共享。")
