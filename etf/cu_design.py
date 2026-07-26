# -*- coding: utf-8 -*-
"""
etf/cu_design.py — CU(설정단위)·PDF(납부자산구성내역) 설계 (레이어 3단계)
=========================================================================
ETF는 AP(지정참가회사)가 CU 단위로 설정/환매한다. 1 CU에 담을 종목별
**정수 주식수**를 정하면, 반올림 때문에 실제 비중이 목표 비중에서 어긋난다.
CU 규모가 클수록 괴리는 줄어든다 — "괴리 허용치를 만족하는 최소 CU 규모"가
설계 산출물이다.

PDF 산정 규칙 (기본: floor + 현금)
  주식수(i) = floor(CU금액 × w(i) / 가격(i))
  현금     = CU금액 - Σ 주식수×가격   (항상 ≥ 0 — 초과 납부가 없어 실무 안전)
  "round" 모드는 괴리가 더 작지만 현금이 음수가 될 수 있어 검증용으로만 둔다.

괴리 지표
  종목별 괴리(bp) = (실제비중 - 목표비중) × 1e4
  총괴리(bp)      = 0.5 × (Σ|실제 - 목표| + |현금비중|) × 1e4
                    **현금을 목표비중 0인 포지션으로 세어 넣는다.** floor는 항상
                    미달 매수라 종목 편차가 전부 음수이고, 그 부족분은 통째로
                    현금에 쌓인다. 현금을 빼고 0.5를 곱하면 지표가 실제 이탈의
                    정확히 절반이 되어(= 현금비중/2) 허용치 게이트를 헐겁게
                    통과시킨다. 현금까지 넣으면 floor 모드에서 총괴리 = 현금비중이
                    되고, 이는 "PDF를 지수에 맞추는 데 필요한 편도 매매량"이라는
                    회전율 척도 해석과도 정합한다.
  종목괴리(bp)    = 0.5 × Σ|실제 - 목표| × 1e4  (현금 제외 — 분해용 참고치)
  0주 종목        = 비중이 작고 주가가 높으면 floor가 0주를 만들 수 있다 —
                    구성종목이 PDF에서 통째로 빠지는 것이므로 명시 경고한다.

강건성 (cu_robustness)
  후보별 괴리는 "오늘 종가"라는 한 점에서만 잰 값이다. 반올림 격자는 주가에
  민감해서 후보 순서가 비단조로 뒤집히기도 한다(7억이 10억보다 좋게 나오는 식).
  가격을 ±shock로 교란해 허용치 초과율을 재고, 오늘 운으로 통과한 후보와
  어떤 가격에서도 통과하는 후보를 구분한다.

관행 참고: 국내 ETF 1좌 최초 NAV 10,000원, 1 CU = 보통 5만~20만 좌
(= 5억~20억 원). cu_shares(1CU당 ETF 좌수) = CU금액 / 좌당 NAV.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EOK = 1e8

# 총괴리 허용치. 현금을 뺀 옛 지표에 걸던 10bp는 실제 이탈 기준으로는 20bp였다
# (지표가 정확히 절반이었으므로). 지표를 바로잡으면서 허용치를 15bp로 두면
# 실질 기준은 20bp → 15bp로 **엄격해진다**. 느슨해진 게 아니다.
DEFAULT_MAX_DEV_BP = 15.0


def build_pdf(weights: pd.Series, prices: pd.Series, cu_notional: float,
              nav_per_share: float = 10_000.0,
              mode: str = "floor_cash") -> dict:
    """1 CU의 납부자산구성내역(PDF)을 산정한다.

    weights : {code: 목표비중(합 1)} / prices : {code: 현재가(원)}
    cu_notional : 1 CU 금액(원) / nav_per_share : ETF 1좌 NAV(원)
    반환: {"pdf": DataFrame, "cash": 현금(원), "cu_shares": 1CU당 ETF 좌수,
           "total_dev_bp": 총괴리, "max_dev_bp": 최대 종목 괴리,
           "zero_share": 0주가 된 종목 리스트}
    """
    if abs(float(weights.sum()) - 1.0) > 1e-6:
        raise ValueError(f"비중 합 {weights.sum():.6f} ≠ 1")
    if cu_notional <= 0 or nav_per_share <= 0:
        raise ValueError("cu_notional·nav_per_share는 양수여야 합니다")
    missing = weights.index.difference(prices.index)
    if len(missing):
        raise ValueError(f"가격 누락 종목: {missing.tolist()}")
    px = prices.reindex(weights.index).astype(float)
    if (px <= 0).any() or px.isna().any():
        raise ValueError(f"가격이 0 이하/결측: {px.index[(px <= 0) | px.isna()].tolist()}")

    ideal = cu_notional * weights / px                    # 이상적(실수) 주식수
    if mode == "floor_cash":
        shares = np.floor(ideal).astype(int)
    elif mode == "round":
        shares = ideal.round().astype(int)
    else:
        raise ValueError(f"mode는 'floor_cash' 또는 'round' — 받은 값: {mode!r}")

    amount = shares * px
    cash = float(cu_notional - amount.sum())              # floor_cash면 항상 ≥ 0
    actual_w = amount / cu_notional
    dev_bp = (actual_w - weights) * 1e4
    cash_bp = cash / cu_notional * 1e4                    # 목표 0인 포지션의 편차

    pdf = pd.DataFrame({
        "목표비중(%)": weights * 100,
        "가격": px,
        "주식수": shares,
        "금액(원)": amount,
        "실제비중(%)": actual_w * 100,
        "괴리(bp)": dev_bp,
    })
    return {
        "pdf": pdf,
        "cash": cash,
        "cash_weight_bp": cash_bp,
        "cu_shares": cu_notional / nav_per_share,
        # 현금을 목표 0 포지션으로 포함 — floor 모드에서는 = cash_bp
        "total_dev_bp": 0.5 * float(dev_bp.abs().sum() + abs(cash_bp)),
        "stock_dev_bp": 0.5 * float(dev_bp.abs().sum()),   # 분해용(현금 제외)
        "max_dev_bp": float(dev_bp.abs().max()),
        "zero_share": shares.index[shares == 0].tolist(),
    }


def cu_robustness(weights: pd.Series, prices: pd.Series, cu_notional: float,
                  max_total_dev_bp: float = DEFAULT_MAX_DEV_BP,
                  shock: float = 0.05, n_trials: int = 300,
                  seed: int = 20260726,
                  nav_per_share: float = 10_000.0) -> pd.Series:
    """가격 교란 하에서 이 CU 규모가 허용치를 넘길 확률.

    가격에 종목별 독립 균등교란 ×(1±shock)를 주고 총괴리를 다시 잰다.
    목표비중은 고정 — 규정집이 정하는 값이라 가격과 함께 움직이지 않는다.
    seed 고정이라 결과는 재현 가능하다.

    반환: {초과율(%), 중앙 총괴리(bp), p95 총괴리(bp), 0주 발생률(%)}
    """
    if not 0 <= shock < 1:
        raise ValueError(f"shock은 [0, 1) — 받은 값: {shock}")
    if n_trials < 1:
        raise ValueError("n_trials는 1 이상이어야 합니다")
    rng = np.random.default_rng(seed)
    px = prices.reindex(weights.index).astype(float)
    devs, zeros = [], 0
    for _ in range(n_trials):
        shocked = px * (1.0 + rng.uniform(-shock, shock, len(px)))
        r = build_pdf(weights, shocked, cu_notional, nav_per_share)
        devs.append(r["total_dev_bp"])
        zeros += bool(r["zero_share"])
    d = np.asarray(devs)
    return pd.Series({
        "초과율(%)": float((d > max_total_dev_bp).mean() * 100),
        "중앙 총괴리(bp)": float(np.median(d)),
        "p95 총괴리(bp)": float(np.percentile(d, 95)),
        "0주 발생률(%)": zeros / n_trials * 100,
    })


def min_cu_notional(weights: pd.Series, prices: pd.Series,
                    max_total_dev_bp: float = DEFAULT_MAX_DEV_BP,
                    candidates_eok: tuple = (1, 2, 3, 5, 7, 10, 15, 20, 30, 50),
                    nav_per_share: float = 10_000.0,
                    shock: float = 0.05, n_trials: int = 300,
                    max_breach_pct: float = 0.0,
                    seed: int = 20260726) -> pd.DataFrame:
    """후보 CU 규모별 괴리를 훑어 허용치를 만족하는 최소 규모를 찾는다.

    충족 = 오늘 종가에서 총괴리 ≤ 허용치 AND 0주 종목 없음.
    강건 = 충족 AND 가격 ±shock 교란에서 초과율 ≤ max_breach_pct.

    max_breach_pct 기본 0 = **교란 n_trials회 전부 허용치 이내**. CU는 상장 후
    바꾸기 번거로운 계약 조건이라, 평균이 아니라 최악에 맞춘다. (유한 표본이라
    '초과율 0%'는 '300회 중 0회'라는 뜻이지 확률 0의 증명은 아니다.)

    '충족'만 보고 고르면 오늘 종가라는 한 점의 반올림 운에 기대게 된다 —
    권장 규모는 '강건'에서 고를 것. shock=0으로 주면 강건성 검정을 끈다.
    """
    rows = []
    for eok in candidates_eok:
        r = build_pdf(weights, prices, eok * EOK, nav_per_share)
        met = (r["total_dev_bp"] <= max_total_dev_bp
               and len(r["zero_share"]) == 0)
        row = {
            "CU금액(억)": eok,
            "1CU ETF좌수": int(r["cu_shares"]),
            "총괴리(bp)": round(r["total_dev_bp"], 2),
            "종목괴리(bp)": round(r["stock_dev_bp"], 2),
            "최대괴리(bp)": round(r["max_dev_bp"], 2),
            "현금(bp)": round(r["cash_weight_bp"], 2),
            "0주 종목수": len(r["zero_share"]),
            "충족": met,
        }
        if shock > 0:
            rb = cu_robustness(weights, prices, eok * EOK, max_total_dev_bp,
                               shock=shock, n_trials=n_trials, seed=seed,
                               nav_per_share=nav_per_share)
            row["초과율(%)"] = round(float(rb["초과율(%)"]), 1)
            row["p95 괴리(bp)"] = round(float(rb["p95 총괴리(bp)"]), 2)
            row["강건"] = met and rb["초과율(%)"] <= max_breach_pct
        rows.append(row)
    return pd.DataFrame(rows)
