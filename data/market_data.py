# -*- coding: utf-8 -*-
"""
data/market_data.py —— 多源行情数据层
========================================
设计：AkShare 优先，失败时自动降级到新浪/腾讯公开接口，页面与分析层无感知。

数据源矩阵（已验证）：
| 数据              | 首选（AkShare）      | 降级                        |
|-------------------|----------------------|-----------------------------|
| 指数实时          | stock_zh_index_spot_em(东财) | 新浪 hq.sinajs.cn s_*  |
| 指数日线          | stock_zh_index_daily(新浪)   | -（本身即新浪）             |
| 个股历史日线      | stock_zh_a_hist(东财) | 新浪 getKLineData JSONP     |
| 全市场快照        | stock_zh_a_spot_em(东财)     | 新浪 Market_Center 分页     |
| 行业板块行情      | stock_board_industry_spot_em(东财) | 腾讯 getRank          |
| 板块成分股        | stock_board_industry_cons_em(东财) | 腾讯 getBoardRankList |
| 涨停池            | stock_zt_pool_em(东财) | 全市场快照近似（≥9.8%）     |

所有函数带 TTL 缓存与重试，任一源失败不阻塞其余功能。
"""
from __future__ import annotations

import json
import math
import re
import time
from urllib.parse import quote

import pandas as pd
import requests

try:
    import akshare as ak
    AK_AVAILABLE = True
except Exception:  # pragma: no cover
    ak = None
    AK_AVAILABLE = False

from config import LIMIT_UP_RATIO, RETRY_TIMES

# ---------------- 请求基础设施 ----------------
_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}
_H_SINA = {**_UA, "Referer": "https://finance.sina.com.cn/"}
_H_TX = {**_UA, "Referer": "https://gu.qq.com/"}

_cache: dict[str, tuple[float, pd.DataFrame | None]] = {}


def _cached(key: str, producer, ttl: int = 60):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    for attempt in range(RETRY_TIMES + 1):
        try:
            df = producer()
            if df is not None and not df.empty:
                _cache[key] = (now, df)
                return df
        except Exception:
            if attempt < RETRY_TIMES:
                time.sleep(1.5)
            continue
    return hit[1] if hit else None


def _http(url: str, headers: dict, timeout: int = 12) -> str:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def normalize_code(code) -> str:
    """'600519'/'sh600519'/'SH600519' → '600519'"""
    s = str(code).strip().lower()
    for p in ("sh", "sz", "bj"):
        s = s.replace(p, "")
    return s.zfill(6) if s.isdigit() else s


def _sina_symbol(code: str) -> str:
    code = normalize_code(code)
    return ("sh" if code[0] in "69" else "sz") + code


# ---------------- 1) 指数实时 ----------------
INDEX_SINA = {
    "上证指数": "s_sh000001", "科创50": "s_sh000688",
    "深证成指": "s_sz399001", "创业板指": "s_sz399006",
    "沪深300": "s_sh000300", "中证500": "s_sh000905",
}


def _index_spot_ak() -> pd.DataFrame:
    parts = []
    for series in ("上证系列指数", "深证系列指数"):
        df = getattr(ak, "stock_zh_index_spot_em")(symbol=series)
        if df is not None and not df.empty:
            parts.append(df)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _index_spot_sina() -> pd.DataFrame:
    """新浪实时指数：var hq_str_s_sh000001="上证指数,最新,涨跌额,涨跌幅%,成交量(手),成交额(万元)";"""
    url = "https://hq.sinajs.cn/list=" + ",".join(INDEX_SINA.values())
    txt = _http(url, _H_SINA)
    rows = []
    for m in re.finditer(r'hq_str_s_(\w+)="([^"]*)"', txt):
        sym, body = m.group(1), m.group(2)
        f = body.split(",")
        if len(f) < 6:
            continue
        name = f[0]
        code = re.sub(r"(sh|sz|bj)", "", sym)
        rows.append({
            "名称": name, "代码": code,
            "最新价": float(f[1]), "涨跌幅": float(f[3]),
            "成交额": float(f[5]) * 1e4,  # 万元 → 元
        })
    return pd.DataFrame(rows)


