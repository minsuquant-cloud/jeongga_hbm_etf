# -*- coding: utf-8 -*-
"""
etf/hist_data.py — 12.5년 장기 시세 로더 (FnGuide 데이터셋)

왜 필요한가
-----------
기존 `run_tracking.py`·`run_stress.py`는 pykrx/FDR로 **최근 1년**을 받아 쓴다.
그 1년이 하필 +207% 초강세장이라 "험한 날" 표본이 사실상 없었다. 실측 MDD도
현재진행형 조정장 하나(-30.8%)뿐이었다.

`D:\\data`의 FnGuide 데이터셋에는 2014-01~2026-06 12.5년이 있고, 여기엔 반도체가
실제로 무너진 구간들이 들어 있다 — 2018년 사이클 붕괴, 2020년 코로나, 2022년 금리인상기.
지금까지의 숫자가 그때도 버티는지 재려면 이 데이터가 필요하다.

상장 시점 처리
--------------
12종목의 데이터 시작일이 제각각이다(2014년 6종목 / 2018~2023년 6종목).
**그 시점에 존재하지 않던 종목을 소급 편입하면 그 자체가 룩어헤드다.**
그래서 매 시점 살아있는 종목만으로 비중을 재정규화한다(`pit_weights`).
편입 종목 수는 결과에 함께 기록해 어느 구간이 몇 종목 기준인지 드러나게 한다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# 융합본(_live: FnGuide 12.5년 + 실시간)이 있으면 우선 사용.
_LIVE, _SNAP = Path(r"D:/data/_live"), Path(r"D:/data/_derived")
DERIVED = Path(os.environ.get(
    "QUANT_DATA_DERIVED",
    _LIVE if (_LIVE / "price_adj_close.parquet").exists() else _SNAP))
BASE = Path(__file__).resolve().parent.parent
FINAL = BASE / "data" / "processed" / "구성표_실사확정_20260725.csv"

FIELDS = {"Open": "price_adj_open", "High": "price_adj_high",
          "Low": "price_adj_low", "Close": "price_adj_close",
          "Volume": "price_volume", "Value": "price_value_traded"}


def load_composition() -> pd.Series:
    """확정 구성표 → 코드별 목표비중(합 1)."""
    c = pd.read_csv(FINAL, encoding="utf-8-sig")
    c["코드"] = c["코드"].astype(str).str.zfill(6)
    w = pd.Series((c["편입비중(%)"] / 100.0).values, index=c["코드"].tolist())
    return w / w.sum()


def load_names() -> pd.Series:
    c = pd.read_csv(FINAL, encoding="utf-8-sig")
    c["코드"] = c["코드"].astype(str).str.zfill(6)
    return c.set_index("코드")["종목명"]


def load_field(field: str, codes: list[str]) -> pd.DataFrame:
    """Date × Code 와이드 시세. field는 FIELDS의 키."""
    df = pd.read_parquet(DERIVED / f"{FIELDS[field]}.parquet")
    have = [c for c in codes if c in df.columns]
    return df[have].astype("float64")


def pit_weights(close: pd.DataFrame, target: pd.Series) -> pd.DataFrame:
    """매 시점 '살아있는 종목'만으로 재정규화한 비중.

    상장 전·상장폐지 후에는 비중 0. 남은 종목끼리 목표비중 비율을 유지한다.
    """
    alive = close.notna()
    w = alive.astype(float).mul(target.reindex(close.columns).fillna(0.0), axis=1)
    total = w.sum(axis=1).replace(0.0, pd.NA)
    return w.div(total, axis=0).fillna(0.0)


def build_index(start: str = "2014-01-02", end: str | None = None,
                base: float = 1000.0) -> pd.DataFrame:
    """PIT 재정규화 지수 + 회전율.

    반환: level(지수), turnover(비중 변화 절반), n_stocks(당시 편입 수)
    """
    target = load_composition()
    close = load_field("Close", target.index.tolist())
    close = close.loc[start:end] if end else close.loc[start:]

    w = pit_weights(close, target)
    ret = close.pct_change().fillna(0.0)
    # 당일 수익률은 전일 비중으로 얻는다 — 당일 비중을 쓰면 미래를 쓰는 셈이다.
    port_ret = (w.shift(1).fillna(0.0) * ret).sum(axis=1)

    level = base * (1 + port_ret).cumprod()
    turnover = (w - w.shift(1)).abs().sum(axis=1) / 2
    return pd.DataFrame({"level": level, "turnover": turnover,
                         "n_stocks": (w > 0).sum(axis=1), "reason": ""})
