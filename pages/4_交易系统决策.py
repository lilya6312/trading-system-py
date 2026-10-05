# -*- coding: utf-8 -*-
"""
pages/4_交易系统决策.py —— 交易系统决策（大盘联动 + 信号扫描 + 组合风控 + 仓位计算）
"""
import pandas as pd
import streamlit as st

import config
from analysis import decision, fundamental, risk
from analysis import market as mkt

st.set_page_config(page_title="交易系统决策", page_icon="🧭", layout="wide")
st.title("交易系统决策")

# 大盘阶段（供联动与风控使用）
_phase = None
try:
    _ov = mkt.market_overview()
    _phase = _ov.get("phase", {}).get("phase") if _ov.get("phase") else None
except Exception:  # noqa: BLE001
    pass
if _phase:
    st.caption(f"当前大盘阶段：**{_phase}**（弱势/冰点时自动封禁短线与右侧交易开仓）")

tab_model, tab_scan, tab_risk, tab_position = st.tabs(
    ["模型匹配", "盘后信号扫描", "组合风控", "仓位计算器"])

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
            res = decision.decide(code, model, phase=_phase)
        if not res["ok"]:
            st.error(res["error"])
        else:
            i = res["indicators"]
            status_color = "🟢" if "符合" in res["status"] else ("🔴" if "回避" in res["status"] else "🟡")
            st.markdown(f"### {status_color} 结论：**{res['status']}**")
            if res.get("env_block"):
                st.error(res["env_block"])

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

            # 基本面排雷（中线/长线必查）
            if model in ("中线", "长线"):
                with st.spinner("拉取财务数据排雷……"):
                    fd = fundamental.fundamental_snapshot(code)
                if fd["ok"]:
                    fin, info = fd["fin"], fd["info"]
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
                    st.caption("基本面数据暂不可达，跳过排雷（不构成买入依据）。")

# ---------------- 盘后信号扫描 ----------------
with tab_scan:
    st.subheader("盘后信号扫描：自选股池 + 强主线成分股")
    st.caption("对代码池自动跑六大模型，每只票只保留最强的一个信号（铁律四）。"
               "弱势/冰点阶段，短线与右侧交易自动封禁。")
    from analysis import signal_scan as ss

    extra = st.text_input("额外代码（逗号分隔，可选）", value="", key="scan_extra")
    if st.button("开始扫描", type="primary"):
        codes = [c.strip() for c in extra.split(",") if c.strip()]
        with st.spinner("扫描中（并发拉取历史 K 线，约 30-60 秒）……"):
            sr = ss.scan_signals(phase=_phase, extra_codes=codes)
        for err in sr["errors"]:
            st.warning(err)
        if sr["table"] is not None and not sr["table"].empty:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("扫描池", sr["pool_size"])
            r2.metric("符合入场", sr["ready"], delta_color="inverse")
            r3.metric("等待跟踪", sr["waiting"])
            r4.metric("大盘封禁", sr["blocked"])
            st.dataframe(
                sr["table"][["代码", "名称", "模型", "状态", "命中", "买点", "止损", "建议仓位", "信号强度"]],
                use_container_width=True, hide_index=True)
            st.caption("点击信号下方「模型匹配」页，输入代码可看完整命中明细与基本面排雷。")
        else:
            st.info("未扫描到可用信号。")

# ---------------- 组合风控 ----------------
with tab_risk:
    st.subheader("组合风控：总仓位 / 单主线集中度 / 回撤熔断 / 连亏降档")
    from analysis import review as rv

    rc1, rc2 = st.columns(2)
    total_capital = rc1.number_input("总资金（元）", min_value=1000.0, value=100000.0, step=10000.0)
    n_hold = rc2.number_input("持仓只数", min_value=0, max_value=20, value=2, step=1)
    st.markdown("**当前持仓市值与行业**（行业用于集中度检查）")
    holdings = []
    for i in range(int(n_hold)):
        h1, h2, h3 = st.columns([1, 1, 2])
        mv = h1.number_input(f"持仓{i+1}市值", min_value=0.0, value=0.0, step=10000.0, key=f"mv{i}")
        ind = h2.text_input(f"持仓{i+1}行业", value="", key=f"ind{i}")
        nm = h3.text_input(f"持仓{i+1}名称", value="", key=f"nm{i}")
        if mv > 0:
            holdings.append({"market_value": mv, "industry": ind, "name": nm})

    if st.button("生成风控报告", type="primary"):
        reviews = rv.load_reviews()
        rr = risk.full_risk_report(_phase, total_capital, holdings, reviews)
        # 阶段仓位
        ph = rr["phase"]
        st.markdown(f"**大盘阶段**：{ph['phase']} → 允许总仓位 **{ph['cap']:.0%}**，推荐 {ph['recommend']}")
        # 总仓位
        t = rr["total"]
        if t.get("ratio") is not None:
            if t["ok"]:
                st.success(f"总仓位 {t['ratio']:.0%} ≤ {t['cap']:.0%}，符合阶段上限。")
            else:
                st.error(t["warn"])
        # 集中度
        cc = rr["concentration"]
        if cc.get("items"):
            st.markdown(f"**单主线集中度**（上限 {risk.MAX_LINE_CONCENTRATION:.0%}）：")
            st.dataframe(pd.DataFrame(cc["items"]), use_container_width=True, hide_index=True)
        if cc.get("warn"):
            st.error(cc["warn"])
        # 回撤熔断
        dd = rr["drawdown"]
        if dd["triggered"]:
            st.error(dd["warn"])
        else:
            st.success(f"账户回撤 {dd['dd']}% < {risk.DRAWDOWN_TRIGGER:.0%}，未触发熔断。")
        # 连亏降档
        stk = rr["streak"]
        if stk["triggered"]:
            st.error(stk["warn"])
        elif stk["streak"] > 0:
            st.info(f"最近连续亏损 {stk['streak']} 笔，再亏 {risk.LOSS_STREAK_TRIGGER - stk['streak']} 笔触发降档。")
        else:
            st.success("最近无连亏记录。")

# ---------------- 仓位计算器 ----------------
with tab_position:
    st.subheader("仓位计算器：单笔亏损预算 → 可买股数")
    st.caption("核心铁律：单笔亏损 ≤ 总资金 × 亏损预算比例；买入价与止损价先定，再反推手数。")
    c1, c2, c3, c4 = st.columns(4)
    pc1 = c1.number_input("总资金（元）", min_value=1000.0, value=100000.0, step=10000.0, key="pos_cap")
    risk_ratio = c2.number_input("单笔亏损预算比例（%）", min_value=0.1, max_value=10.0, value=config.DEFAULT_RISK_RATIO * 100, step=0.5, key="pos_rr") / 100
    buy_price = c3.number_input("买入价（元）", min_value=0.01, value=10.0, step=0.1, key="pos_buy")
    stop_price = c4.number_input("止损价（元）", min_value=0.01, value=9.5, step=0.1, key="pos_stop")
    tier = st.selectbox("当前仓位档位（用于超限校验）", list(config.POSITION_TIERS.keys()), index=2)

    if st.button("计算仓位", type="primary"):
        r = decision.position_calc(pc1, risk_ratio, buy_price, stop_price, tier)
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
