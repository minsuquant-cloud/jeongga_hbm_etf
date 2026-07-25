# -*- coding: utf-8 -*-
"""etf/compliance.py 검증 — 분산요건 판정 로직 (오프라인)."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.compliance import check_diversification, remediation_notes  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


def verdict(df, tag):
    return df[df["항목"].str.startswith(tag)]["판정"].iloc[0]


# ── 1) 적격 케이스: 12종목·최대 15% → 전부 PASS ───────────────────────
w_good = pd.Series([0.15] + [0.85 / 11] * 11,
                   index=[f"S{i}" for i in range(12)])
d = check_diversification(w_good)
check("적격: R1 PASS", verdict(d, "[R1]") == "PASS")
check("적격: R2 PASS", verdict(d, "[R2]") == "PASS")
check("적격: R3 PASS", verdict(d, "[R3]") == "PASS")
check("적격: 해소 메모 없음", remediation_notes(w_good) == [])

# ── 2) 현 구성표 유형: 7종목·최대 21.57% ──────────────────────────────
w_ours = pd.Series([0.2157, 0.1843, 0.18, 0.18, 0.1281, 0.1058, 0.0061],
                   index=list("ABCDEFG"))
d2 = check_diversification(w_ours)
check("7종목: R1 FAIL", verdict(d2, "[R1]") == "FAIL")
check("7종목: R2 PASS (21.57% ≤ 30%)", verdict(d2, "[R2]") == "PASS")
check("7종목: R3 WARN (21.57% > 20%)", verdict(d2, "[R3]") == "WARN")
notes = remediation_notes(w_ours)
check("해소 메모 2건 (종목수 + 20%)", len(notes) == 2, f"n={len(notes)}")

# ── 3) 경계값: 정확히 10종목·정확히 30% ───────────────────────────────
w_edge = pd.Series([0.30] + [0.70 / 9] * 9, index=[f"E{i}" for i in range(10)])
d3 = check_diversification(w_edge)
check("경계: 10종목 = PASS", verdict(d3, "[R1]") == "PASS")
check("경계: 30.00% = PASS (초과 아님)", verdict(d3, "[R2]") == "PASS")
check("경계: 30% > 20% = WARN", verdict(d3, "[R3]") == "WARN")

# ── 4) 30% 초과 → R2 FAIL ─────────────────────────────────────────────
w_over = pd.Series([0.35] + [0.65 / 9] * 9, index=[f"O{i}" for i in range(10)])
check("31%+ : R2 FAIL", verdict(check_diversification(w_over), "[R2]") == "FAIL")

# ── 5) 비정규 입력 정규화 + 방어 ──────────────────────────────────────
d5 = check_diversification(w_ours * 3.0)
check("스케일 불변", verdict(d5, "[R2]") == "PASS")
try:
    check_diversification(pd.Series(dtype=float)); check("빈 입력 방어", False)
except ValueError:
    check("빈 입력 방어", True)
try:
    check_diversification(pd.Series({"A": -0.1, "B": 1.1}))
    check("음수 방어", False)
except ValueError:
    check("음수 방어", True)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
