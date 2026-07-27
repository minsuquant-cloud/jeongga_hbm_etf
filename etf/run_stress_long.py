# -*- coding: utf-8 -*-
"""
etf/run_stress_long.py — 12.5년 위기구간 스트레스 테스트

기존 `run_stress.py`는 최근 1년(+207% 강세장)에서 잰다. 이 스크립트는 같은 검사를
2014-01~2026-06 전 구간에서 다시 돌려, 반도체가 실제로 무너진 구간에서도
지금까지의 숫자가 버티는지 본다.

    .venv/Scripts/python.exe etf/run_stress_long.py

출력: etf/output/stress_long.csv + 콘솔
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.capacity import EOK, max_aum  # noqa: E402
from etf.hist_data import (build_index, load_composition, load_field,  # noqa: E402
                           load_names)
from etf.nav_sim import drag_decomposition, simulate_etf_nav  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")

# 반도체가 실제로 무너진 구간 (정점→저점, 사후 확정된 역사적 사실)
CRISES = {
    "2018 반도체 사이클 붕괴": ("2018-05-01", "2019-01-04"),
    "2020 코로나 폭락": ("2020-01-20", "2020-03-19"),
    "2022 금리인상기": ("2021-12-28", "2022-10-14"),
    "2026 조정(진행중)": ("2026-06-01", None),
}
TER_BP, COST_BP, CASH_W = 45.0, 30.0, 0.01


def main() -> int:
    bt = build_index()
    names = load_names()
    print(f"기간 {bt.index[0].date()} ~ {bt.index[-1].date()} "
          f"({len(bt):,}거래일) | 편입 종목수 {bt['n_stocks'].iloc[0]}"
          f" → {bt['n_stocks'].iloc[-1]}\n")

    nav = simulate_etf_nav(bt, ter_bp=TER_BP, trade_cost_bp=COST_BP,
                           cash_weight=CASH_W)

    rows = {}
    for label, (s, e) in {"전체 기간": (None, None), **CRISES}.items():
        sl = slice(s, e)
        b, n = bt.loc[sl], nav.loc[sl]
        if len(b) < 20:
            continue
        dd = drag_decomposition(b, n, TER_BP, COST_BP, CASH_W)
        idx_ret = float(b["level"].iloc[-1] / b["level"].iloc[0] - 1)
        peak = b["level"].cummax()
        rows[label] = pd.concat([pd.Series({
            "지수수익률(%)": idx_ret * 100,
            "최대낙폭(%)": float((b["level"] / peak - 1).min()) * 100,
            "편입종목수": int(b["n_stocks"].iloc[-1]),
            "거래일": len(b),
        }), dd])

    tbl = pd.DataFrame(rows).T
    print("[T1] 구간별 추적오차 분해 (TER45·비용30·현금1%)")
    print(tbl.round(2).to_string())

    cash = tbl["현금 기여(bp/년)"]
    print(f"\n  → 현금 1% 기여: 전체 {cash['전체 기간']:+.0f}bp"
          f" / 위기구간 {cash[[k for k in CRISES if k in cash.index]].to_dict()}")

    # ── 위기구간 유동성: 당시 실제 거래대금으로 용량 재산출 ──────────────
    print("\n[T2] 위기구간 실측 거래대금 기준 용량")
    target = load_composition()
    val = load_field("Value", target.index.tolist())
    cap_rows = []
    for label, (s, e) in CRISES.items():
        seg = val.loc[s:e] if e else val.loc[s:]
        if len(seg) < 20:
            continue
        adv = seg.mean().dropna()
        w = target.reindex(adv.index).dropna()
        w = w / w.sum()
        summ, _ = max_aum(w, adv.reindex(w.index))
        cap_rows.append({"구간": label, "종목수": len(w),
                         "용량(억)": round(summ["용량(억)"], 0),
                         "병목": f"{names.get(summ['병목 종목'], '')}"})
    cap = pd.DataFrame(cap_rows)
    print(cap.to_string(index=False))

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "stress_long.csv")
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write("# T1 구간별 추적오차 분해 (12.5년)\n")
        tbl.round(3).to_csv(f)
        f.write("\n# T2 위기구간 용량\n")
        cap.to_csv(f, index=False)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
