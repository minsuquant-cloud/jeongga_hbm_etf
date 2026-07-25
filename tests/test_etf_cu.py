# -*- coding: utf-8 -*-
"""etf/cu_design.py 검증 — 전부 오프라인(손계산 픽스처), 네트워크 불필요.

핵심 불변식: floor_cash 모드에서 주식수×가격 + 현금 = CU금액 (원 단위 정확),
현금 ≥ 0, 0주 종목 검출, CU가 커질수록 괴리 단조 개선(경향).
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.cu_design import EOK, build_pdf, min_cu_notional  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


# 손계산 픽스처: 2종목 50/50, 가격 10,000 / 30,000
w = pd.Series({"A": 0.5, "B": 0.5})
px = pd.Series({"A": 10_000.0, "B": 30_000.0})

# ── 1) 손계산: CU 1억 → A 5000주(5천만), B 1666주(4999.8만), 현금 2만 ──
r = build_pdf(w, px, 1 * EOK)
check("A 주식수 = 5000", int(r["pdf"].loc["A", "주식수"]) == 5000)
check("B 주식수 = 1666 (floor)", int(r["pdf"].loc["B", "주식수"]) == 1666,
      f"got={int(r['pdf'].loc['B','주식수'])}")
check("금액+현금 = CU금액 (원 단위)",
      abs(float(r["pdf"]["금액(원)"].sum()) + r["cash"] - 1 * EOK) < 1e-6)
check("현금 ≥ 0 (floor_cash 불변식)", r["cash"] >= 0)
check("현금 = 20,000원", abs(r["cash"] - 20_000.0) < 1e-6, f"got={r['cash']}")
# A는 5000주×1만 = 정확히 50% → 괴리 0. B 부족분은 (A가 아니라) 현금으로 간다.
# B 괴리 = (4999.8만/1억 - 0.5)×1e4 = -2bp, 총괴리 = 0.5×(|0|+|-2|) = 1bp
check("A 괴리 = 0bp (정확 분할)", abs(float(r["pdf"].loc["A", "괴리(bp)"])) < 1e-9)
check("B 괴리 = -2bp", abs(float(r["pdf"].loc["B", "괴리(bp)"]) + 2.0) < 1e-9,
      f"got={float(r['pdf'].loc['B','괴리(bp)']):.4f}")
check("총괴리 = 1bp (부족분은 현금 귀속)", abs(r["total_dev_bp"] - 1.0) < 1e-9,
      f"got={r['total_dev_bp']}")

# ── 2) 0주 검출: 꼬마 비중 + 고가주 ───────────────────────────────────
w3 = pd.Series({"A": 0.995, "TINY": 0.005})
w3 = w3 / w3.sum()
px3 = pd.Series({"A": 10_000.0, "TINY": 800_000.0})   # 0.5%×1억=50만 < 80만
r3 = build_pdf(w3, px3, 1 * EOK)
check("고가 꼬마종목 0주 검출", r3["zero_share"] == ["TINY"], r3["zero_share"])
r3b = build_pdf(w3, px3, 10 * EOK)                    # 0.5%×10억=500만 → 6주
check("CU 키우면 0주 해소", r3b["zero_share"] == [])

# ── 3) CU 규모 ↑ → 괴리 개선 (경향: 최소 후보 대비 최대 후보) ─────────
grid = min_cu_notional(w3, px3, max_total_dev_bp=10.0,
                       candidates_eok=(1, 5, 10, 50))
check("그리드 행 수 = 후보 수", len(grid) == 4)
check("최대 CU 괴리 < 최소 CU 괴리",
      grid["총괴리(bp)"].iloc[-1] < grid["총괴리(bp)"].iloc[0],
      grid["총괴리(bp)"].tolist())
check("1억 CU는 0주 때문에 불충족", not bool(grid.iloc[0]["충족"]))
check("50억 CU는 충족", bool(grid.iloc[-1]["충족"]))

# ── 4) round 모드는 floor보다 괴리 같거나 작음 (검증용) ────────────────
r_round = build_pdf(w, px, 1 * EOK, mode="round")
check("round 총괴리 ≤ floor 총괴리",
      r_round["total_dev_bp"] <= r["total_dev_bp"] + 1e-9)

# ── 5) 입력 방어 ──────────────────────────────────────────────────────
try:
    build_pdf(w * 2, px, 1 * EOK); check("비중 합≠1 방어", False)
except ValueError:
    check("비중 합≠1 방어", True)
try:
    build_pdf(w, px.drop("B"), 1 * EOK); check("가격 누락 방어", False)
except ValueError:
    check("가격 누락 방어", True)
try:
    build_pdf(w, px, -1); check("CU금액 음수 방어", False)
except ValueError:
    check("CU금액 음수 방어", True)
try:
    build_pdf(w, px, 1 * EOK, mode="magic"); check("mode 방어", False)
except ValueError:
    check("mode 방어", True)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
