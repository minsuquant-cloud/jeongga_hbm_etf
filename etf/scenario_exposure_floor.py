# -*- coding: utf-8 -*-
"""
etf/scenario_exposure_floor.py — 위성군 노출도 하한 신설 시나리오 (방법론 개정 검토)
====================================================================================
현행 위성 요건은 **메모리향 ≥70% + 공정확인 + 위원회확인**뿐이고 HBM 노출도
하한이 없다. 그래서 노출도 0.00(티이엠씨)·0.03(주성엔지니어링, 비중 13.42%로
전체 2위)이 규칙상 적법하게 편입된다 — "HBM ETF인데 HBM 0% 종목"이라는,
심사에서 나올 질문이다.

이 모듈은 **판정하지 않는다.** 위성군에 노출도 하한을 넣으면 구성·순도·상장
요건·용량이 어떻게 움직이는지 나란히 놓을 뿐이다. 채택 여부는 사용자 결정이다
(S4 실사 확대 때와 같은 구조).

동결 엔진을 건드리지 않는 방법
------------------------------
`selection.classify_row`의 위성 분기에 하한을 넣으면 팀 엔진 수정이다. 대신
**선분류 → 위성 탈락자 제거 → 엔진 재실행**으로 같은 결과를 얻는다:
  1) selection.classify로 각 종목의 군을 먼저 얻고
  2) 군=='위성' AND 노출도 < 하한 인 행만 후보에서 제외한 뒤
  3) 그 축소된 후보로 select_constituents → compute_weights를 정상 실행
앵커(규칙 0)·핵심(규칙 A)은 노출도 하한과 무관하므로 영향받지 않는다 —
핵심 문턱 30%가 이미 어떤 하한보다 높기 때문이다.

읽는 법 (중요)
--------------
순도가 오르는 것은 당연하다 — 저노출 종목을 빼면 분자가 남는다. 봐야 할 것은
**대가**다: ① R1(≥10종목) 여유가 얼마나 줄어드나 ② 빠진 비중이 어디로 재배분돼
집중도(R2·R3)가 어떻게 되나 ③ 용량 병목이 바뀌나 ④ 회전율(갈아엎는 양).
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.selection as selection  # noqa: E402
import src.universe as universe  # noqa: E402
import src.weighting as weighting  # noqa: E402
from etf.compliance import check_diversification  # noqa: E402

SAT = "위성"


def apply_exposure_floor(judged: pd.DataFrame, floor: float) -> tuple:
    """위성으로 분류될 종목 중 노출도 < floor 인 행을 후보에서 제외.

    반환: (축소된 후보 DataFrame, 제외된 종목 DataFrame[종목명·코드·노출도])
    floor=0이면 현행과 동일(제외 없음).
    """
    if not 0 <= floor <= 1:
        raise ValueError(f"floor는 0~1 (노출도와 같은 척도) — 받은 값: {floor}")
    d = judged.copy()
    if floor <= 0:
        return d, d.iloc[0:0][["종목명", "코드"]].assign(HBM노출도=[])
    grp = selection.classify(d)["군"]
    expo = pd.to_numeric(d["HBM노출도"], errors="coerce").fillna(0.0)
    drop = (grp == SAT) & (expo < floor - 1e-12)
    return d[~drop].copy(), d.loc[drop, ["종목명", "코드", "HBM노출도"]].copy()


def run_floor(judged: pd.DataFrame, floor: float,
              grant_codes: list[str] | None = None) -> dict:
    """하한 1개 시나리오 → 구성·순도·분산요건 요약 (사전 스크린 포함)."""
    d = judged.copy()
    if grant_codes:
        m = d["코드"].isin(list(grant_codes))
        d.loc[m, "HBM공정확인"] = True
        d.loc[m, "위원회확인"] = True
    passed, _ = universe.prescreen(d)              # 하드 탈락이 먼저
    cand, dropped = apply_exposure_floor(passed, floor)

    sel = selection.select_constituents(cand)
    res = weighting.compute_weights(sel)
    issues = weighting.verify(res)
    if issues:
        raise RuntimeError(f"weighting 자체검증 실패: {issues}")

    w = res.set_index("코드")["편입비중"]
    expo = res.set_index("코드")["HBM노출도"].astype(float)
    purity = float((w * expo).sum()) * 100
    comp = check_diversification(w)
    verdicts = comp.set_index(comp["항목"].str[:4])["판정"]
    grp_sum = res.groupby("군")["편입비중(%)"].sum()

    return {
        "노출도 하한": f"{floor:.0%}" if floor > 0 else "없음(현행)",
        "종목수": len(res),
        "앵커/핵심/위성": "/".join(
            str(int((res["군"] == g).sum())) for g in ("앵커", "핵심", "위성")),
        "위성 합(%)": round(float(grp_sum.get("위성", 0.0)), 2),
        "최대비중(%)": round(float(w.max()) * 100, 2),
        "HBM순도(%)": round(purity, 2),
        "R1 종목수≥10": verdicts["[R1]"],
        "R2 ≤30%": verdicts["[R2]"],
        "R3 ≤20%": verdicts["[R3]"],
        "_구성": res[["종목명", "코드", "군", "편입비중(%)", "HBM노출도"]],
        "_탈락": dropped,
    }


def compare(judged: pd.DataFrame, floors: tuple = (0.0, 0.03, 0.05, 0.10),
            grant_codes: list[str] | None = None) -> tuple:
    """하한별 비교표 + 시나리오별 상세."""
    rows, details = [], {}
    for f in floors:
        r = run_floor(judged, f, grant_codes)
        details[f] = r
        rows.append({k: v for k, v in r.items() if not k.startswith("_")})
    return pd.DataFrame(rows), details
