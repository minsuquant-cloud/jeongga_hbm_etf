# -*- coding: utf-8 -*-
"""
etf/run_stress.py — 실데이터 스트레스 테스트 리포트 (최종 12종목 기준)
======================================================================
사용법:
    .venv/Scripts/python.exe etf/run_stress.py

출력: etf/output/stress_t1_tracking.csv, stress_t2_capacity.csv,
      stress_t2b_assumptions.csv, stress_t3_redemption.csv + 콘솔 리포트
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
from etf.stress_test import (redemption_endurance,  # noqa: E402
                             stress_capacity,
                             stress_capacity_assumptions, stress_tracking)

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

    # ── T2b: 관측이 아니라 '우리가 고른' 가정 두 개를 흔든다 ────────────
    capa = stress_capacity_assumptions(w, adv)
    capa["병목 종목"] = capa["병목 종목"].map(lambda x: f"{names.get(x, x)}")
    print("\n[T2b 용량 가정 민감도] ADV 실측 고정 · 참여율 × 청산 허용일수")
    print(capa.to_string(index=False))
    worst = capa.iloc[-1]
    print(f"  → 보수 가정(참여율 {worst['참여율']}·{worst['청산 허용일수']:g}일) "
          f"{worst['용량(억)']:,.0f}억 — 기준의 {worst['기준 대비']}. "
          "용량은 관측치가 아니라 가정의 함수다.")
    capa_dry = stress_capacity_assumptions(w, adv, adv_factor=0.5)
    print(f"  → 여기에 ADV 반토막까지 겹치면 "
          f"{capa_dry.iloc[-1]['용량(억)']:,.0f}억 (최악 시나리오)")

    # ── T3: 복합 — 환매 내구성 ─────────────────────────────────────────
    print("\n[T3 환매 내구성] ADV 반토막 가정 (위기 복합)")
    rows = []
    for aum_eok in (500, 1000, 2000):
        r = redemption_endurance(w, adv, aum_krw=aum_eok * EOK, adv_factor=0.5)
        r["병목 종목"] = f"{names.get(r['병목 종목'], r['병목 종목'])}"
        rows.append(r)
    t3 = pd.DataFrame(rows)
    print(t3.round(2).to_string(index=False))

    # 표마다 별도 CSV — 한 파일에 이어붙이면 헤더가 겹쳐 다시 읽을 수 없다.
    os.makedirs(OUT_DIR, exist_ok=True)
    st2 = st.round(3).copy()
    st2.insert(0, "구간", [f"{win[0]}~{win[1]} (MDD {st.attrs['mdd']:.1%})"
                          if i == "하락 구간" else "전체 기간" for i in st2.index])
    files = {
        "stress_t1_tracking.csv": (st2, True),
        "stress_t2_capacity.csv": (cap, False),
        "stress_t2b_assumptions.csv": (capa, False),
        "stress_t3_redemption.csv": (t3.round(3), False),
    }
    for fname, (df, with_index) in files.items():
        df.to_csv(os.path.join(OUT_DIR, fname), index=with_index,
                  encoding="utf-8-sig")
    print(f"\n저장: {OUT_DIR}\\" + ", ".join(files))


if __name__ == "__main__":
    main()
