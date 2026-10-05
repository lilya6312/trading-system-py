# -*- coding: utf-8 -*-
"""
main.py —— 交易系统工作台入口
===============================
启动方式：在项目根目录执行  streamlit run main.py
侧边栏会列出 pages/ 下的五个模块：
  1 大盘数据  2 主线行情个股分析  3 行业主线选股对比  4 交易系统决策  5 每日复盘
  """
import streamlit as st

import config

st.set_page_config(page_title="个人交易系统工作台", page_icon="📈", layout="wide")

st.title("个人交易系统工作台")
st.caption("依据《个人交易系统手册 V1.0》实现：先看大盘，再谈主线，最后才是个股与仓位。")

# 七步闭环
steps = [
      "① 环境判断", "② 主线识别", "③ 模型匹配", "④ 仓位管理",
      "⑤ 买入执行", "⑥ 持有卖出", "⑦ 复盘进化",
]
cols = st.columns(7)
for col, s in zip(cols, steps):
      col.markdown(f"### {s}")

st.markdown("---")
st.subheader("五档仓位")
pos_rows = "\n".join(
      f"- **{k}**（{lo:.0%}-{hi:.0%}）：{desc}" for k, (lo, hi, desc) in config.POSITION_TIERS.items()
)
st.markdown(pos_rows)

st.subheader("十条交易铁律")
for i, rule in enumerate(config.IRON_RULES, 1):
      st.markdow# -*- coding: utf-8 -*-
"""
main.py —— 交易系统工作台入口
===============================
启动方式：在项目根目录执行  streamlit run main.py
侧边栏会列出 pages/ 下的五个模块：
  1 大盘数据  2 主线行情个股分析  3 行业主线选股对比  4 交易系统决策  5 每日复盘
"""
import streamlit as st

import config

st.set_page_config(page_title="个人交易系统工作台", page_icon="📈", layout="wide")

st.title("个人交易系统工作台")
st.caption("依据《个人交易系统手册 V1.0》实现：先看大盘，再谈主线，最后才是个股与仓位。")

# 七步闭环
steps = [
    "① 环境判断", "② 主线识别", "③ 模型匹配", "④ 仓位管理",
    "⑤ 买入执行", "⑥ 持有卖出", "⑦ 复盘进化",
]
cols = st.columns(7)
for col, s in zip(cols, steps):
    col.markdown(f"### {s}")

st.markdown("---")
st.subheader("五档仓位")
pos_rows = "\n".join(
    f"- **{k}**（{lo:.0%}-{hi:.0%}）：{desc}" for k, (lo, hi, desc) in config.POSITION_TIERS.items()
)
st.markdown(pos_rows)

st.subheader("十条交易铁律")
for i, rule in enumerate(config.IRON_RULES, 1):
    st.markdown(f"{i}. {rule}")

st.markdown("---")
st.info(
    "使用说明：左侧选择模块。所有数据来自 AkShare 公开行情接口，指标为简化启发式规则，"
    "仅用于个人复盘与决策参考，不构成任何投资建议。"
)
