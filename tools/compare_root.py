# -*- coding: utf-8 -*-
"""对比根文件与 pages/4。"""
import urllib.request, os

BASE = "https://raw.githubusercontent.com/lilya6312/trading-system-py/main/"
ROOT = r"C:\Users\chenbo\Doubao\chats\2026-10-05\new-chat\trading-system-py"
FILES = ["main.py", "config.py", "requirements.txt", "README.md",
         "pages/4_交易系统决策.py", "pages/5_每日复盘.py"]

for f in FILES:
    url = BASE + urllib.request.quote(f)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        remote = urllib.request.urlopen(req, timeout=40).read().decode("utf-8")
        local = open(os.path.join(ROOT, f), encoding="utf-8").read()
        same = remote == local
        print(("OK   " if same else "DIFF ") + f + " remote=%d local=%d" % (len(remote), len(local)))
    except Exception as e:
        print("ERR  " + f + " " + str(e)[:100])
