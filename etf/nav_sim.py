# -*- coding: utf-8 -*-
"""
etf/nav_sim.py — HBM 지수 추종 ETF의 NAV 시뮬레이션 (추적오차 레이어 1단계)
==========================================================================
지수 백테스트(backtest.simulate_index)의 산출물 bt(level, turnover)를 소비해
ETF NAV 시계열을 만든다. 엔진 원칙을 따른다: 지수 재생 로직을 복제하지 않고,
공식 수치(bt["level"], bt["turnover"])에서만 파생한다.

NAV 모델 (일간)
---------------
  NAV(d) = NAV(d-1) × [1 + (1-cash_w)·r_idx(d) + cash_w·r_cash(d)]
                    × (1 - TER·Δ달력일/365)
                    × (1 - trade_cost·turnover(d)·(1-cash_w))   # 이벤트일만

구성 요소
  TER        : 총보수. **달력일 기준 일할 계상** (실무 관행 — NAV는 주말·휴일
               포함 매일 보수를 쌓으므로, 거래일 수(연 245~261일 변동)에
               드래그가 좌우되지 않도록 Δ달력일/365 로 차감한다).
  trade cost : 리밸런싱 실매매 비용(왕복 체결비용 bp × 편도 회전율) —
               지수의 apply_costs와 같은 척도라 지수-ETF 비교가 정합하다.
  cash drag  : 설정/환매 대응·배당 수령 지연으로 드는 현금 보유분.
               상승장에서 지수수익을 놓치는 만큼이 추적오차의 원천이 된다.

ETF 특유의 가정 (계약)
  초기 바스켓은 AP의 현물설정(in-kind)으로 납입된다고 가정 — 최초 편입일의
  매매비용은 0이다(bt의 첫 이벤트 회전율이 0인 것과 정합). 이후 리밸런싱은
  펀드 내 실매매로 보고 비용을 차감한다. (실무에서는 정기변경도 일부
  현물교체가 가능하므로 이 모델은 보수적(비용 과대) 추정이다.)

드래그 분해 (drag_decomposition)
  로그수익률 공간에서 **정확 분해**한다: 지수·NAV의 로그 CAGR 차이(bp/년)를
  TER·매매비용의 로그 기여로 나누고, 잔여를 현금 드래그로 귀속한다.
  구성상 '합계 = 실측'이 항등식이라(부동소수 오차 제외) 경로 의존 근사가 없다.
  산술 CAGR 갭은 지수 성과와 곱으로 얽혀(하락장에선 같은 비용도 작아 보임)
  분해 지표로 쓰지 않는다.

추적오차 판정은 기존 backtest.tracking_metrics(지수 vs NAV)로 한다 —
"지수 레벨만으로 계산한 0% 추종오차는 검증이 아니다" 원칙 준수.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest.backtest import tracking_metrics  # noqa: E402

CALENDAR_DAYS = 365.0     # TER 일할 계상 분모 (실무 관행)


def _fee_cost_factors(bt: pd.DataFrame, ter_bp: float, trade_cost_bp: float,
                      cash_weight: float,
                      foreign_cost_bp: float | None = None
                      ) -> tuple[pd.Series, pd.Series]:
    """일자별 (TER 차감계수, 매매비용 차감계수). NAV·분해가 같은 값을 쓴다.

    foreign_cost_bp를 주고 bt에 turnover_foreign이 있으면 **해외 회전율에만**
    그 비용을 적용한다(국내는 trade_cost_bp 그대로). MU 같은 해외 편입분은
    해외 수수료 + 환전 스프레드가 붙어 국내와 체결비용이 다르기 때문이다.
    turnover_foreign이 없으면(구 산출물·순수 국내 구성) 전액 국내로 본다 —
    하위호환.
    """
    idx = bt.index
    gap_days = idx.to_series().diff().dt.days.fillna(0.0)   # 첫날 = 설정일(보수 0)
    ter_factor = 1.0 - ter_bp / 1e4 * gap_days / CALENDAR_DAYS

    tno_fr = bt["turnover_foreign"] if (foreign_cost_bp is not None
                                        and "turnover_foreign" in bt.columns) \
        else pd.Series(0.0, index=idx)
    tno_kr = bt["turnover"] - tno_fr
    if (tno_kr < -1e-12).any():
        raise ValueError("turnover_foreign이 turnover보다 큼 — 산출물 확인")
    cost_rate = (trade_cost_bp * tno_kr
                 + (foreign_cost_bp if foreign_cost_bp is not None
                    else trade_cost_bp) * tno_fr) / 1e4
    cost_factor = 1.0 - cost_rate * (1.0 - cash_weight)
    if (ter_factor <= 0).any() or (cost_factor <= 0).any():
        raise ValueError("차감계수가 0 이하 — ter_bp/trade_cost_bp 값을 확인하세요")
    return ter_factor, cost_factor


def simulate_etf_nav(bt: pd.DataFrame,
                     ter_bp: float = 30.0,
                     trade_cost_bp: float = 30.0,
                     cash_weight: float = 0.0,
                     cash_rate_annual: float = 0.0,
                     base: float = 10_000.0,
                     foreign_cost_bp: float | None = None) -> pd.Series:
    """지수 백테스트 결과로 ETF NAV를 재생한다.

    Parameters
    ----------
    bt : simulate_index() 반환 DataFrame (level, turnover 필수)
    ter_bp : 총보수(연, bp). 예: 30bp = 0.30%
    trade_cost_bp : 리밸런싱 왕복 체결비용(bp) — 편도 회전율에 곱한다
    cash_weight : 상시 현금 보유 비중 (0~0.1 권장). 지수 노출은 1-cash_weight
    cash_rate_annual : 현금 수익률(연). 0이면 순수 드래그
    base : NAV 시작값 (관행상 1좌 10,000원)
    foreign_cost_bp : 해외 편입분의 왕복 체결비용(bp). None이면 국내와 동일.
        bt에 turnover_foreign이 있을 때만 적용된다.
    """
    if not {"level", "turnover"}.issubset(bt.columns):
        raise ValueError("bt에는 level·turnover 컬럼이 필요합니다 (simulate_index 산출물)")
    if not 0.0 <= cash_weight < 1.0:
        raise ValueError(f"cash_weight는 [0, 1) — 받은 값: {cash_weight}")
    if ter_bp < 0 or trade_cost_bp < 0:
        raise ValueError("ter_bp·trade_cost_bp는 음수가 될 수 없습니다")
    if foreign_cost_bp is not None and foreign_cost_bp < 0:
        raise ValueError("foreign_cost_bp는 음수가 될 수 없습니다")

    r_idx = bt["level"].pct_change(fill_method=None).fillna(0.0)
    gap_days = bt.index.to_series().diff().dt.days.fillna(0.0)
    r_cash = cash_rate_annual * gap_days / CALENDAR_DAYS
    ter_factor, cost_factor = _fee_cost_factors(bt, ter_bp, trade_cost_bp,
                                                cash_weight, foreign_cost_bp)
    growth = (1.0 + (1.0 - cash_weight) * r_idx + cash_weight * r_cash) \
        * ter_factor * cost_factor
    return base * growth.cumprod()


def drag_decomposition(bt: pd.DataFrame, nav: pd.Series,
                       ter_bp: float, trade_cost_bp: float,
                       cash_weight: float = 0.0,
                       foreign_cost_bp: float | None = None) -> pd.Series:
    """지수 대비 NAV 부진(연율 bp)의 로그 정확 분해.

    실측 갭(로그 CAGR 차) = TER 기여 + 매매비용 기여 + 현금 기여(잔여).
    구성상 합계가 실측과 일치한다(항등 분해 — 경로 의존 근사 없음).
    """
    yrs = (bt.index[-1] - bt.index[0]).days / 365.25
    if yrs <= 0:
        raise ValueError("기간이 0 이하입니다")
    ter_factor, cost_factor = _fee_cost_factors(bt, ter_bp, trade_cost_bp,
                                                cash_weight, foreign_cost_bp)
    measured = (np.log(bt["level"].iloc[-1] / bt["level"].iloc[0])
                - np.log(nav.iloc[-1] / nav.iloc[0])) / yrs * 1e4
    ter_part = -float(np.log(ter_factor).sum()) / yrs * 1e4
    cost_part = -float(np.log(cost_factor).sum()) / yrs * 1e4
    cash_part = float(measured - ter_part - cost_part)      # 잔여 = 노출부족 순효과
    return pd.Series({
        "실측 갭(로그 bp/년)": float(measured),
        "TER 기여(bp/년)": ter_part,
        "매매비용 기여(bp/년)": cost_part,
        "현금 기여(bp/년)": cash_part,
        "연율화 편도회전율": float(bt["turnover"].sum() / yrs),
    })


def tracking_report(bt: pd.DataFrame, nav: pd.Series,
                    ter_bp: float, trade_cost_bp: float,
                    cash_weight: float = 0.0,
                    foreign_cost_bp: float | None = None) -> pd.Series:
    """추적오차 공식 리포트 = 기존 tracking_metrics(지수 vs NAV) + 드래그 분해."""
    # simulate_index는 bt.attrs["event_log"]에 DataFrame을 싣는데, bt["level"]이
    # 이 attrs를 상속하면 pandas concat의 attrs 비교(__finalize__)가
    # "truth value of a DataFrame is ambiguous"로 죽는다 → attrs 제거 사본 사용.
    level = bt["level"].copy()
    level.attrs = {}
    nav = nav.copy()
    nav.attrs = {}
    tm = tracking_metrics(level, nav)
    dd = drag_decomposition(bt, nav, ter_bp, trade_cost_bp, cash_weight,
                            foreign_cost_bp)
    return pd.concat([tm, dd])


def scenario_grid(bt: pd.DataFrame,
                  ter_bps: tuple = (15.0, 30.0, 45.0),
                  cost_bps: tuple = (10.0, 30.0),
                  cash_weights: tuple = (0.0, 0.02)) -> pd.DataFrame:
    """TER × 매매비용 × 현금보유 시나리오별 추적오차·드래그 비교표."""
    rows = []
    for ter in ter_bps:
        for cost in cost_bps:
            for cw in cash_weights:
                nav = simulate_etf_nav(bt, ter_bp=ter, trade_cost_bp=cost,
                                       cash_weight=cw)
                rep = tracking_report(bt, nav, ter, cost, cw)
                rows.append({
                    "TER(bp)": ter, "매매비용(bp)": cost, "현금(%)": cw * 100,
                    "추종오차(연율,bp)": rep["추종오차(연율)"] * 1e4,
                    "누적 추종차이(%)": rep["누적 추종차이"] * 100,
                    "실측 갭(로그 bp/년)": rep["실측 갭(로그 bp/년)"],
                    "TER 기여(bp/년)": rep["TER 기여(bp/년)"],
                    "매매비용 기여(bp/년)": rep["매매비용 기여(bp/년)"],
                    "현금 기여(bp/년)": rep["현금 기여(bp/년)"],
                })
    return pd.DataFrame(rows)
