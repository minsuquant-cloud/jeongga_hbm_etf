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
  총괴리(bp)      = 0.5 × Σ|실제 - 목표| × 1e4   (편도 회전율과 같은 척도)
  0주 종목        = 비중이 작고 주가가 높으면 floor가 0주를 만들 수 있다 —
                    구성종목이 PDF에서 통째로 빠지는 것이므로 명시 경고한다.

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
        "cash_weight_bp": cash / cu_notional * 1e4,
        "cu_shares": cu_notional / nav_per_share,
        "total_dev_bp": 0.5 * float(dev_bp.abs().sum()),
        "max_dev_bp": float(dev_bp.abs().max()),
        "zero_share": shares.index[shares == 0].tolist(),
    }


def min_cu_notional(weights: pd.Series, prices: pd.Series,
                    max_total_dev_bp: float = 10.0,
                    candidates_eok: tuple = (1, 2, 3, 5, 7, 10, 15, 20, 30, 50),
                    nav_per_share: float = 10_000.0) -> pd.DataFrame:
    """후보 CU 규모별 괴리를 훑어 허용치를 만족하는 최소 규모를 찾는다.

    반환: 후보별 비교표 (총괴리·최대괴리·현금비중·0주 종목 수·충족 여부).
    충족 = 총괴리 ≤ 허용치 AND 0주 종목 없음.
    """
    rows = []
    for eok in candidates_eok:
        r = build_pdf(weights, prices, eok * EOK, nav_per_share)
        rows.append({
            "CU금액(억)": eok,
            "1CU ETF좌수": int(r["cu_shares"]),
            "총괴리(bp)": round(r["total_dev_bp"], 2),
            "최대괴리(bp)": round(r["max_dev_bp"], 2),
            "현금(bp)": round(r["cash_weight_bp"], 2),
            "0주 종목수": len(r["zero_share"]),
            "충족": r["total_dev_bp"] <= max_total_dev_bp
                    and len(r["zero_share"]) == 0,
        })
    return pd.DataFrame(rows)
