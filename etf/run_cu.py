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
from etf.cu_design import (DEFAULT_MAX_DEV_BP, EOK,  # noqa: E402
                           build_pdf, min_cu_notional)
from etf.run_tracking import load_constituents, source_line  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")


def fetch_last_prices(codes: list[str]) -> pd.Series:
    """최신 종가(원). 해외 티커는 KRW 환산 레이어(hist_data)로 — 현지통화가
    KRW 격자에 섞이면 CU 계산 전체가 무의미해진다.

    **as-of가 종목마다 다를 수 있다.** CU는 '지금 바스켓을 담으면 몇 주냐'를
    묻는 계산이라 각 시장의 최신 체결가를 쓰는 것이 맞다(백테스트의 T-1
    룩어헤드 규칙은 여기 적용되지 않는다 — 그건 과거 지수 재생용이다).
    다만 러너마다 as-of가 달라 CU 값이 갈리는 사고가 있었으므로
    (2026-07-30: run_final_long은 parquet 07-29, 여기는 FDR 07-30 → CU 30억
    vs 20억), 반환값 attrs에 종목별 기준일을 실어 리포트에 찍는다.
    """
    import FinanceDataReader as fdr
    from etf.hist_data import foreign_ohlcv_krw
    end = dt.date.today()
    start = end - dt.timedelta(days=14)
    px, asof = {}, {}
    for code in codes:
        if not str(code).isdigit():
            s = foreign_ohlcv_krw(code)["Close"].dropna()
        else:
            s = fdr.DataReader(code, start, end)["Close"].dropna()
        if len(s) == 0:
            raise RuntimeError(f"가격 조회 실패: {code}")
        px[code] = float(s.iloc[-1])
        asof[code] = str(s.index[-1].date())
    out = pd.Series(px)
    out.attrs["asof"] = asof
    return out


def price_source_line(px: pd.Series) -> str:
    """가격 기준일 한 줄 — 구성 출처(source_line)와 같은 원칙을 가격에도."""
    asof = px.attrs.get("asof", {})
    if not asof:
        return "가격 기준일: 미상"
    days = sorted(set(asof.values()))
    if len(days) == 1:
        return f"가격: FDR 최신 종가 (전 종목 {days[0]})"
    grouped = {d: [c for c, v in asof.items() if v == d] for d in days}
    parts = [f"{d} {len(v)}종목" for d, v in grouped.items()]
    return ("가격: FDR 최신 종가 — ⚠기준일 혼재 (" + " · ".join(parts) + ")"
            " · 시장별 마감 시각 차이")


def main():
    ap = argparse.ArgumentParser(description="실데이터 CU/PDF 설계")
    ap.add_argument("--max-dev-bp", type=float, default=DEFAULT_MAX_DEV_BP,
                    help=f"총괴리 허용치(bp, 기본 {DEFAULT_MAX_DEV_BP:g})")
    ap.add_argument("--shock", type=float, default=0.05,
                    help="강건성 검정 가격 교란폭 (기본 ±5%%, 0이면 끔)")
    ap.add_argument("--trials", type=int, default=300,
                    help="강건성 검정 시행 횟수 (기본 300)")
    args = ap.parse_args()

    c = load_constituents()
    codes = c["코드"].tolist()
    names = c.set_index("코드")["종목명"]
    weights = pd.Series((c["편입비중(%)"] / 100.0).values, index=codes)
    weights = weights / weights.sum()

    prices = fetch_last_prices(codes)
    print(f"{source_line(c)}")
    print(f"{price_source_line(prices)}  (실행 {dt.date.today()})")

    grid = min_cu_notional(weights, prices, max_total_dev_bp=args.max_dev_bp,
                           shock=args.shock, n_trials=args.trials)
    print(f"\n[CU 후보별 괴리] 허용 총괴리 {args.max_dev_bp:g}bp · "
          f"강건 = 가격 ±{args.shock:.0%} 교란 {args.trials}회 전부 허용치 이내")
    print(grid.to_string(index=False))

    firm = grid[grid["강건"]] if "강건" in grid.columns else grid[grid["충족"]]
    ok_rows = grid[grid["충족"]]
    if len(firm) == 0:
        print("\n⚠ 어떤 후보도 강건하지 않음 — 후보를 키우거나 허용치 완화 필요")
        rec_eok = int(grid.iloc[-1]["CU금액(억)"])
    else:
        rec_eok = int(firm.iloc[0]["CU금액(억)"])
    print(f"\n[권장 CU] {rec_eok}억 원 (교란에도 허용치를 지키는 최소 규모)")
    if len(ok_rows) and int(ok_rows.iloc[0]["CU금액(억)"]) != rec_eok:
        lucky = ok_rows.iloc[0]
        print(f"  ※ 오늘 종가만 보면 {int(lucky['CU금액(억)'])}억도 통과하지만 "
              f"교란 초과율 {lucky['초과율(%)']:.0f}% — 반올림 격자 운이다. 채택 안 함.")

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
