# -*- coding: utf-8 -*-
"""
etf/hist_data.py — 12.5년 장기 시세 로더 (FnGuide 데이터셋)

왜 필요한가
-----------
기존 `run_tracking.py`·`run_stress.py`는 pykrx/FDR로 **최근 1년**을 받아 쓴다.
그 1년이 하필 +207% 초강세장이라 "험한 날" 표본이 사실상 없었다. 실측 MDD도
현재진행형 조정장 하나(-30.8%)뿐이었다.

`D:\\data`의 FnGuide 데이터셋에는 2014-01~2026-06 12.5년이 있고, 여기엔 반도체가
실제로 무너진 구간들이 들어 있다 — 2018년 사이클 붕괴, 2020년 코로나, 2022년 금리인상기.
지금까지의 숫자가 그때도 버티는지 재려면 이 데이터가 필요하다.

상장 시점 처리
--------------
12종목의 데이터 시작일이 제각각이다(2014년 6종목 / 2018~2023년 6종목).
**그 시점에 존재하지 않던 종목을 소급 편입하면 그 자체가 룩어헤드다.**
그래서 매 시점 살아있는 종목만으로 비중을 재정규화한다(`pit_weights`).
편입 종목 수는 결과에 함께 기록해 어느 구간이 몇 종목 기준인지 드러나게 한다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# 융합본(_live: FnGuide 12.5년 + 실시간)이 있으면 우선 사용.
_LIVE, _SNAP = Path(r"D:/data/_live"), Path(r"D:/data/_derived")
DERIVED = Path(os.environ.get(
    "QUANT_DATA_DERIVED",
    _LIVE if (_LIVE / "price_adj_close.parquet").exists() else _SNAP))
BASE = Path(__file__).resolve().parent.parent
FINAL = BASE / "data" / "processed" / "구성표_실사확정_20260725.csv"

FIELDS = {"Open": "price_adj_open", "High": "price_adj_high",
          "Low": "price_adj_low", "Close": "price_adj_close",
          "Volume": "price_volume", "Value": "price_value_traded"}


def load_composition() -> pd.Series:
    """확정 구성표 → 코드별 목표비중(합 1)."""
    c = pd.read_csv(FINAL, encoding="utf-8-sig")
    c["코드"] = c["코드"].astype(str).str.zfill(6)
    w = pd.Series((c["편입비중(%)"] / 100.0).values, index=c["코드"].tolist())
    return w / w.sum()


def load_names() -> pd.Series:
    c = pd.read_csv(FINAL, encoding="utf-8-sig")
    c["코드"] = c["코드"].astype(str).str.zfill(6)
    return c.set_index("코드")["종목명"]


def load_field(field: str, codes: list[str]) -> pd.DataFrame:
    """Date × Code 와이드 시세. field는 FIELDS의 키."""
    df = pd.read_parquet(DERIVED / f"{FIELDS[field]}.parquet")
    have = [c for c in codes if c in df.columns]
    return df[have].astype("float64")


def pit_weights(close: pd.DataFrame, target: pd.Series) -> pd.DataFrame:
    """매 시점 '살아있는 종목'만으로 재정규화한 비중.

    상장 전·상장폐지 후에는 비중 0. 남은 종목끼리 목표비중 비율을 유지한다.
    """
    alive = close.notna()
    w = alive.astype(float).mul(target.reindex(close.columns).fillna(0.0), axis=1)
    # pd.NA는 object dtype으로 승격돼 fillna에서 downcasting 경고를 낸다 — float NaN 사용
    total = w.sum(axis=1).replace(0.0, float("nan"))
    return w.div(total, axis=0).fillna(0.0)


def simulate_reset_index(close: pd.DataFrame, target: pd.Series,
                         base: float = 1000.0) -> pd.DataFrame:
    """분기 재고정 지수 코어 — 데이터 로드가 없는 순수 함수(오프라인 테스트 대상).

    비중을 매일 목표로 되돌리면(연속 리밸런싱) 실제로는 매일 매매가 일어나는데,
    `|w_t - w_{t-1}|`로 회전율을 재면 목표가 상수라 0이 나온다. 비중 유지에 드는
    매매를 통째로 빠뜨리는 것이다 — 초기 구현이 그랬고, 매매비용이 17bp에서
    0.2bp로 줄어든 것처럼 보였다.

    그래서 실제 운용대로 **구간 중에는 비중이 가격에 따라 표류하게 두고,
    분기 말에만 목표로 되돌린다.** 회전율은 그 되돌림에서 나오는 매매만 센다.

    target은 합이 1이 아니어도 내부에서 정규화한다(동일가중 반사실 등
    임의 비중을 그대로 넘길 수 있게).

    반환: level(지수), turnover(편도 = 교체비율), n_stocks(당시 편입 수)
    """
    target = target / target.sum()
    tgt = pit_weights(close, target)          # 시점별 목표(살아있는 종목만)
    # 결측 구간은 최종가 유지(carry)와 동치가 되도록 명시적 ffill 후 수익률 산출
    # (pct_change 기본 pad와 같은 동작 — pandas 기본값 제거 예고에 따라 명시).
    # 상장폐지 후에는 0% 수익률로 얼어붙지만, 다음 분기 재고정에서 tgt가 그
    # 종목을 0으로 되돌리므로 지수에 기여하지 않는다. 상장 전 구간은 비중 0.
    ret = close.ffill().pct_change(fill_method=None).fillna(0.0)
    resets = set(close.groupby([close.index.year, close.index.quarter])
                      .apply(lambda g: g.index.max()).tolist())

    w = tgt.iloc[0].copy()
    levels, tnos, ns = [], [], []
    lvl = base
    for i, d in enumerate(close.index):
        if i > 0:
            grown = w * (1 + ret.loc[d].fillna(0.0))
            tot = float(grown.sum())
            if tot > 0:
                lvl *= tot
                w = grown / tot                # 표류한 비중
        tno = 0.0
        if i == 0 or d in resets:
            new = tgt.loc[d]
            if float(new.sum()) > 0:
                tno = float((new - w).abs().sum()) / 2
                w = new.copy()
        levels.append(lvl)
        tnos.append(tno)
        ns.append(int((w > 0).sum()))

    return pd.DataFrame({"level": levels, "turnover": tnos, "n_stocks": ns,
                         "reason": ""}, index=close.index)


def build_index(start: str = "2014-01-02", end: str | None = None,
                base: float = 1000.0,
                target: pd.Series | None = None) -> pd.DataFrame:
    """PIT 재정규화 지수 + 회전율 (로더 + simulate_reset_index).

    target을 주면 그 비중으로(예: 동일가중 반사실), 없으면 확정 구성표로 잰다.
    """
    tgt = load_composition() if target is None else target
    close = load_field("Close", tgt.index.tolist())
    close = close.loc[start:end] if end else close.loc[start:]
    return simulate_reset_index(close, tgt, base=base)


def prices_offline(codes: list[str], start: str | None = None,
                   end: str | None = None) -> pd.DataFrame:
    """수정종가 Date × Code. `run_tracking.fetch_prices`와 같은 형태.

    fail-closed 원칙에 따라 중간 결측을 보간하지 않는다 — 엔진이 잡게 둔다.
    """
    df = load_field("Close", codes)
    if start:
        df = df.loc[start:]
    if end:
        df = df.loc[:end]
    return df.dropna(how="all")


def adv_offline(codes: list[str], lookback_days: int = 60,
                end: str | None = None) -> pd.Series:
    """최근 N거래일 일평균 **실측 거래대금**(원).

    ⚠️ FnGuide 구간의 거래대금은 시간외·블록딜을 포함하는 것으로 보여 대형주에서
    정규장 대비 1.7~2.0배 크다(`D:\data\_live\volume_scale.csv`). 용량을
    보수적으로 재려면 `conservative_adv()`를 쓸 것.
    """
    df = load_field("Value", codes)
    if end:
        df = df.loc[:end]
    return df.tail(lookback_days).mean().rename("ADV")


def volume_scale() -> pd.Series:
    """종목별 거래량 정의 배율(FnGuide/pykrx). 없으면 빈 Series."""
    p = DERIVED.parent / "_live" / "volume_scale.csv"
    if not p.exists():
        return pd.Series(dtype=float)
    s = pd.read_csv(p, index_col=0, encoding="utf-8-sig").iloc[:, 0]
    s.index = s.index.astype(str).str.zfill(6)
    return s


def conservative_adv(codes: list[str], lookback_days: int = 60,
                     end: str | None = None) -> pd.Series:
    """정규장 기준 거래대금 추정 = 실측 ÷ 배율.

    시간외·블록딜은 원할 때 원하는 만큼 체결되지 않는다. 용량(며칠 만에 청산
    가능한가)을 재는 목적이면 정규장만 세는 편이 정직하다.
    """
    adv = adv_offline(codes, lookback_days, end)
    sc = volume_scale().reindex(adv.index).fillna(1.0).clip(lower=1.0)
    return (adv / sc).rename("ADV_regular")
