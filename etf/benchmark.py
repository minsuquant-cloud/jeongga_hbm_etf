# -*- coding: utf-8 -*-
"""
etf/benchmark.py — 기존 반도체 ETF 대비 비교 (레이어 4단계: HBM 순도)
=====================================================================
"왜 이 ETF를 사야 하나"의 정량 근거: 우리 지수의 차별점은 **HBM 순도**
(보유 비중 × HBM 노출도의 합)다. 경쟁 ETF의 실제 보유내역(PDF)에 우리
판정 데이터(판정완료 33종목의 HBM노출도)를 적용해 같은 잣대로 잰다.

정직 고지 (fail-closed 산출)
---------------------------
- 노출도는 우리가 판정한 33종목에만 있다. 경쟁 ETF가 담은 그 외 종목
  (해외주·비판정 국내주)은 노출도를 모른다 → **0으로 치지 않고** 두 값을
  함께 낸다:
    · 판정커버리지 = 판정된 종목이 차지하는 비중 합 (%)
    · 순도 하한    = Σ w×노출도 (비판정=0 가정 — 보수적 하한)
    · 커버 내 순도 = 판정된 비중만으로 정규화한 순도 (커버리지가 낮으면
                     대표성이 떨어짐을 함께 표기)
- 현금·선물 등 주식이 아닌 행은 비중 정규화 전에 제거한다.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
JUDGED = os.path.join(PROC, "판정완료_20260723.csv")
# 실사확정본은 HBM공정확인·위원회확인만 뒤집었고 노출도는 손대지 않았다.
# 그래도 노출도가 갈리면 순도 비교가 조용히 어긋나므로 매번 대조한다.
JUDGED_FINAL = os.path.join(PROC, "판정완료_20260725_실사확정.csv")


def _read_exposure(path: str) -> pd.Series:
    d = pd.read_csv(path, encoding="utf-8-sig")
    codes = d["코드"].astype(str).str.zfill(6)
    expo = pd.to_numeric(d["HBM노출도"], errors="coerce")
    if expo.max() > 1.5:                      # % 표기(0~100)면 소수로 환산
        expo = expo / 100.0
    return pd.Series(expo.values, index=codes).dropna()


def load_exposures() -> pd.Series:
    """판정완료 33종목의 HBM노출도(0~1). {6자리 코드: 노출도}

    두 판정 파일의 노출도가 어긋나면 예외 — 어느 쪽이 정본인지 사람이
    정해야 하는 상황이지 조용히 한쪽을 쓸 일이 아니다(fail-closed).
    """
    out = _read_exposure(JUDGED)
    if len(out) == 0:
        raise ValueError("판정완료에서 HBM노출도를 읽지 못함")
    if os.path.exists(JUDGED_FINAL):
        fin = _read_exposure(JUDGED_FINAL)
        common = out.index.intersection(fin.index)
        drift = common[(out[common] - fin[common]).abs() > 1e-9]
        if len(drift):
            raise ValueError(
                "판정 파일 간 HBM노출도 불일치 — 순도 비교의 잣대가 갈립니다: "
                f"{drift.tolist()} (기준 {os.path.basename(JUDGED)} vs "
                f"{os.path.basename(JUDGED_FINAL)})")
    return out


def purity_metrics(weights: pd.Series, exposure: pd.Series) -> pd.Series:
    """보유 비중(합 1) × 노출도 → 순도 지표 3종.

    weights : {code: 비중} (주식만, 합 1로 정규화된 상태)
    exposure: {code: HBM노출도(0~1)} — 판정된 종목만 존재
    """
    if len(weights) == 0:
        raise ValueError("보유 비중이 비어 있습니다")
    if weights.min() < -1e-9:
        raise ValueError("음수 비중 — 입력 확인 필요")
    w = weights / weights.sum()
    judged = w.index.intersection(exposure.index)
    coverage = float(w.loc[judged].sum())
    purity_lb = float((w.loc[judged] * exposure.loc[judged]).sum())
    purity_in = purity_lb / coverage if coverage > 0 else np.nan
    return pd.Series({
        "판정커버리지(%)": coverage * 100,
        "순도 하한(%)": purity_lb * 100,          # 비판정=0 보수 가정
        "커버 내 순도(%)": purity_in * 100,
    })


def overlap(w_a: pd.Series, w_b: pd.Series) -> float:
    """구성 겹침 = Σ min(w_a, w_b). 1이면 동일, 0이면 완전 상이."""
    a = w_a / w_a.sum()
    b = w_b / w_b.sum()
    union = a.index.union(b.index)
    return float(np.minimum(a.reindex(union, fill_value=0.0),
                            b.reindex(union, fill_value=0.0)).sum())


def fetch_etf_holdings(ticker: str, date: str) -> pd.Series:
    """pykrx ETF PDF → {6자리 코드: 비중(합 1)}. 주식 행만(현금·선물 제외).

    KRX 로그인(.env KRX_ID/KRX_PW) 필요. 실패 시 예외 — 조용히 빈 값을
    돌려주지 않는다(fail-closed).
    """
    from pykrx import stock as krx
    pdf = krx.get_etf_portfolio_deposit_file(ticker, date)
    if pdf is None or len(pdf) == 0:
        raise RuntimeError(f"ETF PDF 조회 실패(빈 응답): {ticker} @ {date} — "
                           "KRX 로그인(.env) 확인")
    idx = pdf.index.astype(str)
    # Index.str.fullmatch는 (Series와 달리) ndarray를 반환한다 — 그대로 마스크로 사용
    is_stock = np.asarray(idx.str.fullmatch(r"\d{6}"), dtype=bool)  # 6자리 = 국내 주식
    w = pd.to_numeric(pdf.loc[is_stock, "비중"], errors="coerce").dropna()
    w.index = idx[is_stock]
    w = w[w > 0]
    if len(w) == 0:
        raise RuntimeError(f"주식 보유가 없음(해외형/합성형?): {ticker}")
    total = float(pd.to_numeric(pdf["비중"], errors="coerce").fillna(0).sum())
    out = w / w.sum()
    out.attrs["stock_weight_pct"] = float(w.sum()) / total * 100 if total else np.nan
    return out
