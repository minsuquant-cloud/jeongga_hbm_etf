# -*- coding: utf-8 -*-
"""
etf/export_index.py — 지수를 OHLCV 시계열로 내보내 다른 도구가 쓰게 한다

왜 이렇게 하나
--------------
tech_dashboard에서 이 ETF를 하나의 종목처럼 보고 싶은데, 레포끼리 직접 import하면
서로 묶여버린다. 대신 **공용 데이터 루트(`D:\\data\\_index`)에 parquet로 내보내고**
소비하는 쪽이 가상 티커로 읽게 한다. 데이터가 인터페이스 역할을 하는 셈이다.

OHLCV를 어떻게 만드나
---------------------
지수는 종가 하나뿐이므로 나머지는 구성종목에서 합성한다.

    Close  = 지수 레벨 (분기 재고정, PIT 비중)
    O/H/L  = 종가 대비 구성종목 O/H/L 비율을 비중가중해 지수 종가에 적용
    Volume = 가중 거래대금 ÷ 지수 레벨 (유사 거래량 — OBV·MFI 같은 지표용)

고가·저가를 구성종목 고가·저가의 가중합으로 직접 만들면 안 된다. 종목마다 고점
시각이 달라 실제로는 동시에 성립하지 않는 값이 나오고, 지수 변동폭이 부풀려진다.
그래서 **비율**을 가중평균한 뒤 지수 종가에 곱한다.

    .venv/Scripts/python.exe etf/export_index.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.hist_data import (build_index, load_composition,  # noqa: E402
                           load_field, pit_weights)

TICKER = "JGHBM"          # 정가 HBM 지수 가상 티커
OUT = Path(r"D:/data/_index")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    target = load_composition()
    codes = target.index.tolist()

    bt = build_index()
    close = load_field("Close", codes).loc[bt.index]
    w = pit_weights(close, target)

    # 종가 대비 비율을 가중평균 → 지수 종가에 적용
    ratios = {}
    for field in ("Open", "High", "Low"):
        px = load_field(field, codes).loc[bt.index]
        ratios[field] = (px / close).mul(w).sum(axis=1).replace(0.0, float("nan"))

    val = load_field("Value", codes).loc[bt.index]
    weighted_value = (val * w).sum(axis=1)

    df = pd.DataFrame({
        "Open": bt["level"] * ratios["Open"],
        "High": bt["level"] * ratios["High"],
        "Low": bt["level"] * ratios["Low"],
        "Close": bt["level"],
        "Volume": (weighted_value / bt["level"]).fillna(0.0),
    }, index=bt.index)
    df.index.name = "Date"

    # 고가는 시·종가 이상, 저가는 이하여야 한다 — 합성 과정에서 어긋나면 바로잡는다
    df["High"] = df[["Open", "High", "Low", "Close"]].max(axis=1)
    df["Low"] = df[["Open", "High", "Low", "Close"]].min(axis=1)
    df = df.dropna(subset=["Close"])

    df.to_parquet(OUT / f"{TICKER}.parquet")
    meta = pd.Series({
        "ticker": TICKER, "name": "정가 HBM 지수",
        "start": str(df.index[0].date()), "end": str(df.index[-1].date()),
        "days": len(df), "constituents": len(codes),
        "total_return_pct": round(float(df["Close"].iloc[-1] /
                                        df["Close"].iloc[0] - 1) * 100, 1),
    })
    meta.to_csv(OUT / f"{TICKER}_meta.csv", encoding="utf-8-sig", header=False)

    print(f"{TICKER} → {OUT / f'{TICKER}.parquet'}")
    print(f"  {df.index[0].date()} ~ {df.index[-1].date()} ({len(df):,}일) | "
          f"누적 {meta['total_return_pct']:,.0f}%")
    print(df.tail(3).round(1).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
