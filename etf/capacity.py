# -*- coding: utf-8 -*-
"""
etf/capacity.py — ETF 용량(Capacity) 분석 (레이어 2단계)
========================================================
질문: "이 ETF는 AUM 얼마까지 소화 가능한가?"

방법
----
종목별 일평균 거래대금(ADV)에 대해, ETF가 시장 충격 없이 하루에 낼 수 있는
주문을 ADV × 참여율(participation)로 본다(실무 관행 10~25%). 그러면

  청산 소요일(t) = AUM × w(t) ÷ (참여율 × ADV(t))
  종목별 허용 AUM = 허용일수 × 참여율 × ADV(t) ÷ w(t)
  ETF 용량 = min(종목별 허용 AUM)  ← 병목(binding) 종목이 결정

두 관점을 함께 낸다:
  ① 전량 청산(liquidation): 포지션 전체를 허용일수 안에 — 위기 시 환매 대응력
  ② 리밸런싱(rebalance): 분기 재고정 시 |Δw|만 거래 — 평시 운용 부담

정직 고지
---------
- ADV는 최근 N거래일(기본 60일) 평균 — HBM 테마의 거래대금은 변동이 크므로
  강세장 ADV 기준 용량은 과대평가될 수 있다. 산출일을 함께 기록한다.
- 참여율·허용일수는 가정이다. 기본값(참여율 20%, 청산 5일·리밸 3일)을
  바꿔 민감도를 볼 수 있게 인자로 뺐다.
- ETF의 설정/환매가 현물(in-kind)로 이루어지면 펀드가 직접 매매하지 않으므로
  실제 용량은 이보다 크다 — 이 분석은 보수적 하한이다.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EOK = 1e8          # 1억 원


def capacity_table(weights: pd.Series, adv_krw: pd.Series,
                   aum_krw: float,
                   participation: float = 0.20,
                   rebalance_dw: pd.Series | None = None) -> pd.DataFrame:
    """주어진 AUM에서 종목별 소화 부담 표.

    weights : {code: 목표비중(합 1)} / adv_krw : {code: 일평균 거래대금(원)}
    rebalance_dw : {code: 리밸런싱 편도 |Δw|} (없으면 청산 관점만)
    """
    if abs(float(weights.sum()) - 1.0) > 1e-6:
        raise ValueError(f"비중 합 {weights.sum():.6f} ≠ 1")
    if not 0 < participation <= 1:
        raise ValueError(f"참여율은 (0,1] — 받은 값: {participation}")
    missing = weights.index.difference(adv_krw.index)
    if len(missing):
        raise ValueError(f"ADV 누락 종목: {missing.tolist()}")
    adv = adv_krw.reindex(weights.index).astype(float)
    if (adv <= 0).any():
        raise ValueError(f"ADV가 0 이하: {adv.index[adv <= 0].tolist()}")

    pos = aum_krw * weights
    daily = participation * adv
    out = pd.DataFrame({
        "비중(%)": weights * 100,
        "ADV(억)": adv / EOK,
        "포지션(억)": pos / EOK,
        "포지션/ADV(배)": pos / adv,
        "청산 소요일": pos / daily,
    })
    if rebalance_dw is not None:
        dw = rebalance_dw.reindex(weights.index).fillna(0.0).astype(float)
        out["리밸런싱 소요일"] = aum_krw * dw / daily
    return out


def max_aum(weights: pd.Series, adv_krw: pd.Series,
            participation: float = 0.20,
            max_days: float = 5.0) -> tuple[pd.Series, pd.Series]:
    """종목별 허용 AUM과 ETF 용량(=min, 병목 종목이 결정).

    반환: (요약 Series, 종목별 허용 AUM(원) Series)
    """
    capacity_table(weights, adv_krw, aum_krw=1.0,
                   participation=participation)            # 입력 검증 재사용
    per_stock = (max_days * participation
                 * adv_krw.reindex(weights.index) / weights)
    cap = float(per_stock.min())
    summary = pd.Series({
        "용량(억)": cap / EOK,
        "병목 종목": str(per_stock.idxmin()),
        "가정 참여율": participation,
        "가정 허용일수": max_days,
    })
    return summary, per_stock


def fetch_adv(codes: list[str], lookback_days: int = 60,
              end: str | None = None) -> pd.Series:
    """최근 N거래일 일평균 거래대금(원). pykrx 거래대금 우선, FDR 근사 폴백.

    FDR 폴백은 종가×거래량 근사(일중 체결가 분포 무시) — 사용 시 로그로 고지.
    """
    try:                      # 융합 데이터셋의 실측 거래대금 우선
        from etf.hist_data import adv_offline
        s_off = adv_offline(codes, lookback_days, end)
        if s_off.notna().all():
            print(f"[출처] ADV = 융합 데이터셋 실측 거래대금 ({len(codes)}종목)")
            return s_off
        gap = s_off.index[s_off.isna()].tolist()
        print(f"[출처] 융합 데이터셋에 거래대금 결측 {gap} → 네트워크 조회로 전환")
    except Exception as e:
        # 조용히 넘기지 않는다 — 리포트만 보고 어느 소스인지 알 수 없으면
        # 폐기 구성 사고와 같은 종류의 오독이 생긴다(source_line 원칙).
        print(f"[출처] 융합 데이터셋 ADV 실패({str(e)[:60]}) → 네트워크 조회로 전환")
    import datetime as dt
    end_d = pd.Timestamp(end or dt.date.today())
    start_d = end_d - pd.Timedelta(days=lookback_days * 2 + 10)
    adv = {}
    try:
        from pykrx import stock as krx
        for code in codes:
            df = krx.get_market_ohlcv(start_d.strftime("%Y%m%d"),
                                      end_d.strftime("%Y%m%d"), code)
            if len(df) == 0 or "거래대금" not in df.columns:
                raise RuntimeError(f"pykrx 거래대금 없음: {code}")
            adv[code] = float(df["거래대금"].tail(lookback_days).mean())
        return pd.Series(adv, name="ADV")
    except Exception as e:
        print(f"[경고] pykrx 실패({e}) → FDR 종가×거래량 근사로 폴백")
        import FinanceDataReader as fdr
        for code in codes:
            df = fdr.DataReader(code, start_d, end_d)
            val = (df["Close"] * df["Volume"]).tail(lookback_days)
            if len(val) == 0:
                raise RuntimeError(f"거래대금 산출 실패: {code}")
            adv[code] = float(val.mean())
        return pd.Series(adv, name="ADV(근사)")
