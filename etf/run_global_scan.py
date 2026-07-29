# -*- coding: utf-8 -*-
"""
etf/run_global_scan.py — 해외 후보의 관측 가능 지표 스캔 (실사 이전 단계)

실사(판정)와 관측을 분리한다. HBM노출도·공정확인은 문서 실사로만 정해지지만,
가격·낙폭·상관은 시장 관측치라 지금 잴 수 있다. 이 스캔은 **판정에 아무
입력도 제공하지 않는다** — "이 종목들이 내 지수 옆에서 어떻게 움직여 왔나"를
보여줄 뿐이다.

설계 결정 (미리 막은 함정)
--------------------------
- **전 지표 현지통화 기준.** KRW 환산은 환율 시계열 파이프라인이 갖춰진 뒤
  (글로벌 지수 산출 단계)에 한다 — 어설픈 환산이 지표를 오염시키는 것보다
  통화 표기를 명확히 하는 쪽이 정직하다. 원화 관점 변동은 여기에 환노출이
  추가로 얹힌다는 것만 명기한다.
- **JGHBM과의 상관은 주간 수익률.** 미국 종가는 한국의 다음 날 아침이라
  일간 동일날짜 상관은 시차 때문에 체계적으로 과소된다. 주간이면 시차가
  묻힌다.
- **위기구간 MDD는 표본이 충분할 때만.** 구간 거래일이 기대치의 60% 미만이면
  '표본부족'으로 표기한다(ONTO는 2019 상장이라 2018 구간이 없다). 부분
  표본으로 조용히 계산하면 낙폭이 얕아 보인다.
- 이 후보들 역시 **오늘 살아남은 승자다** — 여기 실린 수익률에도 생존 편향이
  있다. 수익률은 참고일 뿐, 판단 기준은 낙폭·상관이다.

    .venv/Scripts/python.exe etf/run_global_scan.py

산출: etf/output/global_scan.csv
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.global_candidates import registry  # noqa: E402
from etf.run_stress_long import CRISES  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "etf", "output")
JGHBM = Path(r"D:/data/_index/JGHBM.parquet")
MIN_COVERAGE = 0.60          # 위기구간 기대 거래일 대비 최소 표본 비율


def fetch_series(tickers: list[str]) -> tuple[pd.Series | None, str]:
    """조회티커 순서대로 시도(원주 우선) — 처음 성공한 것을 쓴다."""
    import FinanceDataReader as fdr
    for t in tickers:
        try:
            s = fdr.DataReader(t, "2014-01-01")["Close"].dropna()
            if len(s) >= 250:
                return s, t
        except Exception:
            continue
    return None, ""


def crisis_mdd(px: pd.Series, start: str, end: str | None,
               expected_days: int) -> str:
    win = px.loc[start:end] if end else px.loc[start:]
    if len(win) < expected_days * MIN_COVERAGE or len(win) < 20:
        return "표본부족"
    return f"{float((win / win.cummax() - 1).min()) * 100:.1f}"


def weekly_corr(a: pd.Series, b: pd.Series, min_obs: int = 30) -> float:
    """주간(금요일 마감) 수익률 상관 — 시차 완화. 표본 부족이면 NaN."""
    wa = a.resample("W-FRI").last().pct_change(fill_method=None)
    wb = b.resample("W-FRI").last().pct_change(fill_method=None)
    pair = pd.concat([wa, wb], axis=1, join="inner").dropna()
    if len(pair) < min_obs:
        return float("nan")
    return float(pair.corr().iloc[0, 1])


def main() -> int:
    if JGHBM.exists():
        jg = pd.read_parquet(JGHBM)["Close"]
        jg_note = f"JGHBM {jg.index[-1].date()} 기준"
    else:
        jg = None
        jg_note = "⚠ JGHBM parquet 없음 — 상관 생략 (export_index 먼저 실행)"

    # 위기구간 기대 거래일: JGHBM(한국 달력) 기준 근사 — 해외 거래소와 ±10% 차이는
    # MIN_COVERAGE=60%가 흡수한다
    expected = {}
    for label, (s, e) in CRISES.items():
        if jg is not None:
            expected[label] = len(jg.loc[s:e] if e else jg.loc[s:])
        else:
            expected[label] = 150

    rows = []
    for _, c in registry().iterrows():
        px, used = fetch_series(c["조회티커"])
        if px is None:
            rows.append({"종목명": c["종목명"], "티커": c["코드"],
                         "체인구간": c["체인구간"], "데이터": "조회 실패"})
            print(f"⚠ {c['종목명']}: 전 티커 조회 실패 {c['조회티커']}")
            continue
        yr1 = px.loc[px.index[-1] - pd.DateOffset(years=1):]
        row = {
            "종목명": c["종목명"], "티커": c["코드"], "사용티커": used,
            "통화": c["통화"], "체인구간": c["체인구간"],
            "국내대응": c["국내대응"].split(" ※")[0],
            "데이터시작": str(px.index[0].date()),
            "1년 수익률(%)": round(float(px.iloc[-1] / yr1.iloc[0] - 1) * 100, 1),
            "연변동성(%)": round(float(px.pct_change(fill_method=None).dropna()
                                    .std() * 252 ** 0.5) * 100, 1),
            "주간상관 vs JGHBM": round(weekly_corr(px, jg), 2) if jg is not None
                                else float("nan"),
        }
        for label, (s, e) in CRISES.items():
            row[f"MDD {label[:7]}(%)"] = crisis_mdd(px, s, e, expected[label])
        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"\n[해외 후보 관측 스캔] 현지통화 기준 · {jg_note}")
    print(df.to_string(index=False))
    print("\n읽는 법:")
    print("  · 전부 현지통화 — 원화 관점에서는 환노출이 추가로 얹힌다.")
    print("  · 상관은 주간 수익률(시차 완화). 낮을수록 분산 효과, 높을수록 같은 베팅.")
    print("  · 이 표는 실사가 아니다 — HBM노출도·편입 여부는 문서 실사"
          "(글로벌실사_가이드.md)가 정한다.")
    print("  · 수익률에는 생존 편향이 있다(오늘 살아남은 승자들) — 판단 기준은 낙폭·상관.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "global_scan.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
