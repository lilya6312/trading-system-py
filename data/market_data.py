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

    return _cached("index_spot", producer, ttl=60)


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


# ---------------- 5.5) 行业列表（90 细分 + 31 宽行业合并） ----------------
# 同花顺细分行业名 → 东财/腾讯宽行业名（成分股/行情接口只认宽行业名）
THS_TO_WIDE = {
    # 电子
    "半导体": "电子", "光学光电子": "电子", "消费电子": "电子", "其他电子": "电子",
    "元件": "电子", "电子化学品": "电子",
    # 食品饮料
    "白酒": "食品饮料", "饮料制造": "食品饮料", "食品加工制造": "食品饮料",
    "农产品加工": "食品饮料",
    # 家用电器
    "白色家电": "家用电器", "黑色家电": "家用电器", "厨卫电器": "家用电器",
    "小家电": "家用电器",
    # 电力设备
    "电池": "电力设备", "电网设备": "电力设备", "风电设备": "电力设备",
    "光伏设备": "电力设备", "电机": "电力设备", "其他电源设备": "电力设备",
    # 医药生物
    "化学制药": "医药生物", "生物制品": "医药生物", "中药": "医药生物",
    "医疗服务": "医药生物", "医疗器械": "医药生物", "医药商业": "医药生物",
    # 有色金属
    "贵金属": "有色金属", "工业金属": "有色金属", "小金属": "有色金属",
    "能源金属": "有色金属", "金属新材料": "有色金属",
    # 通信 / 计算机 / 汽车
    "通信服务": "通信", "通信设备": "通信",
    "软件开发": "计算机", "IT服务": "计算机", "计算机设备": "计算机",
    "汽车整车": "汽车", "汽车零部件": "汽车", "汽车服务及其他": "汽车",
    # 基础化工
    "化学原料": "基础化工", "化学制品": "基础化工", "化学纤维": "基础化工",
    "农化制品": "基础化工", "塑料制品": "基础化工", "橡胶制品": "基础化工",
    "非金属材料": "基础化工",
    # 能源
    "煤炭开采加工": "煤炭",
    "石油加工贸易": "石油石化", "油气开采及服务": "石油石化", "燃气": "石油石化",
    # 金融
    "银行": "银行", "保险": "非银金融", "证券": "非银金融", "多元金融": "非银金融",
    # 周期 / 制造
    "钢铁": "钢铁", "房地产": "房地产", "建筑装饰": "建筑装饰",
    "建筑材料": "建筑材料", "环保设备": "环保", "环境治理": "环保",
    "港口航运": "交通运输", "公路铁路运输": "交通运输", "机场航运": "交通运输",
    "物流": "交通运输",
    "轨交设备": "机械设备", "工程机械": "机械设备", "通用设备": "机械设备",
    "专用设备": "机械设备", "自动化设备": "机械设备",
    "军工电子": "国防军工", "军工装备": "国防军工",
    "服装家纺": "纺织服饰", "纺织制造": "纺织服饰",
    "家居用品": "轻工制造", "包装印刷": "轻工制造", "造纸": "轻工制造",
    "零售": "商贸零售", "贸易": "商贸零售", "互联网电商": "商贸零售",
    "旅游及酒店": "社会服务", "教育": "社会服务", "其他社会服务": "社会服务",
    "养殖业": "农林牧渔", "种植业与林业": "农林牧渔",
    "游戏": "传媒", "文化传媒": "传媒", "影视院线": "传媒",
    "综合": "综合",
}
# 反向：宽行业名 → 同花顺细分名（板块历史接口用；优先常见细分）
WIDE_TO_THS_DEFAULT = {
    "医药生物": "医药商业", "食品饮料": "食品加工制造", "汽车": "汽车整车",
    "美容护理": "美容护理", "银行": "银行", "房地产": "房地产",
    "公用事业": "电力", "交通运输": "公路铁路运输", "农林牧渔": "种植业与林业",
    "电力设备": "电网设备", "有色金属": "工业金属", "电子": "消费电子",
    "计算机": "软件开发", "通信": "通信设备", "传媒": "文化传媒",
    "国防军工": "军工装备", "机械设备": "通用设备", "基础化工": "化学制品",
    "钢铁": "钢铁", "煤炭": "煤炭开采加工", "石油石化": "石油加工贸易",
    "建筑装饰": "建筑装饰", "建筑材料": "建筑材料", "环保": "环境治理",
    "商贸零售": "零售", "社会服务": "旅游及酒店", "家用电器": "白色家电",
    "纺织服饰": "服装家纺", "轻工制造": "家居用品", "综合": "综合",
    "非银金融": "证券",
}

# 同花顺细分行业名（缓存；接口不可达时用内置表兜底）
_THS_NAMES_FALLBACK = list(THS_TO_WIDE.keys()) + ["美容护理", "综合"]


def get_all_industries() -> list[str]:
    """
    完整行业列表（页面下拉用）：
    同花顺 90 细分行业名优先（成分股经 THS_TO_WIDE 映射回宽行业取数），
    接口不可达时回退东财/腾讯宽行业名。
    """
    try:
        if AK_AVAILABLE:
            df = getattr(ak, "stock_board_industry_name_ths")()
            if df is not None and not df.empty:
                names = [str(x) for x in df["name"]]
                if names:
                    return names
    except Exception:  # noqa: BLE001
        pass
    return _THS_NAMES_FALLBACK


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
    # 同花顺细分行业名 → 宽行业名（东财/腾讯接口只认宽行业）
    wide = THS_TO_WIDE.get(industry, industry)

    def producer():
        if AK_AVAILABLE:
            try:
                df = getattr(ak, "stock_board_industry_cons_em")(symbol=wide)
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass
        return _industry_cons_tx(wide)

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


# ---------------- 8) 个股搜索（代码 / 名称） ----------------
def search_stock(keyword: str, top: int = 10) -> pd.DataFrame:
    """
    按代码或名称模糊搜索 A 股：
      - 6 位纯数字 → 精确代码
      - 1-5 位数字 → 代码前缀
      - 其他 → 名称包含匹配
    返回候选表（代码/名称/最新价/涨跌幅），供"代码+名称搜索"输入框使用。
    """
    s = str(keyword or "").strip()
    if not s:
        return pd.DataFrame()
    spot = get_all_stock_spot()
    if spot is None or spot.empty:
        return pd.DataFrame()
    spot = spot.copy()
    spot["代码"] = spot["代码"].astype(str).str.zfill(6)
    name_col = "名称" if "名称" in spot.columns else "name"

    if s.isdigit() and len(s) == 6:
        m = spot[spot["代码"] == s]
        return m.head(top) if not m.empty else pd.DataFrame()
    if s.isdigit():
        m = spot[spot["代码"].str.startswith(s)]
        if not m.empty:
            return m.head(top)
    m = spot[spot[name_col].astype(str).str.contains(s, case=False, na=False)]
    return m.head(top)
