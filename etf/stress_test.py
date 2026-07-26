# -*- coding: utf-8 -*-
"""
etf/stress_test.py — 스트레스 테스트 (레이어 7단계)
===================================================
지금까지의 숫자는 전부 +207% 초강세장 1년에서 실측됐다 — 조건이 최상이었다는
뜻이다. 이 모듈은 같은 데이터에서 **험한 구간·험한 가정**을 잘라내 재측정한다.

시나리오
--------
[T1] 하락장 추적오차 — 실측 최대낙폭 구간(고점→저점)만 잘라 NAV 재생.
     상승장에서 '드래그'였던 현금이 하락장에선 방어가 되는지(부호 반전),
     보수·비용 갭은 그대로인지 확인한다.
[T2] 유동성 가뭄 용량 — 거래대금(ADV)을 ×0.5 / ×⅓로 깎아 용량 재산출.
     위기 시 거래 냉각은 통상 낙폭보다 먼저 온다.
[T3] 복합 — 하락장 + ADV 반토막에서 "AUM의 몇 %가 하루에 환매돼도
     감당 가능한가"(일일 환매 소화율)를 잰다. 실제 위기는 겹쳐서 온다.

정직성: 모든 스트레스는 실측 데이터의 변형(구간 절단·계수 축소)이며,
가상의 낙폭을 지어내지 않는다. 가정(계수)은 결과에 명기한다.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.capacity import EOK, max_aum  # noqa: E402
from etf.nav_sim import drag_decomposition, simulate_etf_nav  # noqa: E402


def drawdown_window(level: pd.Series) -> tuple:
    """최대낙폭 구간 (고점일, 저점일, 낙폭). 실측 경로에서 잘라낸다."""
    if len(level) < 3:
        raise ValueError("낙폭 구간을 찾기에 데이터가 너무 짧습니다")
    peak = level.cummax()
    dd = level / peak - 1.0
    trough = dd.idxmin()
    peak_date = level.loc[:trough].idxmax()
    if peak_date >= trough:
        raise ValueError("낙폭 구간이 성립하지 않습니다 (단조 상승 경로?)")
    return peak_date, trough, float(dd.min())


def stress_tracking(bt: pd.DataFrame, ter_bp: float = 45.0,
                    trade_cost_bp: float = 30.0,
                    cash_weight: float = 0.01) -> pd.DataFrame:
    """[T1] 전체 기간 vs 최대낙폭 구간의 드래그 분해 비교.

    NAV는 전체 기간으로 한 번 재생하고(경로 일관성), 분해만 구간 절단 —
    구간별로 NAV를 다시 시작하면 진입 시점 효과가 섞인다.
    """
    nav = simulate_etf_nav(bt, ter_bp=ter_bp, trade_cost_bp=trade_cost_bp,
                           cash_weight=cash_weight)
    peak_d, trough_d, mdd = drawdown_window(bt["level"])

    rows = {}
    for label, sl in (("전체 기간", slice(None, None)),
                      ("하락 구간", slice(peak_d, trough_d))):
        bt_s = bt.loc[sl]
        nav_s = nav.loc[sl]
        dd = drag_decomposition(bt_s, nav_s, ter_bp, trade_cost_bp, cash_weight)
        idx_ret = float(bt_s["level"].iloc[-1] / bt_s["level"].iloc[0] - 1)
        rows[label] = pd.concat([pd.Series({"지수수익률(%)": idx_ret * 100}),
                                 dd])
    out = pd.DataFrame(rows).T
    out.attrs["mdd"] = mdd
    out.attrs["window"] = (str(peak_d.date()), str(trough_d.date()))
    return out


def stress_capacity(weights: pd.Series, adv_krw: pd.Series,
                    factors: tuple = (1.0, 0.5, 1 / 3),
                    participation: float = 0.20,
                    max_days: float = 5.0) -> pd.DataFrame:
    """[T2] ADV 축소 계수별 용량. 용량은 ADV에 정비례하므로 결과도 비례 —
    그 '당연함'을 숫자로 박제하는 것이 목적이다(발표 답변용)."""
    rows = []
    for f in factors:
        s, per = max_aum(weights, adv_krw * f, participation=participation,
                         max_days=max_days)
        rows.append({
            "ADV 가정": f"×{f:.2f}" if f != 1.0 else "실측(강세장)",
            "용량(억)": round(s["용량(억)"], 0),
            "병목 종목": s["병목 종목"],
        })
    return pd.DataFrame(rows)


def stress_capacity_assumptions(weights: pd.Series, adv_krw: pd.Series,
                                participations: tuple = (0.30, 0.20, 0.15, 0.10),
                                day_grid: tuple = (5.0, 3.0),
                                adv_factor: float = 1.0) -> pd.DataFrame:
    """[T2b] 용량을 떠받치는 **가정 두 개**를 흔든다.

    T2는 ADV(관측치)만 흔들었지만, 용량 = 허용일수 × 참여율 × ADV / 비중 이므로
    참여율·청산 허용일수도 결과를 정비례로 좌우한다. 이 둘은 관측이 아니라
    우리가 고른 숫자라서, 안 흔들면 "1,994억"이 관측치인 양 읽힌다.

    기본 20%·5일은 넉넉한 쪽 가정이다 — 시장충격을 아끼려 참여율을 10%로 낮추고
    청산을 3일로 조이면 용량은 0.5×0.6 = 0.3배가 된다.
    """
    rows = []
    for part in participations:
        for days in day_grid:
            s, _ = max_aum(weights, adv_krw * adv_factor,
                           participation=part, max_days=days)
            rows.append({
                "참여율": f"{part:.0%}",
                "청산 허용일수": days,
                "용량(억)": round(s["용량(억)"], 0),
                "병목 종목": s["병목 종목"],
                "기준 대비": f"×{part / 0.20 * days / 5.0:.2f}",
            })
    out = pd.DataFrame(rows)
    out.attrs["adv_factor"] = adv_factor
    return out


def redemption_endurance(weights: pd.Series, adv_krw: pd.Series,
                         aum_krw: float, adv_factor: float = 0.5,
                         participation: float = 0.20) -> pd.Series:
    """[T3] 하루에 AUM의 몇 %까지 환매(현금 청산 가정)를 소화할 수 있나.

    일일 소화율 = min_i(참여율 × ADV_i × factor / (AUM × w_i)).
    현물환매(in-kind)면 이 제약이 사라진다 — 결과에 함께 명기.
    """
    if aum_krw <= 0:
        raise ValueError("aum_krw는 양수여야 합니다")
    w = weights / weights.sum()
    adv = adv_krw.reindex(w.index).astype(float) * adv_factor
    daily_capacity_ratio = (participation * adv / (aum_krw * w))
    worst = daily_capacity_ratio.idxmin()
    return pd.Series({
        "AUM(억)": aum_krw / EOK,
        "ADV 가정": f"×{adv_factor:.2f}",
        "일일 환매 소화율(%)": float(daily_capacity_ratio.min()) * 100,
        "병목 종목": str(worst),
        "비고": "현금 청산 가정 — 현물환매(in-kind) 시 제약 없음",
    })
