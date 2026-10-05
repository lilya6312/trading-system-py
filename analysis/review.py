# -*- coding: utf-8 -*-
"""
analysis/review.py —— 每日复盘存储与统计
=========================================
复盘记录以 JSON 持久化到 data/reviews.json（相对项目根目录），
提供增、查、统计（胜率 / 累计盈亏 / 模型胜率 / 情绪影响）与 CSV 导出。
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import date

import pandas as pd

import config

REVIEW_FIELDS = ["date", "code", "name", "industry", "model", "buy_reason",
                 "position", "sell_reason", "pnl_pct", "emotion", "lesson"]


def _path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        config.REVIEW_FILE)


def load_reviews() -> pd.DataFrame:
    """读取全部复盘记录（倒序），文件不存在或损坏时返回空表。"""
    p = _path()
    if not os.path.exists(p):
        return pd.DataFrame(columns=REVIEW_FIELDS)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        df = pd.DataFrame(data, columns=REVIEW_FIELDS)
        if not df.empty:
            df = df.sort_values("date", ascending=False).reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame(columns=REVIEW_FIELDS)


def add_review(row: dict) -> None:
    """新增一条复盘记录。"""
    df = load_reviews()
    clean = {k: row.get(k, "") for k in REVIEW_FIELDS}
    clean["date"] = str(clean.get("date") or date.today())
    new = pd.DataFrame([clean], columns=REVIEW_FIELDS)
    df = pd.concat([df, new], ignore_index=True)
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(df.to_dict("records"), f, ensure_ascii=False, indent=2)


def review_stats(df: pd.DataFrame) -> dict:
    """统计：笔数 / 胜率 / 累计盈亏 / 平均盈亏 / 模型胜率 / 情绪影响。"""
    if df is None or df.empty:
        return {}
    pnl = pd.to_numeric(df["pnl_pct"], errors="coerce").fillna(0)
    wins = int((pnl > 0).sum())
    stats = {
        "总笔数": len(df),
        "胜率": round(wins / len(df) * 100, 1) if len(df) else 0.0,
        "累计盈亏%": round(float(pnl.sum()), 2),
        "平均盈亏%": round(float(pnl.mean()), 2),
    }
    # 模型胜率
    if "model" in df.columns:
        model_pnl = df.groupby("model")["pnl_pct"].apply(
            lambda s: round(float((pd.to_numeric(s, errors="coerce") > 0).mean() * 100), 1)
        ).to_dict()
        stats["模型胜率"] = model_pnl
    # 情绪影响：情绪评分 >= 4 的冲动交易 vs 其余
    if "emotion" in df.columns:
        emo = pd.to_numeric(df["emotion"], errors="coerce")
        hot = pnl[emo >= 4]
        calm = pnl[emo < 4]
        stats["冲动交易占比"] = round(len(hot) / len(df) * 100, 1) if len(df) else 0.0
        stats["冲动交易均盈亏%"] = round(float(hot.mean()), 2) if len(hot) else 0.0
        stats["冷静交易均盈亏%"] = round(float(calm.mean()), 2) if len(calm) else 0.0
    return stats


def to_csv(df: pd.DataFrame) -> str:
    """导出 CSV 字符串（UTF-8 with BOM，Excel 可直接打开）。"""
    buf = io.StringIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()
