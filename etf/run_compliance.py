# -*- coding: utf-8 -*-
"""
etf/run_compliance.py — 확정 구성표의 분산요건 점검 리포트
==========================================================
사용법:
    .venv/Scripts/python.exe etf/run_compliance.py

출력: etf/output/compliance_report.csv + 콘솔 리포트
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.compliance import check_diversification, remediation_notes  # noqa: E402
from etf.run_tracking import load_constituents  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")


def main():
    c = load_constituents()
    names = c.set_index("코드")["종목명"]
    w = pd.Series((c["편입비중(%)"] / 100.0).values, index=c["코드"].tolist())

    rep = check_diversification(w)
    # 실측 컬럼의 코드에 종목명 붙이기 (읽기 편하게)
    rep["실측"] = rep["실측"].astype(str)
    for code, name in names.items():
        rep["실측"] = rep["실측"].str.replace(code, f"{name}", regex=False)

    print("[지수형 ETF 분산요건 점검] 구성표_실데이터_20260723 기준")
    print(rep.to_string(index=False))

    notes = remediation_notes(w)
    if notes:
        print("\n[해소 방안 메모]")
        for i, n in enumerate(notes, 1):
            print(f"  {i}. {n}")

    n_fail = int((rep["판정"] == "FAIL").sum())
    n_warn = int((rep["판정"] == "WARN").sum())
    print(f"\n종합: FAIL {n_fail} · WARN {n_warn} — "
          + ("현 구성으로는 ETF 상장 불가 (FAIL 해소 필요)" if n_fail
             else "상장 요건 충족 (WARN은 모니터링)"))

    os.makedirs(OUT_DIR, exist_ok=True)
    out_csv = os.path.join(OUT_DIR, "compliance_report.csv")
    rep.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_csv}")


if __name__ == "__main__":
    main()
