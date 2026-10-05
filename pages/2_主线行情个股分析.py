# -*- coding: utf-8 -*-
"""
pages/2_主线行情个股分析.py —— 主线行情与个股分析
"""
import streamlit as st

from analysis import mainline

st.set_page_config(page_title="主线行情个股分析", page_icon="🔥", layout="wide")
st.title("主线行情个股分析")

res = mainline.mainline_ranking(top_n=8)
for err in res.get("errors", []):
    st.warning(err)

if res["strong"]:
    st.success("**当前强主线候选**：" + " / ".join(res["strong"]))
else:
    st.info("暂无明显强主线（板块内涨停 < 2 家且无 2 连板），建议空仓或小仓观望。")

st.subheader("板块强度排行")
df = res.get("ranking")
if df is not None and not df.empty:
    st.dataframe(df, use_container_width=True, hide_index=True)
    with st.expander("如何看懂主线评分"):
        st.markdown(
            "主线评分 = 40%×板块当日涨幅排名 + 30%×板块内涨停家数 + 20%×上涨家数占比 + 10%×连板高度。\n\n"
            "**新主线三特征**：\n"
            "1. 板块容量大（总市值居前）；\n"
            "2. 新板块或调整很久的老板块；\n"
            "3. 指数大幅调整时跌幅可控、低位点火。\n\n"
            "**点火信号**：指数调整低位板块集体涨停、千亿龙头涨停＝点火；指数新高附近涨停＝加速赶顶。"
        )
else:
    st.error("板块数据获取失败，请检查网络后重试。")

st.markdown("---")
st.caption("提示：在「行业主线选股对比」页选择一个板块，可对其成分股做打分选股与 K 线对比。")
