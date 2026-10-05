# -*- coding: utf-8 -*-
"""
pages/4_交易系统决策.py —— 交易系统决策（模型匹配 + 仓位计算）
"""
import streamlit as st

import config
from analysis import decision

st.set_page_config(page_title="交易系统决策", page_icon="🧭", layout="wide")
st.title("交易系统决策")

tab_model, tab_position = st.tabs(["模型匹配", "仓位计算器"])

# ---------------- 模型匹配 ----------------
with tab_model:
    st.subheader("模型匹配：一只票只套一个模型")
    # 支持从自选股池/复盘页跳转自动带入代码（st.query_params）
    qp_code = st.query_params.get("code", "") or ""
    c1, c2 = st.columns(2)
    code = c1.text_input("股票代码（6 位，如 600519）", value=qp_code or "600519",
                         key=f"decision_code_{qp_code}")
    model = c2.selectbox("套用模型", list(config.MODELS.keys()))

    m = config.MODELS[model]
    with st.expander(f"查看「{model}」模型规则", expanded=False):
        st.markdown(
            f"- **持有周期**：{m['cycle']}\n"
            f"- **触发条件**：{m['trigger']}\n"
            f"- **买点**：{m['buy']}\n"
            f"- **卖点**：{m['sell']}\n"
            f"- **止损**：{m['stop']}\n"
            f"- **仓位档**：{m['position']}"
        )

    if st.button("执行决策", type="primary"):
        with st.spinner("拉取历史 K 线并计算指标……"):
            res = decision.decide(code, model)
        if not res["ok"]:
            st.error(res["error"])
        else:
            i = res["indicators"]
            status_color = "🟢" if "符合" in res["status"] else ("🔴" if "回避" in res["status"] else "🟡")
            st.markdown(f"### {status_color} 结论：**{res['status']}**")

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("最新价", round(i["last"], 2))
            m2.metric("涨跌幅", f"{i['chg_pct']:+.2f}%")
            m3.metric("RSI14", round(i["rsi14"], 1))
            m4.metric("距60日高点回撤", f"{i['drawdown_60']:.1f}%")
            m5.metric("量比(今/5日均)", f"{i['vol_ratio_5d']:.2f}")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**命中条件**")
                if res["hit"]:
                    for h in res["hit"]:
                        st.markdown(f"- ✅ {h}")
                else:
                    st.markdown("- 无")
            with c2:
                st.markdown("**未满足条件**")
                if res["miss"]:
                    for m_ in res["miss"]:
                        st.markdown(f"- ⬜ {m_}")
                else:
                    st.markdown("- 无")

            p = res["prices"]
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("买点参考", p["买点参考"])
            a2.metric("卖点参考", p["卖点参考"])
            a3.metric("止损参考", p["止损参考"])
            a4.metric("止损幅度", f"{(p['买点参考'] - p['止损参考']) / p['买点参考'] * 100:.1f}%" if p["买点参考"] else "-")

            st.info(f"规则提示：{m['stop']}。下单前先写止损位，再按下方仓位计算器算好手数。")

# ---------------- 仓位计算器 ----------------
with tab_position:
    st.subheader("仓位计算器：单笔亏损预算 → 可买股数")
    st.caption("核心铁律：单笔亏损 ≤ 总资金 × 亏损预算比例；买入价与止损价先定，再反推手数。")
    c1, c2, c3, c4 = st.columns(4)
    total_capital = c1.number_input("总资金（元）", min_value=1000.0, value=100000.0, step=10000.0)
    risk_ratio = c2.number_input("单笔亏损预算比例（%）", min_value=0.1, max_value=10.0, value=config.DEFAULT_RISK_RATIO * 100, step=0.5) / 100
    buy_price = c3.number_input("买入价（元）", min_value=0.01, value=10.0, step=0.1)
    stop_price = c4.number_input("止损价（元）", min_value=0.01, value=9.5, step=0.1)
    tier = st.selectbox("当前仓位档位（用于超限校验）", list(config.POSITION_TIERS.keys()), index=2)

    if st.button("计算仓位", type="primary"):
        r = decision.position_calc(total_capital, risk_ratio, buy_price, stop_price, tier)
        if "error" in r:
            st.error(r["error"])
        else:
            g1, g2, g3, g4, g5 = st.columns(5)
            g1.metric("可买股数（整手）", r["shares"])
            g2.metric("占用资金", f"{r['cost']:,.0f} 元")
            g3.metric("占总资金", f"{r['ratio']:.0%}")
            g4.metric("单笔最大亏损", f"{r['max_loss']:,.0f} 元")
            g5.metric("每股风险", f"{r['risk_per_share']:.3f} 元")
            if r["warn"]:
                st.warning(r["warn"])
            else:
                st.success("仓位在所选档位范围内，符合交易系统规矩。")

st.markdown("---")
st.caption("决策输出基于公开行情与简化启发式规则，仅供个人复盘参考，不构成投资建议。")
