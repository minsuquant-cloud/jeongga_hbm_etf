# -*- coding: utf-8 -*-
"""
etf/run_benchmark.py — 기존 반도체 ETF 대비 실데이터 비교 리포트
================================================================
경쟁 ETF의 실제 보유내역(KRX PDF)·가격으로 HBM 순도/구성 겹침/성과를
우리 지수와 같은 잣대로 비교한다.

사용법:
    .venv/Scripts/python.exe etf/run_benchmark.py
필요: .env에 KRX_ID/KRX_PW (pykrx PDF 조회용)

출력: etf/output/benchmark_report.csv + 콘솔 리포트
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from backtest.backtest import simulate_index, ann_vol, cagr, correlation  # noqa: E402
from etf.benchmark import (fetch_etf_holdings, load_exposures,  # noqa: E402
                           overlap, purity_metrics)
from etf.run_tracking import (build_events, fetch_prices,  # noqa: E402
                              load_constituents, source_line)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")

COMPETITORS = {
    "091160": "KODEX 반도체",
    "091230": "TIGER 반도체",
    "396500": "TIGER 반도체TOP10",
    "455850": "SOL AI반도체소부장",
    "471990": "KODEX AI반도체핵심장비",
    "442580": "PLUS 글로벌HBM반도체",
}


PROBE_TICKER = "091160"        # KODEX 반도체 — PDF 존재 여부 확인용 기준 ETF


def business_days_desc(limit: int = 10) -> list[str]:
    """오늘부터 거슬러 올라가는 영업일 목록(YYYYMMDD, 최신순).

    주말만 넘기면 광복절 같은 평일 휴장일을 못 걸러 PDF 조회가 빈 응답이 된다.
    거래소 영업일 캘린더(pykrx)를 우선 쓰고, 실패 시 주말만 넘기는 근사로
    폴백하되 폴백 사실을 로그로 남긴다.
    """
    today = dt.date.today()
    try:
        from pykrx import stock as krx
        days = krx.get_previous_business_days(
            fromdate=(today - dt.timedelta(days=40)).strftime("%Y%m%d"),
            todate=today.strftime("%Y%m%d"))
        if len(days):
            return [pd.Timestamp(d).strftime("%Y%m%d") for d in days][::-1][:limit]
        raise RuntimeError("영업일 캘린더가 비어 있음")
    except Exception as e:
        print(f"[경고] 영업일 캘린더 조회 실패({e}) → 주말만 넘기는 근사 사용")
        out, d = [], today
        while len(out) < limit:
            if d.weekday() < 5:
                out.append(d.strftime("%Y%m%d"))
            d -= dt.timedelta(days=1)
        return out


def resolve_pdf_date(limit: int = 4) -> str:
    """**PDF가 실제로 존재하는** 최근 영업일을 찾는다.

    영업일이라고 PDF가 있는 게 아니다 — 당일 보유내역은 장중·마감 직후엔
    아직 공시 전이라 빈 응답이 온다(2026-07-27 13시 실행에서 전 종목 NaN으로
    확인). 기준 ETF 하나로 실제 조회를 해보고 안 되면 하루씩 뒤로 물린다.
    limit을 크게 잡지 말 것 — KRX 조회 한 번이 수십 초라 탐색이 곧 대기시간이다.
    """
    for d in business_days_desc(limit):
        try:
            fetch_etf_holdings(PROBE_TICKER, d)
            return d
        except Exception:
            print(f"  [보유내역 미공시] {d} → 이전 영업일로")
    raise RuntimeError(
        f"최근 {limit}영업일 안에 조회 가능한 ETF 보유내역이 없습니다 — "
        "KRX 로그인(.env) 또는 장 상태를 확인하십시오")


def main():
    expo = load_exposures()
    c = load_constituents()
    codes = c["코드"].tolist()
    ours_w = pd.Series((c["편입비중(%)"] / 100.0).values, index=codes)
    ours_w = ours_w / ours_w.sum()

    # ── 우리 지수 1년 재생 (run_tracking과 동일 방법론) ────────────────
    today = dt.date.today()
    start = str(today - dt.timedelta(days=365))
    prices = fetch_prices(codes, start, str(today))
    bt = simulate_index(prices, build_events(prices, ours_w))
    level = bt["level"].copy(); level.attrs = {}

    rows = []
    ours_m = purity_metrics(ours_w, expo)
    rows.append({"ETF": "정가 HBM 지수(자체)", "코드": "-",
                 **ours_m.round(2).to_dict(),
                 "겹침 vs 자체(%)": 100.0,
                 "1년 수익률(%)": (level.iloc[-1] / level.iloc[0] - 1) * 100,
                 "연변동성(%)": ann_vol(level) * 100,
                 "상관계수": 1.0})

    import FinanceDataReader as fdr
    pdf_date = resolve_pdf_date()
    for tkr, name in COMPETITORS.items():
        try:
            hold = fetch_etf_holdings(tkr, pdf_date)
            m = purity_metrics(hold, expo)
            ov = overlap(ours_w, hold) * 100
        except Exception as e:
            print(f"[경고] {name}({tkr}) 보유내역 실패 → 순도 산출불가: {e}")
            m = pd.Series({"판정커버리지(%)": np.nan, "순도 하한(%)": np.nan,
                           "커버 내 순도(%)": np.nan})
            ov = np.nan
        try:
            px = fdr.DataReader(tkr, start, str(today))["Close"].dropna()
            ret = (px.iloc[-1] / px.iloc[0] - 1) * 100
            vol = ann_vol(px) * 100
            corr = correlation(level, px)
        except Exception as e:
            print(f"[경고] {name}({tkr}) 가격 실패: {e}")
            ret = vol = corr = np.nan
        rows.append({"ETF": name, "코드": tkr, **m.round(2).to_dict(),
                     "겹침 vs 자체(%)": round(ov, 1),
                     "1년 수익률(%)": round(ret, 1),
                     "연변동성(%)": round(vol, 1),
                     "상관계수": round(corr, 3) if corr == corr else np.nan})

    rep = pd.DataFrame(rows)
    # fail-closed: 순도 비교가 이 리포트의 존재 이유다. 경쟁사 보유내역이
    # 하나도 안 잡혔는데 저장하면, 멀쩡하던 직전 리포트를 NaN으로 덮어쓴다.
    if rep.iloc[1:]["순도 하한(%)"].notna().sum() == 0:
        raise RuntimeError(
            f"경쟁 ETF 보유내역을 하나도 받지 못했습니다(기준일 {pdf_date}) — "
            "기존 리포트를 덮어쓰지 않고 중단합니다. KRX 로그인·기준일 확인 필요")
    print(f"\n[HBM 순도·성과 비교] {source_line(c)} · "
          f"보유내역 기준일 {pdf_date} · 성과 1년")
    print(rep.to_string(index=False))
    print("\n읽는 법: '순도 하한'은 비판정 종목(해외주 등)을 0으로 치는 보수적 "
          "하한 — 커버리지가 낮은 ETF(글로벌형)의 실제 순도는 이보다 높을 수 "
          "있다. 같은 잣대(우리 판정 33종목)의 상대 비교로만 해석할 것.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_csv = os.path.join(OUT_DIR, "benchmark_report.csv")
    rep.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_csv}")


if __name__ == "__main__":
    main()
