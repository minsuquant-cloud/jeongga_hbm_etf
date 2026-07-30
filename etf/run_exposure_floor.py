# -*- coding: utf-8 -*-
"""
etf/run_exposure_floor.py — 위성 노출도 하한 시나리오 비교 (의사결정 자료)

    .venv/Scripts/python.exe etf/run_exposure_floor.py
산출: etf/output/exposure_floor.csv (+ _구성_*.csv)

용량까지 함께 본다 — 저노출 위성이 빠지면 비중이 재배분되고, 그러면
용량 병목(현재 넥스틴)이 바뀔 수 있다. 순도만 보고 결정하면 놓치는 대가다.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.capacity import EOK, fetch_adv, max_aum  # noqa: E402
from etf.global_candidates import (load_global_judged,  # noqa: E402
                                   merge_with_korean, normalize_code)
from etf.run_final import GRANTED  # noqa: E402
from etf.run_rebalance_review import composition_diff, load_judged_kr  # noqa: E402
from etf.run_tracking import load_constituents, source_line  # noqa: E402
from etf.scenario_exposure_floor import compare  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "etf", "output")
FLOORS = (0.0, 0.03, 0.05, 0.10)


def main() -> int:
    current = load_constituents()
    judged_kr = load_judged_kr()
    judged_gl, _ = load_global_judged()
    judged = merge_with_korean(judged_kr, judged_gl) if len(judged_gl) \
        else judged_kr

    tbl, details = compare(judged, FLOORS, grant_codes=list(GRANTED))
    print(f"[위성 노출도 하한 시나리오] 현행: {source_line(current)}")
    print("현행 위성 요건 = 메모리향 ≥70% + 공정확인 + 위원회확인 (노출도 하한 없음)\n")
    print(tbl.to_string(index=False))

    # 용량: 저노출 위성 편출 → 비중 재배분 → 병목이 바뀌나
    print("\n[용량 영향] 참여율 20%·청산 5일, 정규장 기준 아님(실측 ADV)")
    adv = fetch_adv(current["코드"].tolist())
    names = current.set_index("코드")["종목명"]
    cap_rows = []
    for f in FLOORS:
        w = details[f]["_구성"].set_index("코드")["편입비중(%)"] / 100.0
        w = w / w.sum()
        sub = adv.reindex(w.index)
        if sub.isna().any():                    # 새 종목이 들어올 일은 없지만 방어
            cap_rows.append({"노출도 하한": details[f]["노출도 하한"],
                             "용량(억)": float("nan"), "병목": "ADV 미상"})
            continue
        s, _per = max_aum(w, sub)
        cap_rows.append({"노출도 하한": details[f]["노출도 하한"],
                         "용량(억)": round(s["용량(억)"]),
                         "병목": names.get(s["병목 종목"], s["병목 종목"])})
    print(pd.DataFrame(cap_rows).to_string(index=False))

    # 현행 대비 변경량 — 갈아엎는 양(회전율)이 곧 비용이다
    print("\n[현행 대비 변경]")
    for f in FLOORS:
        if f == 0.0:
            continue
        d = details[f]
        diff, tno = composition_diff(current, d["_구성"])
        out = ", ".join(d["_탈락"]["종목명"]) or "없음"
        print(f"  하한 {d['노출도 하한']:>4}: 편출 {len(d['_탈락'])}종목 ({out}) · "
              f"편도 회전율 {tno:.2f}% · 순도 {d['HBM순도(%)']:.2f}% · "
              f"R1 {d['R1 종목수≥10']}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "exposure_floor.csv")
    with open(out, "w", encoding="utf-8-sig") as fh:
        fh.write("# 노출도 하한 시나리오 비교\n")
        tbl.to_csv(fh, index=False)
        fh.write("\n# 용량 영향\n")
        pd.DataFrame(cap_rows).to_csv(fh, index=False)
    for f in FLOORS:
        tag = details[f]["노출도 하한"].replace("%", "pct").replace("없음(현행)", "current")
        details[f]["_구성"].to_csv(
            os.path.join(OUT_DIR, f"exposure_floor_구성_{tag}.csv"),
            index=False, encoding="utf-8-sig")
    print(f"\n저장: {out} (+ 시나리오별 구성)")
    print("\n※ 이 표는 판정이 아니다 — 방법론 개정 여부는 사용자 결정이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
