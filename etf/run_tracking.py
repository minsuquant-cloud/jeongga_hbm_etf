# -*- coding: utf-8 -*-
"""
etf/run_tracking.py — 실데이터 추적오차 리포트 (확정 구성표 기준)
=================================================================
확정 구성표(기본: 구성표_실사확정_20260725.csv — 12종목)의 확정 비중으로
실제 주가 1년을 재생해 지수를 만들고, ETF NAV 시나리오(TER × 매매비용 × 현금)
별 추적오차를 산출한다.

load_constituents()는 capacity·cu·compliance·benchmark 러너가 공유하는
**단일 구성 진입점**이다. 구 구성표(7종목)를 보려면 --constituents로 지정한다
— 기본값을 옛 파일로 두면 하위 러너 4개가 통째로 폐기 구성을 리포트한다.

사용법:
    .venv/Scripts/python.exe etf/run_tracking.py [--start 2025-07-25] [--end 오늘]
        [--constituents data/processed/구성표_실데이터_20260723.csv]

방법론 단순화 (정직 고지)
  - 리밸런싱: 분기 말마다 확정 비중으로 재고정(re-target). 실제 지수는
    정기변경 심사로 비중이 갱신되지만, 과거 심사 스냅샷(PIT 유동시총)이
    없으므로 확정 구성표 비중을 고정 목표로 쓴다. 회전율은 drift→재고정
    분만 계상되므로 실제(심사로 구성이 바뀌는 경우)보다 과소일 수 있다.
  - 가격: FinanceDataReader 수정주가(무상증자·분할 반영, 배당 미반영) — PR 계약.
출력: etf/output/tracking_scenarios.csv + 콘솔 리포트
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest.backtest import make_event, simulate_index, summary  # noqa: E402
from etf.nav_sim import scenario_grid, simulate_etf_nav, tracking_report  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
CONSTITUENTS = os.path.join(PROC, "구성표_실사확정_20260725.csv")   # 최종 12종목
OUT_DIR = os.path.join(BASE, "etf", "output")


def load_constituents(path: str | None = None) -> pd.DataFrame:
    """확정 구성표를 읽는다. 어느 파일을 썼는지 attrs["source"]에 남긴다.

    리포트마다 구성 출처를 찍게 해서, 구 구성표로 산출한 수치가 최종본으로
    오인되는 사고(7종목 리포트가 12종목 확정본 행세)를 막는다.
    """
    src = path or CONSTITUENTS
    c = pd.read_csv(src, encoding="utf-8-sig")
    c["코드"] = c["코드"].astype(str).str.zfill(6)     # 5930 → 005930
    w = c["편입비중(%)"].astype(float)
    if abs(w.sum() - 100.0) > 0.5:
        raise ValueError(f"구성표 비중 합 {w.sum():.2f}% ≠ 100% — 파일 확인 필요")
    c.attrs["source"] = os.path.basename(src)
    return c


def source_line(c: pd.DataFrame) -> str:
    """리포트 머리글용 구성 출처 한 줄."""
    return f"구성: {c.attrs.get('source', '?')} ({len(c)}종목)"


def fetch_prices(codes: list[str], start: str, end: str) -> pd.DataFrame:
    """수정종가. 융합 데이터셋이 있으면 그것을 쓰고, 없으면 FDR로 조회한다.

    오프라인을 우선하는 이유는 속도가 아니라 **일관성**이다. 종목마다 다른 시점에
    네트워크로 받아오면 실행할 때마다 결과가 미묘하게 달라진다.
    """
    try:
        from etf.hist_data import prices_offline
        df = prices_offline(codes, start, end)
        if len(df) and df.shape[1] == len(codes):
            return df
    except Exception:
        pass
    import FinanceDataReader as fdr
    px = {}
    for code in codes:
        s = fdr.DataReader(code, start, end)["Close"]
        if len(s) == 0:
            raise RuntimeError(f"가격 조회 실패: {code}")
        px[code] = s
    df = pd.DataFrame(px).dropna(how="all")
    # fail-closed: 중간 결측은 엔진(simulate_index)이 예외로 잡는다 — 여기서
    # 임의 보간하지 않는다(팀 원칙).
    return df


def build_events(prices: pd.DataFrame, weights: pd.Series) -> list:
    """최초 편입 + 분기 말 재고정. weights: {code: 비중(합 1)}"""
    events = [make_event(prices.index[0], "regular", weights)]
    q_ends = prices.groupby([prices.index.year, prices.index.quarter]) \
        .apply(lambda g: g.index.max())
    for d in sorted(q_ends)[:-1]:                     # 마지막 분기말은 표본 끝
        if d > prices.index[0]:
            events.append(make_event(d, "regular", weights))
    return events


def main():
    ap = argparse.ArgumentParser(description="실데이터 ETF 추적오차 리포트")
    today = dt.date.today()
    ap.add_argument("--start", default=str(today - dt.timedelta(days=365)))
    ap.add_argument("--end", default=str(today))
    ap.add_argument("--constituents", default=None,
                    help="구성표 CSV 경로 (기본: 실사확정 12종목)")
    args = ap.parse_args()

    c = load_constituents(args.constituents)
    codes = c["코드"].tolist()
    weights = pd.Series((c["편입비중(%)"] / 100.0).values, index=codes)
    weights = weights / weights.sum()

    print(f"{source_line(c)}, 기간 {args.start} ~ {args.end}")
    prices = fetch_prices(codes, args.start, args.end)
    print(f"가격 {len(prices)}거래일 × {len(prices.columns)}종목 수집")

    events = build_events(prices, weights)
    bt = simulate_index(prices, events)
    print("\n[지수 성과]")
    print(summary(bt).to_string())

    # 대표 시나리오 상세 (TER 45bp — 국내 테마 ETF 중앙값 근방, 비용 30bp, 현금 1%)
    ter, cost, cash = 45.0, 30.0, 0.01
    nav = simulate_etf_nav(bt, ter_bp=ter, trade_cost_bp=cost, cash_weight=cash)
    rep = tracking_report(bt, nav, ter, cost, cash)
    print(f"\n[대표 시나리오: TER {ter:g}bp · 비용 {cost:g}bp · 현금 {cash:.0%}]")
    print(rep.to_string())

    grid = scenario_grid(bt, ter_bps=(15, 30, 45), cost_bps=(10, 30),
                         cash_weights=(0.0, 0.01))
    os.makedirs(OUT_DIR, exist_ok=True)
    out_csv = os.path.join(OUT_DIR, "tracking_scenarios.csv")
    grid.round(3).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n[시나리오 그리드 12종] → {out_csv}")
    print(grid.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
