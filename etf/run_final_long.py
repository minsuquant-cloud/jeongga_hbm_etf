# -*- coding: utf-8 -*-
"""
etf/run_final_long.py — 12.5년 융합 데이터 기준 최종 산출

기존 러너들은 최근 1년(+207% 강세장)에서 잰다. 여기서는 같은 검사를
2014-01~오늘 전 구간에서 다시 돌려 설계서에 실을 숫자를 확정한다.

바뀌는 것
---------
1. **용량을 정규장 기준으로 잰다.** 실측 거래대금에는 시간외·블록딜이 섞여 있는데,
   그건 원할 때 원하는 만큼 체결되지 않는다. 며칠 만에 청산 가능한가를 묻는
   용량 계산에는 정규장만 세는 편이 정직하다(대형주는 이것만으로 1.7~2.0배 차이).
2. **개인 복제 최소 투자금액**을 낸다. 실제 ETF 상장은 자산운용사만 가능하므로,
   개인이 이 구성을 재현하려면 전 종목을 비중대로 직접 사야 한다. 최소 1주 단위라
   비중을 맞출 수 있는 하한이 존재한다. 산출은 `etf/replication.py`에 있고
   **가격 교란에 강건한 금액**을 고른다(이분탐색 단조 가정을 버린 이유는 그쪽
   도크스트링 참조).

    .venv/Scripts/python.exe etf/run_final_long.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.capacity import EOK, max_aum  # noqa: E402
from etf.cu_design import build_pdf  # noqa: E402
from etf.hist_data import (adv_offline, build_index, conservative_adv,  # noqa: E402
                           load_composition, load_field, load_names,
                           volume_scale)
from etf.nav_sim import drag_decomposition, simulate_etf_nav  # noqa: E402
from etf.replication import min_replication_cost  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "etf", "output")
TER_BP, COST_BP, CASH_W = 45.0, 30.0, 0.01


def main() -> int:
    w = load_composition()
    names = load_names()
    codes = w.index.tolist()
    os.makedirs(OUT_DIR, exist_ok=True)

    bt = build_index()
    print(f"기간 {bt.index[0].date()} ~ {bt.index[-1].date()} "
          f"({len(bt):,}거래일) | 편입 {int(bt['n_stocks'].iloc[-1])}종목\n")

    # ── 1) 추적오차 (전 구간) ─────────────────────────────────────────
    nav = simulate_etf_nav(bt, ter_bp=TER_BP, trade_cost_bp=COST_BP,
                           cash_weight=CASH_W)
    dd = drag_decomposition(bt, nav, TER_BP, COST_BP, CASH_W)
    print("[1] 추적오차 분해 — 12.5년 전 구간")
    print(dd.round(2).to_string())

    # ── 2) 용량: 실측 vs 정규장 ───────────────────────────────────────
    adv_raw, adv_reg = adv_offline(codes), conservative_adv(codes)
    rows = []
    for label, adv in (("실측(시간외 포함)", adv_raw), ("정규장 기준", adv_reg)):
        s, per = max_aum(w, adv)
        rows.append({"기준": label, "용량(억)": round(s["용량(억)"], 0),
                     "병목": names.get(s["병목 종목"], s["병목 종목"])})
    cap = pd.DataFrame(rows)
    print("\n[2] 용량 — 거래대금 정의에 따라")
    print(cap.to_string(index=False))
    sc = volume_scale().reindex(codes).fillna(1.0)
    print(f"    배율 1.0 초과 종목: {int((sc > 1.01).sum())}/{len(codes)} "
          f"(최대 {sc.max():.2f} — {names.get(sc.idxmax(), '')})")

    # ── 3) CU/PDF ────────────────────────────────────────────────────
    price = load_field("Close", codes).ffill().iloc[-1]
    cu = build_pdf(w, price, cu_notional=7e8)
    print(f"\n[3] CU 7억 기준 총괴리 {cu['total_dev_bp']:.1f}bp | "
          f"0주 종목 {len(cu['zero_share'])}개")

    # ── 4) 개인 복제 최소 투자금액 ────────────────────────────────────
    print("\n[4] 개인 복제 — 실제 ETF 상장은 자산운용사만 가능하므로 직접 보유 기준")
    rep = []
    for tol in (100.0, 50.0, 25.0):
        r = min_replication_cost(w, price, tol_bp=tol)
        rep.append({"허용편차(bp)": tol,
                    "최소투자금액(만원)": round(r["최소투자금액"] / 1e4, 0),
                    "실제편차(bp)": round(r["달성편차(bp)"], 1),
                    "현금잔여(%)": round(r.get("현금 잔여(%)", 0), 2),
                    "p95 편차(bp)": round(r["p95 편차(bp)"], 1),
                    "오늘만통과(만원)": round(r["오늘만통과금액"] / 1e4, 0)})
    rep_df = pd.DataFrame(rep)
    print(rep_df.to_string(index=False))
    print(f"    참고: 최고가 종목 {names.get(price.idxmax(), '')} "
          f"{price.max():,.0f}원 (비중 {w[price.idxmax()]*100:.1f}%)")
    print("    ※ '최소투자금액'은 가격 ±5% 교란 200회 전부 허용치 이내인 금액이다."
          " '오늘만통과'는 오늘 종가 한 점에서만 통과하는 금액 — 정수 주 격자가"
          " 톱니라 강건하지 않다(CU와 같은 이유로 채택하지 않는다).")

    out = os.path.join(OUT_DIR, "final_long.csv")
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write("# 1 추적오차 (12.5년)\n"); dd.round(3).to_csv(f)
        f.write("\n# 2 용량\n"); cap.to_csv(f, index=False)
        f.write("\n# 4 개인 복제 최소금액\n"); rep_df.to_csv(f, index=False)
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
