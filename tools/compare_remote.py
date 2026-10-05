# -*- coding: utf-8 -*-
"""对比本地工程与 GitHub 仓库（raw）的文件内容是否一致。"""
import urllib.request, os, sys

BASE = "https://raw.githubusercontent.com/lilya6312/trading-system-py/main/"
ROOT = r"C:\Users\chenbo\Doubao\chats\2026-10-05\new-chat\trading-system-py"
FILES = [
    "main.py", "config.py", "requirements.txt", "README.md",
    "pages/1_大盘数据.py", "pages/2_主线行情个股分析.py", "pages/3_行业主线选股对比.py",
    "pages/4_交易系统决策.py", "pages/5_每日复盘.py", "pages/6_自选股池.py",
    "data/__init__.py", "data/market_data.py",
    "analysis/__init__.py", "analysis/market.py", "analysis/mainline.py",
    "analysis/stock.py", "analysis/decision.py", "analysis/review.py", "analysis/watchlist.py",
]

def main():
    ok = diff = err = 0
    for f in FILES:
        url = BASE + urllib.request.quote(f)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            remote = urllib.request.urlopen(req, timeout=40).read().decode("utf-8")
            local = open(os.path.join(ROOT, f), encoding="utf-8").read()
            if remote == local:
                ok += 1
                print("OK   ", f, len(local))
            else:
                diff += 1
                print("DIFF ", f, "remote=%d local=%d" % (len(remote), len(local)))
        except Exception as e:
            err += 1
            print("ERR  ", f, str(e)[:100])
    print("---- ok=%d diff=%d err=%d" % (ok, diff, err))

if __name__ == "__main__":
    main()
