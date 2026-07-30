# -*- coding: utf-8 -*-
"""
etf/replication.py — 개인 복제 최소 투자금액 (정수 주 격자, 교란 강건)
=====================================================================
실제 ETF 상장은 자산운용사만 가능하므로, 이 구성을 재현하려면 13종목을 직접
사야 한다. 정수 주 단위라 총액이 작으면 비중이 어긋난다 — "허용 편차 안에
들어오는 최소 금액"이 산출물이다.

왜 이분탐색을 버렸나 (2026-07-30)
---------------------------------
초기 구현은 `run_final_long.min_replication_cost`에 있었고 이분탐색을 썼다.
이분탐색은 **편차가 금액에 대해 단조 감소**한다고 가정하는데, 정수 주 격자
때문에 실제로는 톱니다. 결과:
  · 100bp 기준 답 1억 6,820만원 아래에 1억 5,979만원도 통과했다(최소가 아님)
  · 금액 ±5% 교란 21점 중 3점이 허용치 초과(최대 109.5bp) — 답이 강건하지 않다
  · 6,829만원 → 1억 6,820만원, 하루 가격 급락으로 2.5배 튀었다
CU에서 똑같은 함정을 이미 만났다(`cu_design.cu_robustness`) — 그 해법을 옮긴다.
  ① 이분탐색 대신 **로그 격자 전수 스캔** (톱니를 정면으로 훑는다)
  ② 가격 ±shock 교란에서 **전 시행 통과**하는 최소 금액을 권장
     (오늘 종가 한 점의 반올림 운에 기대지 않는다)

편차 지표 — CU와 같은 척도
--------------------------
floor 매수라 종목 편차가 전부 음수이고, 부족분은 통째로 현금에 쌓인다.
따라서 `Σ|실제 - 목표| = 현금비중`이며, 이는 `cu_design`의 (현금 포함) 총괴리와
같은 값이다. 두 지표를 같은 자로 읽을 수 있다.
0주 종목은 편차에 비중만큼 반영되지만, 구성종목이 통째로 빠지는 것이므로
별도로 세어 경고한다(CU와 동일).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 기본 허용 편차 — cu_design.DEFAULT_MAX_DEV_BP(15bp)와 달리 개인 복제는
# 금액 제약이 커서 실무적으로 100bp를 기본으로 본다(설계서도 100bp 기준 인용).
DEFAULT_TOL_BP = 100.0
DEFAULT_SHOCK = 0.05
DEFAULT_TRIALS = 200
DEFAULT_SEED = 20260730


def deviation_bp(weights: pd.Series, prices: pd.Series, total: float) -> float:
    """총액 `total`로 floor 매수했을 때의 비중 편차(bp) = 현금비중(bp)."""
    if total <= 0:
        raise ValueError("total은 양수여야 합니다")
    shares = np.floor(total * weights / prices)
    actual = (shares * prices).sum()
    return float((total - actual) / total) * 1e4


def _dev_vector(w: np.ndarray, px: np.ndarray, totals: np.ndarray) -> np.ndarray:
    """금액 배열에 대한 편차(bp) 벡터 — 격자 스캔용 벡터화."""
    ideal = totals[:, None] * w[None, :] / px[None, :]      # (T, N)
    actual = (np.floor(ideal) * px[None, :]).sum(axis=1)
    return (totals - actual) / totals * 1e4


def zero_share_count(weights: pd.Series, prices: pd.Series,
                     total: float) -> int:
    """0주가 되는 종목 수 — 구성종목이 통째로 빠지는 것이라 별도 경고 대상."""
    return int((np.floor(total * weights / prices) == 0).sum())


def replication_grid(weights: pd.Series, prices: pd.Series,
                     tol_bp: float = DEFAULT_TOL_BP,
                     lo: float = 1e7, hi: float = 1e10, n_points: int = 90,
                     shock: float = DEFAULT_SHOCK,
                     n_trials: int = DEFAULT_TRIALS,
                     seed: int = DEFAULT_SEED) -> pd.DataFrame:
    """로그 격자 금액별 편차 + 가격 교란 초과율.

    이분탐색이 아니라 전수 스캔이다 — 편차가 금액에 단조가 아니므로
    (정수 주 격자) 훑어서 실제 최소를 찾는다. shock=0이면 강건성 검정 생략.

    반환 컬럼: 금액 · 편차(bp) · 0주 · 충족 · 초과율(%) · p95 편차(bp)
    """
    if not 0 <= shock < 1:
        raise ValueError(f"shock은 [0, 1) — 받은 값: {shock}")
    if lo <= 0 or hi <= lo:
        raise ValueError("금액 범위는 0 < lo < hi 여야 합니다")
    px = prices.reindex(weights.index).astype(float)
    if px.isna().any() or (px <= 0).any():
        raise ValueError(f"가격 결측·비양수: {px.index[px.isna() | (px <= 0)].tolist()}")
    w = (weights / weights.sum()).to_numpy(dtype=float)
    p = px.to_numpy(dtype=float)

    totals = np.geomspace(lo, hi, n_points)
    base = _dev_vector(w, p, totals)

    if shock > 0:
        rng = np.random.default_rng(seed)
        shocked = p[None, :] * (1.0 + rng.uniform(-shock, shock,
                                                  (n_trials, len(p))))
        # (T, trials) — 금액 × 시행별 편차
        devs = np.empty((len(totals), n_trials))
        for j in range(n_trials):
            devs[:, j] = _dev_vector(w, shocked[j], totals)
        breach = (devs > tol_bp).mean(axis=1) * 100
        p95 = np.percentile(devs, 95, axis=1)
    else:
        breach = np.zeros(len(totals))
        p95 = base

    zeros = [zero_share_count(weights, px, t) for t in totals]
    met = (base <= tol_bp) & (np.asarray(zeros) == 0)
    return pd.DataFrame({
        "금액": totals, "편차(bp)": base.round(2), "0주": zeros,
        "충족": met, "초과율(%)": breach.round(1), "p95 편차(bp)": p95.round(2),
        "강건": met & (breach <= 0.0) & (np.asarray(zeros) == 0),
    })


def min_replication_cost(weights: pd.Series, prices: pd.Series,
                         tol_bp: float = DEFAULT_TOL_BP,
                         shock: float = DEFAULT_SHOCK,
                         n_trials: int = DEFAULT_TRIALS,
                         seed: int = DEFAULT_SEED,
                         n_points: int = 90) -> dict:
    """허용 편차를 **교란에도** 지키는 최소 투자금액.

    반환: 최소투자금액 · 달성편차(bp) · 0주 종목 · 현금 잔여(%) ·
          초과율(%) · p95 편차(bp) · 오늘만통과금액(참고 — 강건하지 않음)
    강건한 금액이 격자 안에 없으면 최소투자금액 = NaN (조용히 근사하지 않는다).
    """
    g = replication_grid(weights, prices, tol_bp=tol_bp, shock=shock,
                         n_trials=n_trials, seed=seed, n_points=n_points)
    lucky = g.loc[g["충족"], "금액"]
    firm = g.loc[g["강건"], "금액"]
    out = {
        "오늘만통과금액": float(lucky.iloc[0]) if len(lucky) else float("nan"),
        "최소투자금액": float(firm.iloc[0]) if len(firm) else float("nan"),
    }
    if len(firm):
        t = out["최소투자금액"]
        row = g.loc[g["금액"] == t].iloc[0]
        px = prices.reindex(weights.index).astype(float)
        shares = np.floor(t * (weights / weights.sum()) / px)
        out.update({
            "달성편차(bp)": float(row["편차(bp)"]),
            "0주 종목": int(row["0주"]),
            "현금 잔여(%)": float(1 - (shares * px).sum() / t) * 100,
            "초과율(%)": float(row["초과율(%)"]),
            "p95 편차(bp)": float(row["p95 편차(bp)"]),
        })
    else:
        out.update({"달성편차(bp)": float("nan"), "0주 종목": -1,
                    "현금 잔여(%)": float("nan"), "초과율(%)": float("nan"),
                    "p95 편차(bp)": float("nan")})
    return out
