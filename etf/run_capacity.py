# -*- coding: utf-8 -*-
"""
etf/run_capacity.py — 실데이터 용량 리포트 (확정 구성표 기준)
=============================================================
구성표 7종목의 최근 60거래일 실제 거래대금으로 "이 ETF는 AUM 얼마까지
소화 가능한가"를 산출한다.

사용법:
    .venv/Scripts/python.exe etf/run_capacity.py [--participation 0.2]
        [--max-days 5] [--lookback 60]

출력: etf/output/capacity_report.csv + 콘솔 리포트
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.capacity import EOK, capacity_table, fetch_adv, max_aum  # noqa: E402
from etf.run_tracking import load_constituents  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")

AUM_GRID_EOK = (100, 500, 1000, 3000)      # 억 원


def main():
    ap = argparse.ArgumentParser(description="실데이터 ETF 용량 리포트")
    ap.add_argument("--participation", type=float, default=0.20,
                    help="일일 ADV 참여율 (기본 20%%)")
    ap.add_argument("--max-days", type=float, default=5.0,
                    help="전량 청산 허용일수 (기본 5일)")
    ap.add_argument("--lookback", type=int, default=60,
                    help="ADV 산출 기간(거래일, 기본 60)")
    args = ap.parse_args()

    c = load_constituents()
    codes = c["코드"].tolist()
    names = c.set_index("코드")["종목명"]
    weights = pd.Series((c["편입비중(%)"] / 100.0).values, index=codes)
    weights = weights / weights.sum()

    print(f"ADV 수집: 최근 {args.lookback}거래일 (기준일 {dt.date.today()})")
    adv = fetch_adv(codes, lookback_days=args.lookback)

    summary, per_stock = max_aum(weights, adv,
                                 participation=args.participation,
                                 max_days=args.max_days)
    bottleneck = summary["병목 종목"]
    print(f"\n[ETF 용량] 참여율 {args.participation:.0%} · "
          f"청산 {args.max_days:g}일 기준")
    print(f"  용량: {summary['용량(억)']:,.0f}억 원")
    print(f"  병목: {names.get(bottleneck, bottleneck)}({bottleneck})")

    rows = []
    for aum_eok in AUM_GRID_EOK:
        tbl = capacity_table(weights, adv, aum_krw=aum_eok * EOK,
                             participation=args.participation)
        worst = tbl["청산 소요일"].idxmax()
        rows.append({
            "AUM(억)": aum_eok,
            "최악 종목": f"{names.get(worst, worst)}({worst})",
            "최악 청산일": round(float(tbl["청산 소요일"].max()), 1),
            "5일 내 청산가능": bool(tbl["청산 소요일"].max() <= args.max_days),
        })
    grid = pd.DataFrame(rows)

    detail = capacity_table(weights, adv, aum_krw=1000 * EOK,
                            participation=args.participation)
    detail.insert(0, "종목명", names.reindex(detail.index))
    detail["허용 AUM(억)"] = (per_stock / EOK).round(0)

    print(f"\n[AUM 1,000억 기준 종목별 상세]")
    print(detail.round(2).to_string())
    print(f"\n[AUM 그리드]")
    print(grid.to_string(index=False))

    os.makedirs(OUT_DIR, exist_ok=True)
    out_csv = os.path.join(OUT_DIR, "capacity_report.csv")
    detail.round(3).to_csv(out_csv, encoding="utf-8-sig")
    print(f"\n저장: {out_csv}")
    print("\n주의: ADV는 최근 강세장 거래대금 기준 — 거래 냉각 시 용량은 줄어든다. "
          "현물설정 활용 시 실제 용량은 이보다 크다(보수적 하한).")


if __name__ == "__main__":
    main()
