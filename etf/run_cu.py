# -*- coding: utf-8 -*-
"""
etf/run_cu.py — 실데이터 CU/PDF 설계 리포트 (확정 구성표 기준)
==============================================================
구성표 7종목의 최신 종가로 CU 후보 규모별 괴리를 훑고, 권장 CU의
납부자산구성내역(PDF)을 산출한다.

사용법:
    .venv/Scripts/python.exe etf/run_cu.py [--max-dev-bp 10]

출력: etf/output/cu_grid.csv + cu_pdf.csv + 콘솔 리포트
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.cu_design import EOK, build_pdf, min_cu_notional  # noqa: E402
from etf.run_tracking import load_constituents, source_line  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")


def fetch_last_prices(codes: list[str]) -> pd.Series:
    import FinanceDataReader as fdr
    end = dt.date.today()
    start = end - dt.timedelta(days=14)
    px = {}
    for code in codes:
        s = fdr.DataReader(code, start, end)["Close"].dropna()
        if len(s) == 0:
            raise RuntimeError(f"가격 조회 실패: {code}")
        px[code] = float(s.iloc[-1])
    return pd.Series(px)


def main():
    ap = argparse.ArgumentParser(description="실데이터 CU/PDF 설계")
    ap.add_argument("--max-dev-bp", type=float, default=10.0,
                    help="총괴리 허용치(bp, 기본 10)")
    args = ap.parse_args()

    c = load_constituents()
    codes = c["코드"].tolist()
    names = c.set_index("코드")["종목명"]
    weights = pd.Series((c["편입비중(%)"] / 100.0).values, index=codes)
    weights = weights / weights.sum()

    prices = fetch_last_prices(codes)
    print(f"{source_line(c)} · 최신 종가 수집 (기준일 {dt.date.today()})")

    grid = min_cu_notional(weights, prices, max_total_dev_bp=args.max_dev_bp)
    print(f"\n[CU 후보별 괴리] 허용 총괴리 {args.max_dev_bp:g}bp")
    print(grid.to_string(index=False))

    ok_rows = grid[grid["충족"]]
    if len(ok_rows) == 0:
        print("\n⚠ 어떤 후보도 허용치를 만족하지 못함 — 후보를 키우거나 허용치 완화 필요")
        rec_eok = int(grid.iloc[-1]["CU금액(억)"])
    else:
        rec_eok = int(ok_rows.iloc[0]["CU금액(억)"])
    print(f"\n[권장 CU] {rec_eok}억 원 (허용치 만족 최소 규모)")

    r = build_pdf(weights, prices, rec_eok * EOK)
    pdf = r["pdf"].copy()
    pdf.insert(0, "종목명", names.reindex(pdf.index))
    print(f"\n[1 CU = {rec_eok}억 PDF]  (ETF {int(r['cu_shares']):,}좌, "
          f"현금 {r['cash']:,.0f}원 = {r['cash_weight_bp']:.1f}bp)")
    print(pdf.round(2).to_string())
    print(f"총괴리 {r['total_dev_bp']:.2f}bp · 최대괴리 {r['max_dev_bp']:.2f}bp"
          + (f" · ⚠0주: {r['zero_share']}" if r["zero_share"] else ""))

    os.makedirs(OUT_DIR, exist_ok=True)
    grid.to_csv(os.path.join(OUT_DIR, "cu_grid.csv"),
                index=False, encoding="utf-8-sig")
    pdf.round(3).to_csv(os.path.join(OUT_DIR, "cu_pdf.csv"),
                        encoding="utf-8-sig")
    print(f"\n저장: {OUT_DIR}\\cu_grid.csv, cu_pdf.csv")


if __name__ == "__main__":
    main()
