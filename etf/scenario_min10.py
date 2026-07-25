# -*- coding: utf-8 -*-
"""
etf/scenario_min10.py — 종목수 10 충족 시나리오 시뮬레이션 (5단계 FAIL 해소)
============================================================================
분산요건 점검(compliance)의 핵심 FAIL — "구성 7종목 < 상장규정 10종목" —
을 푸는 방법론 개정안들을 팀 엔진(selection→weighting) 그대로 돌려
종목수·순도·분산요건의 교환 관계를 정량화한다.

사전 진단 (판정완료 33종목 기준)
--------------------------------
- 위성 요건(메모리향 ≥70% + HBM공정확인 + 위원회확인)에서 **공정·위원회
  확인 통과 기업이 현 구성 7종목뿐** — 임계값만 완화해도 위성은 늘지 않는다.
  (걸림돌이 숫자가 아니라 '실사 문서'라는 뜻)
- 따라서 경로는 둘: ① 핵심 노출도 문턱 인하(규칙 완화 = 순도 희석),
  ② 공정확인 실사 확대(규칙 유지 = 실사 비용·시간, 순도 희석은 위성
  상한 18%가 자연 통제).

시뮬 정직성
-----------
- 실사 확대(assume_process_check)는 "메모리향 상위 기업이 실사를 통과할
  것"이라는 **가정**이다 — 실제 통과 여부는 문서 확보 전까지 알 수 없다.
  결과 표에 가정임을 명기한다.
- 판정완료 33종목 밖의 종목은 다루지 않는다(판정 데이터 없음 = 편입 불가).
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.selection as selection  # noqa: E402
import src.weighting as weighting  # noqa: E402
from etf.compliance import check_diversification  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JUDGED = os.path.join(BASE, "data", "processed", "판정완료_20260723.csv")


def load_judged() -> pd.DataFrame:
    d = pd.read_csv(JUDGED, encoding="utf-8-sig")
    d["코드"] = d["코드"].astype(str).str.zfill(6)
    return d


@contextmanager
def thresholds(core_th: float, sat_mem_th: float):
    """selection 모듈 상수를 임시 변경 (반드시 원복 — 누수 금지)."""
    orig = (selection.CORE_TH, selection.SAT_MEM_TH)
    selection.CORE_TH, selection.SAT_MEM_TH = core_th, sat_mem_th
    try:
        yield
    finally:
        selection.CORE_TH, selection.SAT_MEM_TH = orig


def run_scenario(judged: pd.DataFrame,
                 core_th: float = 0.30,
                 sat_mem_th: float = 0.70,
                 assume_process_check: bool = False) -> dict:
    """시나리오 1회 실행 → 구성·순도·분산요건 요약.

    assume_process_check : True면 '메모리향 ≥ sat_mem_th 기업은 공정·위원회
    확인을 통과한다'고 가정(실사 확대 시나리오). 가정임을 결과에 표기.
    """
    d = judged.copy()
    if assume_process_check:
        grant = d["메모리향비중"] >= sat_mem_th
        d.loc[grant, "HBM공정확인"] = True
        d.loc[grant, "위원회확인"] = True

    with thresholds(core_th, sat_mem_th):
        sel = selection.select_constituents(d)
        res = weighting.compute_weights(sel)
        issues = weighting.verify(res)
    if issues:
        raise RuntimeError(f"weighting 자체검증 실패: {issues}")

    w = res.set_index("코드")["편입비중"]
    expo = res.set_index("코드")["HBM노출도"].astype(float)
    purity = float((w * expo).sum())
    comp = check_diversification(w)
    verdicts = comp.set_index(comp["항목"].str[:4])["판정"]

    return {
        "핵심문턱": f"{core_th:.0%}",
        "위성문턱": f"{sat_mem_th:.0%}",
        "실사확대(가정)": "예" if assume_process_check else "-",
        "종목수": len(res),
        "앵커/핵심/위성": "/".join(str(int((res["군"] == g).sum()))
                              for g in ("앵커", "핵심", "위성")),
        "최대비중(%)": round(float(w.max()) * 100, 2),
        "HBM순도(%)": round(purity * 100, 2),
        "R1 종목수≥10": verdicts["[R1]"],
        "R2 ≤30%": verdicts["[R2]"],
        "R3 ≤20%": verdicts["[R3]"],
        "_구성": res[["종목명", "군", "편입비중(%)"]],
    }


SCENARIOS = [
    # (라벨, core_th, sat_mem_th, 실사확대)
    ("S0 현행", 0.30, 0.70, False),
    ("S1 핵심 15%", 0.15, 0.70, False),
    ("S2 핵심 10%", 0.10, 0.70, False),
    ("S3 핵심 5%", 0.05, 0.70, False),
    ("S4 실사 확대(문턱 유지)", 0.30, 0.70, True),
    ("S5 실사 확대+위성 60%", 0.30, 0.60, True),
]


def run_all(judged: pd.DataFrame | None = None) -> pd.DataFrame:
    judged = judged if judged is not None else load_judged()
    rows = []
    for label, core, sat, proc in SCENARIOS:
        r = run_scenario(judged, core, sat, proc)
        r.pop("_구성")
        rows.append({"시나리오": label, **r})
    return pd.DataFrame(rows)
