# -*- coding: utf-8 -*-
"""
etf/run_stress.py — 실데이터 스트레스 테스트 리포트 (최종 12종목 기준)
======================================================================
사용법:
    .venv/Scripts/python.exe etf/run_stress.py

출력: etf/output/stress_report.csv + 콘솔 리포트
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.ERROR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from backtest.backtest import simulate_index  # noqa: E402
from etf.capacity import fetch_adv, EOK  # noqa: E402
from etf.run_tracking import build_events, fetch_prices  # noqa: E402
from etf.stress_test import (redemption_endurance, stress_capacity,  # noqa: E402
                             stress_tracking)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")
FINAL = os.path.join(BASE, "data", "processed", "구성표_실사확정_20260725.csv")


def main():
    c = pd.read_csv(FINAL, encoding="utf-8-sig")
    c["코드"] = c["코드"].astype(str).str.zfill(6)
    names = c.set_index("코드")["종목명"]
    w = pd.Series((c["편입비중(%)"] / 100.0).values, index=c["코드"].tolist())
    w = w / w.sum()

    today = dt.date.today()
    start = str(today - dt.timedelta(days=365))
    prices = fetch_prices(w.index.tolist(), start, str(today))
    bt = simulate_index(prices, build_events(prices, w))

    # ── T1: 하락장 추적오차 ────────────────────────────────────────────
    st = stress_tracking(bt, ter_bp=45, trade_cost_bp=30, cash_weight=0.01)
    win = st.attrs["window"]
    print(f"[T1 하락장 추적오차] 최대낙폭 구간 {win[0]} → {win[1]} "
          f"(MDD {st.attrs['mdd']:.1%}) · TER45·비용30·현금1%")
    print(st.round(2).to_string())
    cash_full = st.loc["전체 기간", "현금 기여(bp/년)"]
    cash_down = st.loc["하락 구간", "현금 기여(bp/년)"]
    print(f"  → 현금 1%: 상승장 {cash_full:+.0f}bp(드래그) / "
          f"하락장 {cash_down:+.0f}bp(방어) — 부호 반전 확인")

    # ── T2: 유동성 가뭄 용량 ───────────────────────────────────────────
    adv = fetch_adv(w.index.tolist())
    cap = stress_capacity(w, adv)
    cap["병목 종목"] = cap["병목 종목"].map(lambda x: f"{names.get(x, x)}({x})")
    print("\n[T2 유동성 가뭄 용량] 참여율 20%·청산 5일")
    print(cap.to_string(index=False))

    # ── T3: 복합 — 환매 내구성 ─────────────────────────────────────────
    print("\n[T3 환매 내구성] ADV 반토막 가정 (위기 복합)")
    rows = []
    for aum_eok in (500, 1000, 2000):
        r = redemption_endurance(w, adv, aum_krw=aum_eok * EOK, adv_factor=0.5)
        r["병목 종목"] = f"{names.get(r['병목 종목'], r['병목 종목'])}"
        rows.append(r)
    t3 = pd.DataFrame(rows)
    print(t3.round(2).to_string(index=False))

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "stress_report.csv")
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write(f"# T1 하락장 추적오차 (구간 {win[0]}~{win[1]}, MDD {st.attrs['mdd']:.1%})\n")
        st.round(3).to_csv(f)
        f.write("\n# T2 유동성 가뭄 용량\n")
        cap.to_csv(f, index=False)
        f.write("\n# T3 환매 내구성 (ADV x0.5)\n")
        t3.round(3).to_csv(f, index=False)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
