# -*- coding: utf-8 -*-
"""
etf/run_final.py — 실사 확정 반영 최종 리포트 (구성·상장요건·용량·CU 통합)
==========================================================================
2026-07-25 실사 판정 확정(사용자 결정):
  · 편입 확정 5: 네오셈·티이엠씨·솔브레인·주성엔지니어링·오로스테크놀로지
    - 오로스: 사업보고서에 TSV Overlay 솔루션 명시 → 규칙 C② 문서 근거 인정
  · 관찰종목 2: 심텍·SFA반도체 — 현재 HBM 귀속 매출의 문서 근거 없음
    ("앞으로 연관될 것"은 전망이지 판정 요건이 아님 — fail-closed).
    HBM 매출이 공시에 잡히면 다음 정기변경에서 재심사(정원 폐지 취지).

산출: 확정 판정 CSV + 최종 구성표 + 상장요건 점검 + 용량·CU 재산출
사용법:
    .venv/Scripts/python.exe etf/run_final.py [--skip-market]
    (--skip-market: 네트워크 없이 구성·상장요건까지만)
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.ERROR)
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from etf.capacity import EOK, fetch_adv, max_aum  # noqa: E402
from etf.compliance import check_diversification  # noqa: E402
from etf.cu_design import build_pdf, min_cu_notional  # noqa: E402
from etf.scenario_min10 import load_judged, run_scenario  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")
PROC = os.path.join(BASE, "data", "processed")

GRANTED = {                       # 실사 확정 (2026-07-25 사용자 판정)
    "253590": "네오셈", "425040": "티이엠씨", "357780": "솔브레인",
    "036930": "주성엔지니어링", "322310": "오로스테크놀로지",
}
WATCHLIST = {"222800": "심텍", "036540": "SFA반도체"}


def main():
    ap = argparse.ArgumentParser(description="실사 확정 최종 리포트")
    ap.add_argument("--skip-market", action="store_true",
                    help="ADV·가격 조회 없이 구성·상장요건까지만")
    args = ap.parse_args()

    judged = load_judged()

    # ── 1) 확정 판정 CSV (원본 PIT 보존 — 새 파일로 기록) ──────────────
    upd = judged.copy()
    m = upd["코드"].isin(GRANTED)
    upd.loc[m, "HBM공정확인"] = True
    upd.loc[m, "위원회확인"] = True
    out_judged = os.path.join(PROC, "판정완료_20260725_실사확정.csv")
    upd.to_csv(out_judged, index=False, encoding="utf-8-sig")

    # ── 2) 최종 구성 (팀 엔진) + 상장요건 ─────────────────────────────
    r = run_scenario(judged, grant_codes=list(GRANTED))
    comp = r["_구성"].copy()
    print(f"[최종 구성] {r['종목수']}종목 ({r['앵커/핵심/위성']}) · "
          f"HBM 순도 {r['HBM순도(%)']}% · 최대비중 {r['최대비중(%)']}%")
    print(comp.to_string(index=False))
    print(f"\n[상장요건] R1(≥10종목): {r['R1 종목수≥10']} · "
          f"R2(≤30%): {r['R2 ≤30%']} · R3(≤20% 방침): {r['R3 ≤20%']}")
    print(f"[관찰종목] {', '.join(WATCHLIST.values())} — HBM 매출 공시 확인 시 "
          "다음 정기변경 재심사")

    out_comp = os.path.join(PROC, "구성표_실사확정_20260725.csv")
    comp.to_csv(out_comp, index=False, encoding="utf-8-sig")

    if args.skip_market:
        print(f"\n저장: {out_judged}\n      {out_comp}")
        return

    # ── 3) 용량·CU 재산출 (새 비중 기준) ───────────────────────────────
    w = pd.Series((comp["편입비중(%)"] / 100.0).values,
                  index=comp["코드"].astype(str).str.zfill(6).tolist())
    w = w / w.sum()
    names = judged.set_index("코드")["종목명"]

    print("\n[용량 재산출] ADV 60거래일, 참여율 20%·청산 5일")
    adv = fetch_adv(list(w.index))
    summary, per_stock = max_aum(w, adv)
    print(f"  용량: {summary['용량(억)']:,.0f}억 원 "
          f"(기존 7종목 613억 → 병목 {names.get(summary['병목 종목'], summary['병목 종목'])})")
    worst3 = (per_stock / EOK).nsmallest(3)
    for code, cap in worst3.items():
        print(f"    허용 AUM 하위: {names.get(code, code)} {cap:,.0f}억")

    print("\n[CU 재산출] 허용 총괴리 10bp")
    import FinanceDataReader as fdr
    end = dt.date.today()
    px = {}
    for code in w.index:
        s = fdr.DataReader(code, end - dt.timedelta(days=14), end)["Close"].dropna()
        px[code] = float(s.iloc[-1])
    prices = pd.Series(px)
    grid = min_cu_notional(w, prices, max_total_dev_bp=10.0)
    ok_rows = grid[grid["충족"]]
    rec_eok = int(ok_rows.iloc[0]["CU금액(억)"]) if len(ok_rows) else None
    print(grid.to_string(index=False))
    if rec_eok:
        pdf = build_pdf(w, prices, rec_eok * EOK)
        print(f"  권장 CU {rec_eok}억: 총괴리 {pdf['total_dev_bp']:.2f}bp"
              + (f" · ⚠0주 {pdf['zero_share']}" if pdf["zero_share"] else ""))

    os.makedirs(OUT_DIR, exist_ok=True)
    grid.to_csv(os.path.join(OUT_DIR, "final_cu_grid.csv"),
                index=False, encoding="utf-8-sig")
    (per_stock / EOK).round(1).rename("허용AUM(억)").to_frame() \
        .assign(종목명=lambda x: names.reindex(x.index)) \
        .to_csv(os.path.join(OUT_DIR, "final_capacity.csv"), encoding="utf-8-sig")
    print(f"\n저장: {out_judged}\n      {out_comp}\n"
          f"      {OUT_DIR}\\final_capacity.csv, final_cu_grid.csv")


if __name__ == "__main__":
    main()
