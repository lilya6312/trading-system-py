# -*- coding: utf-8 -*-
"""tools/test_pages.py —— Streamlit AppTest 页面渲染级验证（真实执行页面脚本）"""
import sys
import os
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from streamlit.testing.v1 import AppTest  # noqa: E402

PAGES = ["main.py",
         "pages/1_大盘数据.py",
         "pages/2_主线行情个股分析.py",
         "pages/3_行业主线选股对比.py",
         "pages/4_交易系统决策.py",
         "pages/5_每日复盘.py",
         "pages/6_自选股池.py"]

ok, bad = [], []
for page in PAGES:
    try:
        at = AppTest.from_file(os.path.join(ROOT, page), default_timeout=180)
        at.run()
        if at.exception:
            bad.append(f"{page}: EXCEPTION {at.exception}")
        else:
            ok.append(page)
    except Exception as e:  # noqa: BLE001
        bad.append(f"{page}: {type(e).__name__}: {e}")

print("OK:", *ok, sep="\n  ")
if bad:
    print("BAD:", *bad, sep="\n  ")
print(f"RESULT ok={len(ok)} bad={len(bad)}")
sys.exit(1 if bad else 0)
