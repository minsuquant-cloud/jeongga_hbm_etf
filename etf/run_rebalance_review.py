# -*- coding: utf-8 -*-
"""
etf/run_rebalance_review.py — 리밸런싱 변경 제안 보고서 (승인 게이트)
====================================================================
사용자 결정(2026-07-29): 리밸런싱은 **보고 → 승인 → 반영**의 3단계다.
엔진이 돌린 결과는 '제안'일 뿐이고, 사용자가 오케이한 것만 ETF 정본에
들어간다 — 실사(판정 주체는 사용자)와 같은 원리를 리밸런싱에도 적용한다.

  1단계 [보고]  이 러너: 최신 판정 CSV로 팀 엔진(버퍼 포함)을 돌려
                현행 정본과의 diff(추가·편출·군 이동·비중 변경·회전율)를
                보고서로 만든다. **정본은 절대 건드리지 않는다.**
  2단계 [승인]  사용자가 보고서를 읽고 오케이.
  3단계 [반영]  --approve <제안CSV> 로 확정 구성표 승격 → 상수 전환 →
                run_all.py 로 산출물 전체 재실행.

엔진 충실도
-----------
선정은 rebalance.select_from_selection(팀 v2)을 쓴다 — **히스테리시스 버퍼**
(기존 종목은 유지 임계 hold_core/hold_sat로 완화 판정)가 작동하므로, 신규
문턱만으로 재선정할 때처럼 경계 종목이 과잉 편출되지 않는다. 사전 스크린
(universe.prescreen)은 버퍼보다 우선한다(하드 탈락).

입력이 정본이다
---------------
판정 CSV(국내: 판정완료_*_실사확정 / 해외: 글로벌후보_실사_*)가 리밸 심사의
입력이다. 재실사·유동시총 갱신은 **이 CSV들을 갱신하는 것**으로 반영된다 —
이 러너는 CSV에 적힌 것만 믿는다(fail-closed).

사용:
    .venv/Scripts/python.exe etf/run_rebalance_review.py                # 보고
    .venv/Scripts/python.exe etf/run_rebalance_review.py --approve \\
        etf/output/rebalance_proposal_20261214.csv                     # 반영
산출: etf/output/rebalance_proposal_<날짜>.csv (+ _diff.csv)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.universe as universe  # noqa: E402
import src.weighting as weighting  # noqa: E402
from src.rebalance import ConfigV2, select_from_selection  # noqa: E402
from etf.global_candidates import (load_global_judged,  # noqa: E402
                                   merge_with_korean, normalize_code)
from etf.run_tracking import load_constituents, source_line  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
OUT_DIR = os.path.join(BASE, "etf", "output")
JUDGED_KR = os.path.join(PROC, "판정완료_20260725_실사확정.csv")


def load_judged_kr(path: str = JUDGED_KR) -> pd.DataFrame:
    d = pd.read_csv(path, encoding="utf-8-sig")
    d["코드"] = d["코드"].map(normalize_code)
    d.attrs["source"] = os.path.basename(path)
    return d


def composition_diff(old: pd.DataFrame, new: pd.DataFrame,
                     hold_note: dict | None = None) -> tuple[pd.DataFrame, float]:
    """현행 vs 제안 구성의 종목별 diff (순수 함수 — 오프라인 테스트 대상).

    반환: (diff 표, 편도 회전율 %). 구분 = 신규/편출/군이동/유지.
    hold_note: {코드: 사유} — 버퍼 유지 등 주의 표시.
    """
    o = old.set_index("코드")
    n = new.set_index("코드")
    codes = sorted(set(o.index) | set(n.index))
    rows = []
    for c in codes:
        w_old = float(o.at[c, "편입비중(%)"]) if c in o.index else 0.0
        w_new = float(n.at[c, "편입비중(%)"]) if c in n.index else 0.0
        if c in n.index and c not in o.index:
            kind = "신규 편입"
        elif c in o.index and c not in n.index:
            kind = "편출"
        elif o.at[c, "군"] != n.at[c, "군"]:
            kind = f"군 이동 {o.at[c, '군']}→{n.at[c, '군']}"
        else:
            kind = "유지"
        name = (n.at[c, "종목명"] if c in n.index else o.at[c, "종목명"])
        grp = (n.at[c, "군"] if c in n.index else o.at[c, "군"])
        rows.append({"코드": c, "종목명": name, "군": grp, "구분": kind,
                     "현행(%)": round(w_old, 2), "제안(%)": round(w_new, 2),
                     "Δ(%p)": round(w_new - w_old, 2),
                     "비고": (hold_note or {}).get(c, "")})
    diff = pd.DataFrame(rows).sort_values(
        ["구분", "제안(%)"], ascending=[True, False]).reset_index(drop=True)
    turnover = 0.5 * float(diff["Δ(%p)"].abs().sum())
    return diff, turnover


def purity(comp: pd.DataFrame, judged: pd.DataFrame) -> float:
    expo = judged.set_index("코드")["HBM노출도"].astype(float)
    w = comp.set_index("코드")["편입비중(%)"] / 100.0
    joined = expo.reindex(w.index)
    if joined.isna().any():
        missing = joined.index[joined.isna()].tolist()
        raise ValueError(f"노출도를 모르는 편입 종목: {missing} — 판정 CSV 확인")
    return float((w * joined).sum() * 100)


def propose(judged: pd.DataFrame, current: pd.DataFrame,
            cfg: ConfigV2 = ConfigV2()) -> dict:
    """판정 CSV + 현행 구성 → 제안 구성 + diff (정본 무접촉)."""
    passed, rejects = universe.prescreen(judged)          # 하드 탈락이 버퍼보다 우선
    prev = set(current["코드"])
    sel = select_from_selection(passed, prev_members=prev, cfg=cfg)
    res = weighting.compute_weights(sel)
    issues = weighting.verify(res)
    if issues:
        raise RuntimeError(f"weighting 자체검증 실패: {issues}")
    prop = res[["종목명", "코드", "군", "편입비중(%)"]].copy()

    # 버퍼로 살아남은 종목 표시 — 신규 문턱으로는 미편입인데 유지 임계로 잔류
    from src.rebalance import selection_hold_group
    hold_note = {}
    for _, r in passed[passed["코드"].isin(prev)].iterrows():
        entry_g = selection_hold_group(r, cfg.entry_core, cfg.entry_sat)
        hold_g = selection_hold_group(r, cfg.hold_core, cfg.hold_sat)
        if entry_g == "미편입" and hold_g != "미편입":
            hold_note[r["코드"]] = (f"⚠버퍼 유지 (신규 문턱 미달·유지 임계 "
                                    f"{cfg.hold_core:.0%}/{cfg.hold_sat:.0%} 통과)")
    for _, r in rejects.iterrows():
        if r["코드"] in prev:
            hold_note[r["코드"]] = f"사전 스크린 탈락: {r['사유']}"

    diff, turnover = composition_diff(current, prop, hold_note)
    return {"proposal": prop, "diff": diff, "turnover_pct": turnover,
            "rejects": rejects,
            "purity_old": purity(current, judged),
            "purity_new": purity(prop, judged)}


def main() -> int:
    ap = argparse.ArgumentParser(description="리밸런싱 변경 제안 보고서")
    ap.add_argument("--judged-kr", default=JUDGED_KR)
    ap.add_argument("--judged-gl", default=None,
                    help="글로벌 실사 CSV (기본: global_candidates.TEMPLATE)")
    ap.add_argument("--buffer", default=None,
                    choices=["none", "narrow", "mid", "wide"],
                    help="버퍼 정책 (기본: ConfigV2 기본값 mid 0.27/0.67)")
    ap.add_argument("--approve", default=None, metavar="제안CSV",
                    help="승인 반영: 제안 CSV를 확정 구성표로 승격")
    args = ap.parse_args()

    # ── 3단계 [반영] — 승인된 제안만 정본 후보로 승격 ──────────────────
    if args.approve:
        src_csv = args.approve
        stamp = dt.date.today().strftime("%Y%m%d")
        dst = os.path.join(PROC, f"구성표_확정_{stamp}.csv")
        if not os.path.exists(src_csv):
            raise FileNotFoundError(f"제안 파일 없음: {src_csv}")
        if os.path.exists(dst):
            raise FileExistsError(f"이미 존재: {dst} — 같은 날 재승격 금지"
                                  "(기존 확정본 보호)")
        shutil.copyfile(src_csv, dst)
        print(f"[승인 반영] {src_csv} → {dst}")
        print("\n남은 절차 (정본 전환 체크리스트 — CLAUDE.md 원칙):")
        print(f"  1. **두 상수를 모두** '{os.path.basename(dst)}'로 갱신 "
              "(코드 변경 = 의도 명시라 수동이다)")
        print("       etf/run_tracking.py  CONSTITUENTS")
        print("       etf/hist_data.py     FINAL")
        print("     → 한쪽만 바꾸면 run_all.py의 [0a] 게이트가 막는다")
        print("  2. etf/run_all.py 로 산출물 전체 재실행 (같은 날 = 날짜 통일 원칙)")
        print("  3. 커밋 — 구 구성표는 역사 기록으로 보존")
        return 0

    # ── 1단계 [보고] — 정본 무접촉 ─────────────────────────────────────
    current = load_constituents()
    judged_kr = load_judged_kr(args.judged_kr)
    if args.judged_gl:
        judged_gl, pending = load_global_judged(args.judged_gl)
    else:
        judged_gl, pending = load_global_judged()
    judged = merge_with_korean(judged_kr, judged_gl) if len(judged_gl) \
        else judged_kr

    cfg = ConfigV2.with_policy(args.buffer) if args.buffer else ConfigV2()
    r = propose(judged, current, cfg)

    print(f"[리밸런싱 제안] 현행: {source_line(current)} · "
          f"판정 입력: {judged_kr.attrs['source']}"
          + (f" + 글로벌 {len(judged_gl)}종" if len(judged_gl) else ""))
    print(f"버퍼: hold_core {cfg.hold_core:.0%} / hold_sat {cfg.hold_sat:.0%} "
          f"(신규 {cfg.entry_core:.0%}/{cfg.entry_sat:.0%})\n")
    if len(pending):
        print(f"[미실사 해외 후보 {len(pending)}종 — 심사 대상에서 제외] "
              + ", ".join(pending["종목명"]))
    if len(r["rejects"]):
        print("[사전 스크린 탈락]")
        print(r["rejects"].to_string(index=False))
    print()

    changes = r["diff"][r["diff"]["구분"] != "유지"]
    holds = r["diff"][r["diff"]["비고"].str.contains("버퍼", na=False)]
    print(r["diff"].to_string(index=False))
    print(f"\n요약: 변경 {len(changes)}건 (신규 "
          f"{(r['diff']['구분'] == '신규 편입').sum()} · 편출 "
          f"{(r['diff']['구분'] == '편출').sum()} · 군이동 "
          f"{r['diff']['구분'].str.startswith('군 이동').sum()}) · "
          f"버퍼 유지 {len(holds)}건")
    print(f"편도 회전율 {r['turnover_pct']:.2f}% · "
          f"순도 {r['purity_old']:.2f}% → {r['purity_new']:.2f}%")

    stamp = dt.date.today().strftime("%Y%m%d")
    os.makedirs(OUT_DIR, exist_ok=True)
    p_prop = os.path.join(OUT_DIR, f"rebalance_proposal_{stamp}.csv")
    p_diff = os.path.join(OUT_DIR, f"rebalance_proposal_{stamp}_diff.csv")
    r["proposal"].to_csv(p_prop, index=False, encoding="utf-8-sig")
    r["diff"].to_csv(p_diff, index=False, encoding="utf-8-sig")
    print(f"\n저장: {p_prop}\n      {p_diff}")
    print("\n⚠ 이 파일은 **제안**이다 — 승인 전까지 정본이 아니다.")
    print("  승인하려면:  .venv/Scripts/python.exe etf/run_rebalance_review.py "
          f"--approve {p_prop}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
