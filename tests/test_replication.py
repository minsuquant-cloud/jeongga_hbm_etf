# -*- coding: utf-8 -*-
"""etf/replication.py 검증 — 오프라인(손계산 픽스처), 네트워크 불필요.

배경 회귀: 개인 복제 최소금액을 이분탐색으로 찾던 초기 구현은 편차가 금액에
단조라고 가정했는데 정수 주 격자 때문에 톱니다. 100bp 답(1억 6,820만) 아래에
1억 5,979만원도 통과했고, ±5% 교란에서 21점 중 3점이 허용치를 넘었다.
CU(cu_robustness)와 같은 해법으로 옮긴 뒤의 계약을 지킨다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.replication import (deviation_bp, min_replication_cost,  # noqa: E402
                             replication_grid, zero_share_count)

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


# ── 1) 손계산: 2종목 50/50, 가격 10,000 / 30,000 ──────────────────────
w = pd.Series({"A": 0.5, "B": 0.5})
px = pd.Series({"A": 10_000.0, "B": 30_000.0})
# 1억: A 5000주(5천만) · B 1666주(4,999.8만) → 현금 2만 = 2bp
check("편차 = 현금비중 (손계산 2bp)",
      abs(deviation_bp(w, px, 1e8) - 2.0) < 1e-9, deviation_bp(w, px, 1e8))
# 정확히 나누어떨어지는 금액이면 편차 0
check("정확 분할 금액은 편차 0",
      abs(deviation_bp(w, px, 60_000.0)) < 1e-9, deviation_bp(w, px, 60_000.0))
try:
    deviation_bp(w, px, -1)
    check("음수 금액 예외", False)
except ValueError:
    check("음수 금액 예외", True)

# ── 2) CU 지표와 같은 척도인지 (현금 포함 총괴리와 일치) ──────────────
from etf.cu_design import build_pdf  # noqa: E402

r = build_pdf(w, px, 1e8)
check("CU total_dev_bp == 복제 deviation_bp (같은 자)",
      abs(r["total_dev_bp"] - deviation_bp(w, px, 1e8)) < 1e-9,
      f"{r['total_dev_bp']} vs {deviation_bp(w, px, 1e8)}")

# ── 3) 0주 검출 ───────────────────────────────────────────────────────
w3 = pd.Series({"A": 0.995, "TINY": 0.005})
w3 = w3 / w3.sum()
px3 = pd.Series({"A": 10_000.0, "TINY": 800_000.0})   # 0.5%×1억=50만 < 80만
check("고가 꼬마종목 0주 검출", zero_share_count(w3, px3, 1e8) == 1)
check("금액 키우면 0주 해소", zero_share_count(w3, px3, 1e9) == 0)

# ── 4) 편차는 금액에 단조가 아니다 (이분탐색을 버린 이유) ─────────────
g = replication_grid(w, px, tol_bp=50.0, lo=1e7, hi=1e9, n_points=120, shock=0)
d = g["편차(bp)"].to_numpy()
check("편차가 비단조 (톱니 실증)", bool((np.diff(d) > 0).any()),
      "단조 감소라면 이분탐색이 옳았다는 뜻")

# ── 5) 강건 선택: 오늘만 통과 금액보다 크거나 같다 ────────────────────
res = min_replication_cost(w3, px3, tol_bp=50.0, n_trials=60, n_points=70)
check("강건 금액 ≥ 오늘만통과 금액",
      not np.isfinite(res["최소투자금액"])
      or res["최소투자금액"] >= res["오늘만통과금액"] - 1e-9,
      f"강건 {res['최소투자금액']:,.0f} vs 오늘 {res['오늘만통과금액']:,.0f}")
check("강건 금액의 교란 초과율 0%",
      not np.isfinite(res["최소투자금액"]) or res["초과율(%)"] == 0.0,
      res["초과율(%)"])
check("강건 금액은 0주 없음",
      not np.isfinite(res["최소투자금액"]) or res["0주 종목"] == 0,
      res["0주 종목"])

# ── 6) 격자에 강건 답이 없으면 NaN (조용한 근사 금지) ─────────────────
tiny = min_replication_cost(w3, px3, tol_bp=0.001, n_trials=20, n_points=30)
check("불가능한 허용치 → NaN", not np.isfinite(tiny["최소투자금액"]),
      tiny["최소투자금액"])

# ── 7) 재현성 (seed 고정) ─────────────────────────────────────────────
a = min_replication_cost(w3, px3, tol_bp=50.0, n_trials=40, n_points=50)
b = min_replication_cost(w3, px3, tol_bp=50.0, n_trials=40, n_points=50)
check("seed 고정 → 동일 결과", a == b)

# ── 8) 허용치를 키우면 최소금액은 작아지거나 같다 (방향 정합) ──────────
loose = min_replication_cost(w3, px3, tol_bp=200.0, n_trials=40, n_points=70)
tight = min_replication_cost(w3, px3, tol_bp=50.0, n_trials=40, n_points=70)
check("허용치↑ → 최소금액 ≤",
      loose["최소투자금액"] <= tight["최소투자금액"] + 1e-9,
      f"200bp {loose['최소투자금액']:,.0f} vs 50bp {tight['최소투자금액']:,.0f}")

# ── 9) 입력 방어 ──────────────────────────────────────────────────────
try:
    replication_grid(w, px.drop("B"), shock=0)
    check("가격 누락 예외", False)
except (ValueError, KeyError):
    check("가격 누락 예외", True)
try:
    replication_grid(w, px, shock=1.5)
    check("shock 범위 예외", False)
except ValueError:
    check("shock 범위 예외", True)
try:
    replication_grid(w, px, lo=1e9, hi=1e8, shock=0)
    check("금액 범위 역전 예외", False)
except ValueError:
    check("금액 범위 역전 예외", True)

# ── 10) 실제 정본 구성으로 스모크 (parquet 없이 합성 가격) ────────────
real = pd.read_csv("data/processed/구성표_글로벌확정_20260729.csv",
                   encoding="utf-8-sig")
from etf.global_candidates import normalize_code  # noqa: E402

real["코드"] = real["코드"].map(normalize_code)
rw = pd.Series((real["편입비중(%)"] / 100).values, index=real["코드"])
rw = rw / rw.sum()
# 고가주(하이닉스 155만·MU 119만)를 포함한 현실적 가격대
rng = np.random.default_rng(1)
rpx = pd.Series(rng.uniform(9_000, 1_600_000, len(rw)), index=rw.index)
rr = min_replication_cost(rw, rpx, tol_bp=100.0, n_trials=50, n_points=70)
check("13종목 스모크 — 강건 답 존재", np.isfinite(rr["최소투자금액"]),
      rr)
check("13종목 스모크 — 편차 ≤ 허용치",
      rr["달성편차(bp)"] <= 100.0 + 1e-9, rr["달성편차(bp)"])

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
