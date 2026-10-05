# -*- coding: utf-8 -*-
"""
tools/smoke_test.py —— 全量模块冒烟测试
每个模块执行一次最小可验证调用；网络接口失败会降级，不视为失败。
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def t(name, fn):
    try:
        r = fn()
        PASS.append(f"{name}: OK {r if isinstance(r, str) else ''}")
    except Exception as e:  # noqa: BLE001
        FAIL.append(f"{name}: FAIL {type(e).__name__}: {e}")


# 1) 配置
import config
t("config", lambda: f"models={len(config.MODELS)} phases={list(config.MARKET_PHASE_RULES)}")

# 2) 数据层
from data import market_data as md
t("market_data", lambda: f"spot_cols={len(md.get_all_stock_spot().columns)}")

# 3) 精确涨跌停
from analysis import limit
spot = md.get_all_stock_spot()
t("limit", lambda: f"zt={limit.count_limit(spot, up=True)} dt={limit.count_limit(spot, up=False)}")

# 4) 情绪面
from analysis import sentiment
t("sentiment", lambda: f"score={sentiment.sentiment_snapshot().get('情绪评分')}")

# 5) 主线（RPS + 生命周期）
from analysis import mainline
t("mainline", lambda: f"strong={mainline.mainline_ranking(top_n=4).get('strong')}")

# 6) 决策（含大盘阶段联动）
from analysis import decision
t("decision", lambda: f"status={decision.decide('600519', '波段', phase='强势')['status']}")

# 7) 信号扫描
from analysis import signal_scan
t("signal_scan", lambda: f"ready={signal_scan.scan_signals(phase='强势', extra_codes=['600519']).get('ready')}")

# 8) 组合风控
from analysis import risk
t("risk", lambda: f"cap={risk.phase_cap('弱势')['cap']}")

# 9) 基本面排雷
from analysis import fundamental
t("fundamental", lambda: f"warn={fundamental.fundamental_snapshot('600519').get('warnings')}")

# 10) 复盘（计划-执行）
from analysis import review as rv
t("review", lambda: f"fields={len(rv.REVIEW_FIELDS)}")

print("=" * 50)
for x in PASS:
    print("[PASS]", x)
for x in FAIL:
    print("[FAIL]", x)
print("=" * 50)
print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
sys.exit(1 if FAIL else 0)