def get_index_spot() -> pd.DataFrame | None:
    def producer():
        if AK_AVAILABLE:
            try:
                return _index_spot_ak()
            except Exception:
                pass
        return _index_spot_sina()

    return _cached("index_spot", producer)


# ---------------- 2) 指数日线（新浪，AkShare 原生可用） ----------------
def get_index_daily(code: str, days: int = 120) -> pd.DataFrame | None:
    def producer():
        if AK_AVAILABLE:
            df = getattr(ak, "stock_zh_index_daily")(symbol=code)
            if df is not None and not df.empty:
                return df.tail(days).copy()
        return pd.DataFrame()

    return _cached(f"index_daily:{code}:{days}", producer)


# ---------------- 3) 个股历史日线 ----------------
def _stock_hist_sina(code: str, days: int) -> pd.DataFrame:
    sym = _sina_symbol(code)
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/"
           f"CN_MarketDataService.getKLineData?symbol={sym}&scale=240&ma=no&datalen={days}")
    txt = _http(url, _H_SINA)
    data = re.search(r"\((\[.*\])\)", txt, re.S)
    if not data:
        return pd.DataFrame()
    arr = json.loads(data.group(1))
    df = pd.DataFrame(arr)
    df = df.rename(columns={"day": "日期", "open": "开盘", "close": "收盘",
                            "high": "最高", "low": "最低", "volume": "成交量"})
    for c in ("开盘", "收盘", "最高", "最低", "成交量"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["日期"] = pd.to_datetime(df["日期"])
    df["涨跌幅"] = (df["收盘"].pct_change() * 100).round(2)
    return df


def get_stock_hist(code: str, days: int = 250, adjust: str = "qfq") -> pd.DataFrame | None:
    def producer():
        if AK_AVAILABLE:
            try:
                df = getattr(ak, "stock_zh_a_hist")(
                    symbol=code, period="daily", start_date="19900101", adjust=adjust)
                if df is not None and not df.empty:
                    df = df.tail(days).copy()
                    df["日期"] = pd.to_datetime(df["日期"])
                    return df
            except Exception:
                pass
        return _stock_hist_sina(code, days)

    return _cached(f"stock_hist:{code}:{days}:{adjust}", producer)


# ---------------- 4) 全市场快照 ----------------
_PAGE_NUM = 100  # 新浪接口单页上限（实测传 200 也只返回 100）


def _all_spot_sina() -> pd.DataFrame:
    """新浪 Market_Center 并发分页拉全市场（5571 只 / 每页 100 ≈ 56 页，8 并发）。"""
    base = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    cnt_txt = _http(base + "Market_Center.getHQNodeStockCount?node=hs_a", _H_SINA)
    try:
        total = int(json.loads(cnt_txt))
    except Exception:  # noqa: BLE001
        total = 5600
    pages = max(1, math.ceil(total / _PAGE_NUM))

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch(page: int):
        url = (base + "Market_Center.getHQNodeData?"
               f"page={page}&num={_PAGE_NUM}&sort=changepercent&asc=0&node=hs_a&symbol=&_s_r_a=init")
        for _ in range(2):  # 单页失败重试一次
            try:
                arr = json.loads(_http(url, _H_SINA, timeout=15))
                if isinstance(arr, list) and arr:
                    return pd.DataFrame(arr)
            except Exception:  # noqa: BLE001
                continue
        return None

    frames = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch, p): p for p in range(1, pages + 1)}
        for fut in as_completed(futs):
            df = fut.result()
            if df is not None:
                frames.append(df)
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["code"])
    df = df.rename(columns={
        "code": "代码", "name": "名称", "trade": "最新价", "changepercent": "涨跌幅",
        "volume": "成交量", "amount": "成交额", "turnoverratio": "换手率",
    })
    for c in ("最新价", "涨跌幅", "成交量", "成交额", "换手率"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # 新浪无以下字段，统一置空，页面标注
    df["量比"] = pd.NA
    df["60日涨跌幅"] = pd.NA
    df["年初至今涨跌幅"] = pd.NA
    return df


def get_all_stock_spot() -> pd.DataFrame | None:
    def producer():
        if AK_AVAILABLE:
            try:
                df = getattr(ak, "stock_zh_a_spot_em")()
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass
        return _all_spot_sina()

    # 全市场快照重（~28 次请求），缓存 5 分钟
    return _cached("all_stock_spot", producer, ttl=300)


# ---------------- 5) 行业板块行情 ----------------
def _industry_spot_tx() -> pd.DataFrame:
    """腾讯行业板块排名。字段：板块名称/涨跌幅/换手率/总市值(流通)/领涨股票。"""
    url = ("https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank?"
           "board_type=hy&sort_type=price&direct=down&offset=0&count=100")
    txt = _http(url, _H_TX)
    obj = json.loads(txt)
    lst = (obj.get("data") or {}).get("rank_list") or []
    rows = []
    for it in lst:
        lzg = it.get("lzg") or {}
        rows.append({
            "板块代码": it.get("code", ""),
            "板块名称": it.get("name", ""),
            "涨跌幅": float(it.get("zdf", 0) or 0),
            "换手率": float(it.get("hsl", 0) or 0),
            "总市值": float(it.get("ltsz", 0) or 0) * 1e8,  # 亿 → 元
            "上涨家数": pd.NA, "下跌家数": pd.NA,
            "领涨股票": lzg.get("name", ""),
            "领涨股票-涨跌幅": float(lzg.get("zdf", 0) or 0),
        })
    return pd.DataFrame(rows)


def get_industry_spot() -> pd.DataFrame | None:
    def producer():
        if AK_AVAILABLE:
            try:
                df = getattr(ak, "stock_board_industry_spot_em")()
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass
        return _industry_spot_tx()

    return _cached("industry_spot", producer)


# ---------------- 6) 板块成分股 ----------------
def _industry_cons_tx(industry: str) -> pd.DataFrame:
    spot = get_industry_spot()
    if spot is None or spot.empty:
        return pd.DataFrame()
    m = spot[spot["板块名称"] == industry]
    if m.empty:
        return pd.DataFrame()
    board_code = str(m.iloc[0]["板块代码"])
    url = ("https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList?"
           f"board_code={quote(board_code)}&sort_type=price&direct=down&offset=0&count=200")
    txt = _http(url, _H_TX)
    obj = json.loads(txt)
    lst = (obj.get("data") or {}).get("rank_list") or []
    rows = []
    for it in lst:
        code = it.get("code", "")
        if not code:
            continue
        rows.append({
            "代码": normalize_code(code),
            "名称": it.get("name", ""),
            "最新价": float(it["zxj"]) if it.get("zxj") else pd.NA,
            "涨跌幅": float(it["zdf"]) if it.get("zdf") is not None else pd.NA,
            "换手率": float(it["hsl"]) if it.get("hsl") else pd.NA,
        })
    return pd.DataFrame(rows)


def get_industry_cons(industry: str) -> pd.DataFrame | None:
    def producer():
        if AK_AVAILABLE:
            try:
                df = getattr(ak, "stock_board_industry_cons_em")(symbol=industry)
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass
        return _industry_cons_tx(industry)

    return _cached(f"industry_cons:{industry}", producer)


# ---------------- 7) 涨停池 ----------------
def _zt_pool_approx() -> pd.DataFrame:
    """东财涨停池不可达时，从全市场快照近似筛选（≥9.8%），标注近似。"""
    spot = get_all_stock_spot()
    if spot is None or spot.empty:
        return pd.DataFrame()
    df = spot[spot["涨跌幅"] >= LIMIT_UP_RATIO * 100].copy()
    if df.empty:
        return df
    out = pd.DataFrame({
        "代码": df["代码"], "名称": df["名称"], "涨跌幅": df["涨跌幅"],
        "最新价": df["最新价"], "成交额": df["成交额"],
        "所属行业": pd.NA, "_近似": True,
    })
    return out


def get_zt_pool(trade_date: str | None = None) -> pd.DataFrame | None:
    def producer():
        if AK_AVAILABLE:
            try:
                if trade_date:
                    df = getattr(ak, "stock_zt_pool_em")(date=trade_date)
                else:
                    df = getattr(ak, "stock_zt_pool_em")()
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass
        return _zt_pool_approx()

    return _cached(f"zt_pool:{trade_date or 'latest'}", producer)
