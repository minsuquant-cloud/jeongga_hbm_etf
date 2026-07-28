# -*- coding: utf-8 -*-
"""
etf/run_tr_index.py — JGHBM 지수의 PR vs TR: 배당이 만드는 격차와 분배금 정책

지금까지 지수·추적오차·백테스트 전부 PR(배당 미반영) 기준이었다. 실제 ETF는
구성종목 배당을 수취해 분배금으로 지급하거나 재투자한다 — 그 재원이 얼마인지
모르면 분배금 정책(상품 설계의 일부)을 정할 수 없다.

TR 근사: 매 시점 PIT 비중 × 그 시점 관측 연 배당수익률(일간 지표 — 천연 PIT)을
일할 가산. 배당락 타이밍·세금은 무시하는 1차 근사다.

    .venv/Scripts/python.exe etf/run_tr_index.py

산출: etf/output/tr_index.csv (PR·TR 지수 + 포트 배당수익률 시계열)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.hist_data import build_index, load_composition, load_field, pit_weights  # noqa: E402

_SNAP = Path(r"D:/data/_derived")
OUT = Path(__file__).resolve().parent / "output"


def main() -> int:
    target = load_composition()
    codes = target.index.tolist()

    bt = build_index()
    level_pr = bt["level"] if "level" in bt else bt.iloc[:, 0]
    close = load_field("Close", codes).loc[level_pr.index]
    w = pit_weights(close, target)

    dy = pd.read_parquet(_SNAP / "indi_dividend_yield.parquet")
    dy = dy.reindex(columns=codes).reindex(level_pr.index).ffill().fillna(0.0)
    port_dy = (w * dy).sum(axis=1)                       # 포트 가중 연 배당수익률(%)

    days = level_pr.index.to_series().diff().dt.days.fillna(0)
    daily_div = port_dy / 100.0 * days / 365.25          # 구간 일할 배당수익
    tr = level_pr * (1.0 + daily_div).cumprod()

    yrs = (level_pr.index[-1] - level_pr.index[0]).days / 365.25
    cagr_pr = (level_pr.iloc[-1] / level_pr.iloc[0]) ** (1 / yrs) - 1
    cagr_tr = (tr.iloc[-1] / tr.iloc[0]) ** (1 / yrs) - 1

    print(f"기간 {level_pr.index[0].date()} ~ {level_pr.index[-1].date()} ({yrs:.1f}년)")
    print(f"  PR 지수 CAGR: {cagr_pr:7.2%}")
    print(f"  TR 지수 CAGR: {cagr_tr:7.2%}   (배당 기여 {100*(cagr_tr-cagr_pr):+.2f}%p/yr)")
    print(f"  포트 배당수익률: 중앙값 {port_dy.median():.2f}%/yr · 최근 {port_dy.iloc[-1]:.2f}%/yr")
    print("\n분배금 정책 시사점: 최근 포트 배당수익률이 곧 연 분배 가능 재원의 근사다.")
    print("(1차 근사 — 배당락 타이밍·배당소득세 15.4% 미반영. 세후 분배면 ×0.846)")

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"PR": level_pr, "TR": tr, "포트배당수익률(%)": port_dy}).to_csv(
        OUT / "tr_index.csv", encoding="utf-8-sig")
    print(f"저장: output/tr_index.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
