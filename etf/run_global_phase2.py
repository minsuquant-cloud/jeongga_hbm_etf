# -*- coding: utf-8 -*-
"""
etf/run_global_phase2.py — 글로벌판(13종목·MU 포함) 용량·CU·환노출
==================================================================
1차·2차 실사로 구성은 확정됐다(앵커 3사 + 국내 비앵커 10). 이 러너는 그
구성이 **운용 가능한가**를 잰다 — phase 2로 이월했던 세 가지:

  ① 용량   : MU ADV(KRW 환산)를 붙여 병목·허용 AUM 재산출
  ② CU/PDF : MU 포함 정수 주 격자에서 총괄리·강건성 (min_cu_notional 재사용)
  ③ 환노출 : MU를 KRW 환산으로 넣은 지수 vs 환율 고정(헤지 근사) 지수 —
             위기 4구간 MDD로 환노출의 기여를 분해

정직 고지
---------
- 비중은 오늘 확정 구성의 소급 적용 — 기존 12.5년 분석과 같은 한계(수익률은
  성과 주장에 쓰지 않는다. MDD·상대 비교만 본다).
- MU ADV는 FDR 종가×거래량 근사(정규장 배율 미상 — 미국은 단일 통합 테이프라
  국내 같은 시간외 부풀림 이슈는 작다고 가정하고 배율 1.0).
- 환율은 USD/KRW 일별 종가. MU의 KRW 시세 = USD 종가 × 당일 환율 —
  한국 장 마감(15:30)과 미국 장 마감의 시차는 주간 단위 분석에서 묻힌다고
  가정한다(run_global_scan의 주간상관과 같은 논리).

    .venv/Scripts/python.exe etf/run_global_phase2.py

산출: etf/output/global_capacity.csv · global_cu.csv · global_fx_index.csv
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.capacity import EOK, max_aum  # noqa: E402
from etf.cu_design import min_cu_notional, build_pdf, cu_robustness  # noqa: E402
from etf.hist_data import (conservative_adv, prices_offline,  # noqa: E402
                           simulate_reset_index)
from etf.run_stress_long import CRISES  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")
COMPOSITION = os.path.join(OUT_DIR, "global_scenario_구성.csv")

PARTICIPATION, MAX_DAYS = 0.20, 5.0     # 기존 용량 가정과 동일
CU_CANDIDATES = (7, 10, 15, 20, 30, 50)


def load_global_composition() -> tuple[pd.Series, dict]:
    """global_scenario_구성.csv → ({코드: 비중(합 1)}, {코드: 종목명})."""
    c = pd.read_csv(COMPOSITION, encoding="utf-8-sig", dtype={"코드": str})
    w = pd.Series(c["편입비중(%)"].values / 100.0, index=c["코드"].values)
    if abs(w.sum() - 1.0) > 1e-4:
        raise ValueError(f"글로벌 구성 비중 합 {w.sum():.4f} ≠ 1 — 구성표 확인")
    return w / w.sum(), dict(zip(c["코드"], c["종목명"]))


def mu_krw_series() -> tuple[pd.Series, pd.Series, float]:
    """MU 종가(USD)·USD/KRW 일별 시계열 (2014~). 반환: (usd, fx, 최신환율)"""
    import FinanceDataReader as fdr
    usd = fdr.DataReader("MU", "2014-01-01")["Close"].dropna()
    fx = fdr.DataReader("USD/KRW", "2014-01-01")["Close"].dropna()
    return usd, fx, float(fx.iloc[-1])


def main() -> int:
    (w, names) = load_global_composition()
    kr_codes = [c for c in w.index if c.isdigit()]
    if set(w.index) - set(kr_codes) != {"MU"}:
        raise ValueError(f"예상 밖 해외 티커: {set(w.index) - set(kr_codes) - {'MU'}}")

    usd, fx, rate = mu_krw_series()
    mu_px_krw = float(usd.iloc[-1]) * rate

    # ── ① 용량 — 정규장 기준(국내) + MU ADV(KRW) ─────────────────────
    adv = conservative_adv(kr_codes)                       # 정규장 추정(원)
    vol = __import__("FinanceDataReader").DataReader("MU", "2026-01-01")
    mu_adv = float((vol["Close"] * vol["Volume"]).dropna().tail(60).mean()) * rate
    adv.loc["MU"] = mu_adv
    summary, per_stock = max_aum(w, adv, PARTICIPATION, MAX_DAYS)

    cap_tbl = pd.DataFrame({
        "종목명": [names[c] for c in w.index],
        "비중(%)": (w * 100).round(2),
        "ADV(억)": (adv.reindex(w.index) / EOK).round(0),
        "허용 AUM(억)": (per_stock.reindex(w.index) / EOK).round(0),
    }).sort_values("허용 AUM(억)")
    print("[① 용량 — 글로벌판 13종목, 정규장 기준 + MU]")
    print(cap_tbl.to_string(index=False))
    print(f"  → 용량 {summary['용량(억)']:,.0f}억 · 병목 "
          f"{names[summary['병목 종목']]}({summary['병목 종목']})")
    print("  ⚠ 비앵커 비중이 국내판과 동일하므로 국내 꼬마주 병목은 그대로다 —"
          " 글로벌 확장은 용량을 늘리지 않는다(늘리는 건 앵커 유동성뿐).")

    # ── ② CU/PDF — MU 포함 정수 주 격자 ──────────────────────────────
    px = prices_offline(kr_codes).ffill().iloc[-1]         # 국내 최신 수정종가
    px.loc["MU"] = mu_px_krw
    grid = min_cu_notional(w, px.reindex(w.index), candidates_eok=CU_CANDIDATES)
    print("\n[② CU 격자 — MU 포함]")
    print(grid.to_string(index=False))
    ok = grid[grid["강건"]]
    pick = int(ok.iloc[0]["CU금액(억)"]) if len(ok) else None
    if pick:
        r = build_pdf(w, px.reindex(w.index), pick * EOK)
        rb = cu_robustness(w, px.reindex(w.index), pick * EOK)
        mu_row = r["pdf"].loc["MU"]
        print(f"  → 권장 CU {pick}억: 총괴리 {r['total_dev_bp']:.1f}bp · "
              f"MU {int(mu_row['주식수'])}주({mu_px_krw:,.0f}원) · "
              f"p95 {rb['p95 총괴리(bp)']:.1f}bp")
    else:
        print("  ⚠ 후보 중 강건 통과 CU 없음 — 후보 확대 필요")

    # ── ③ 환노출 — KRW 환산 vs 환율 고정(헤지 근사) ──────────────────
    close_kr = prices_offline(kr_codes)
    cal = close_kr.index                                    # 한국 거래일 달력
    # T-1 시프트: 미국 T 종가는 한국 T 마감 뒤에 나온다 — 룩어헤드 제거
    # (hist_data.align_foreign과 같은 규약, 2026-07-29 리뷰 반영)
    mu_usd_on_cal = usd.reindex(cal).ffill().shift(1)
    fx_on_cal = fx.reindex(cal).ffill().shift(1)
    panel_fx = close_kr.copy()
    panel_fx["MU"] = mu_usd_on_cal * fx_on_cal              # 환노출 포함
    panel_hg = close_kr.copy()
    panel_hg["MU"] = mu_usd_on_cal * float(fx_on_cal.dropna().iloc[0])  # 환율 고정(헤지 근사)

    bt_fx = simulate_reset_index(panel_fx.dropna(how="all"), w)
    bt_hg = simulate_reset_index(panel_hg.dropna(how="all"), w)

    rows = []
    for label, (s, e) in {"전체 (2014~)": (None, None), **CRISES}.items():
        sl = slice(s, e)
        seg_fx, seg_hg = bt_fx["level"].loc[sl], bt_hg["level"].loc[sl]
        if len(seg_fx) < 20:
            rows.append({"구간": label, "MDD 환노출(%)": "표본부족",
                         "MDD 헤지근사(%)": "표본부족", "환노출 기여(%p)": "—"})
            continue
        mdd = lambda x: float((x / x.cummax() - 1).min()) * 100
        m_fx, m_hg = mdd(seg_fx), mdd(seg_hg)
        rows.append({"구간": label, "MDD 환노출(%)": round(m_fx, 1),
                     "MDD 헤지근사(%)": round(m_hg, 1),
                     "환노출 기여(%p)": round(m_fx - m_hg, 1)})
    fx_tbl = pd.DataFrame(rows)
    print("\n[③ 환노출 — MU KRW 환산 vs 환율 고정(헤지 근사), 위기 MDD]")
    print(fx_tbl.to_string(index=False))
    print("  읽는 법: 기여가 음수면 환노출이 낙폭을 키웠고, 양수면 원화 약세가")
    print("  완충했다는 뜻. 수익률이 아니라 낙폭만 본다(소급 비중 한계 동일).")

    os.makedirs(OUT_DIR, exist_ok=True)
    cap_tbl.to_csv(os.path.join(OUT_DIR, "global_capacity.csv"),
                   encoding="utf-8-sig")
    grid.to_csv(os.path.join(OUT_DIR, "global_cu.csv"),
                index=False, encoding="utf-8-sig")
    fx_tbl.to_csv(os.path.join(OUT_DIR, "global_fx_index.csv"),
                  index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT_DIR}\\global_capacity.csv · global_cu.csv · global_fx_index.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
