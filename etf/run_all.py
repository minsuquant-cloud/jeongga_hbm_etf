# -*- coding: utf-8 -*-
"""
etf/run_all.py — 설계 검증 전체 재현 (이것이 '최종본' 진입점)
=============================================================
러너가 18개로 늘어나면서 "무엇을 돌려야 최종본인가"가 불분명해졌다.
⚠ `run_final.py`는 최종본이 **아니다** — 2026-07-25 12종목 실사확정 시절
러너이고, 지금 돌리면 폐기본 구성표(구성표_실사확정_20260725.csv)를 쓴다.
이름만 final이다. 현행 정본은 13종목 글로벌(구성표_글로벌확정_20260729.csv).

이 스크립트가 하는 일
---------------------
  [0] **EOD 게이트** — parquet 최신일을 FDR과 대조한다. 괴리가 크면 중단.
      CLAUDE.md의 "산출 러너는 장 마감 후에 돌린다"를 코드로 강제한다
      (2026-07-29 장중 실행에서 소스별 가격이 12% 어긋난 사고).
  [1~n] 정본 러너를 순서대로 실행하고 단계별 성공/실패를 표로 낸다.

설계 원칙
  · 각 러너를 **별 프로세스**로 돌린다 — 한 러너의 전역 상태·예외가 다음을
    오염시키지 않고, 실패해도 나머지를 계속 볼 수 있다.
  · 네트워크 의존 단계는 뒤로 몰고 `--skip-network`로 뺄 수 있다.
  · KRX 벤치마크는 **실패를 허용**한다(서비스 장애가 잦고, 실패 시 러너가
    직전 정상본을 보존하도록 이미 만들어져 있다). 나머지는 실패 = 빨간불.

사용:
    .venv/Scripts/python.exe etf/run_all.py                # 전체
    .venv/Scripts/python.exe etf/run_all.py --skip-network # 오프라인만
    .venv/Scripts/python.exe etf/run_all.py --gate-only    # 게이트만 확인
    .venv/Scripts/python.exe etf/run_all.py --force        # 게이트 무시(비권장)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(BASE, ".venv", "Scripts", "python.exe")

# 게이트 기준 — 같은 날짜 라벨에서 소스가 이만큼 어긋나면 EOD가 아니다
GATE_TOL_PCT = 1.0
GATE_PROBES = [("000660", "SK하이닉스"), ("005930", "삼성전자"),
               ("042700", "한미반도체")]

# (라벨, 스크립트, 네트워크 필요, 실패 허용)
STEPS = [
    ("구성·상장요건",      "run_compliance.py",     False, False),
    ("12.5년 최종 산출",   "run_final_long.py",     False, False),
    ("위기 스트레스",      "run_stress_long.py",    False, False),
    ("동일가중 반사실",    "run_counterfactual.py", False, False),
    ("노출도 하한 시나리오", "run_exposure_floor.py", False, False),
    ("재무 건강 경보",     "run_health.py",         False, True),
    ("지수 내보내기",      "export_index.py",       False, False),
    ("추적오차",           "run_tracking.py",       True,  False),
    ("용량",               "run_capacity.py",       True,  False),
    ("CU 설계",            "run_cu.py",             True,  False),
    ("벤치마크(KRX)",      "run_benchmark.py",      True,  True),
    # 마지막 — 위 산출물을 읽어 사람이 볼 HTML 한 장을 만든다.
    # 앞 단계가 일부 실패해도 읽을 수 있는 만큼은 보여주므로 실패 허용.
    ("일일 리포트",        "make_daily_report.py",  False, True),
]

# 여기 없는 러너는 의도적으로 제외한 것이다:
#   run_final.py         — 2026-07-25 12종목 시절. 폐기본 구성표를 쓴다(이름만 final).
#                          산출물 final_capacity/final_cu_grid.csv도 12종목 값이라 삭제했다.
#   run_scenario_min10   — S4 실사 확대 검토용(역사 기록). 결론은 이미 반영됨.
#   run_global_scenario  — 미실사 후보가 남아 있는 동안 결과 = 현행. 실사 진행 시 수동 실행.
#   run_global_scan      — 실사와 무관한 관측 지표. 후보 재평가 때만.
#   run_stress / run_tracking(1년) — 12.5년판이 정본. 1년 비교가 필요할 때만.
#   run_tr_index         — 배당 데이터가 2025-12에서 멈춰 정체 경고만 나온다.
#   run_rebalance_review — 승인 게이트라 정기변경 때 수동 실행(정본 무접촉).
#   export_basket        — 승인 게이트 뒤에서만. 자동 실행 금지.


def eod_gate(force: bool = False) -> tuple[bool, str]:
    """parquet 최신일이 EOD 확정인지 FDR로 대조. (통과 여부, 메시지)."""
    from etf.hist_data import load_composition, load_field
    w = load_composition()
    pq = load_field("Close", w.index.tolist())
    last = pq.index[-1]
    today = pd.Timestamp(dt.date.today())

    import FinanceDataReader as fdr
    gaps, fdr_latest = [], None
    for code, name in GATE_PROBES:
        s = fdr.DataReader(code, str((last - pd.Timedelta(days=10)).date())
                           )["Close"].dropna()
        fdr_latest = max(fdr_latest, s.index[-1]) if fdr_latest is not None \
            else s.index[-1]
        if last not in s.index:
            gaps.append((name, float("nan")))
            continue
        gaps.append((name, abs(float(pq.loc[last, code]) - float(s.loc[last]))
                     / float(s.loc[last]) * 100))
    worst = max((g for _, g in gaps if g == g), default=float("nan"))

    print(f"[0] EOD 게이트 — parquet 최신 {last.date()} · FDR 최신 "
          f"{fdr_latest.date() if fdr_latest is not None else '?'}")
    for name, g in gaps:
        print(f"    {name:<10} 괴리 {g:5.2f}%" if g == g
              else f"    {name:<10} 해당일 FDR 없음")

    if worst != worst:
        return force, "FDR 대조 실패 — 수동 확인 필요"
    if worst > GATE_TOL_PCT:
        return force, (f"괴리 {worst:.2f}% > {GATE_TOL_PCT}% — parquet이 EOD가 "
                       "아니다(장중 스냅샷 의심). 마감 후 파이프라인 갱신 뒤 재실행")
    stale = (today - last).days
    note = f"괴리 {worst:.2f}% 정합"
    if fdr_latest is not None and fdr_latest > last:
        note += (f" · ⚠ 다만 FDR엔 {fdr_latest.date()}가 있는데 parquet은 "
                 f"{last.date()} — 파이프라인이 {stale}일 뒤처졌다. "
                 "산출은 그 날짜 기준으로 일관되지만 최신은 아니다")
    return True, note


def run_step(label: str, script: str, allow_fail: bool) -> dict:
    path = os.path.join(BASE, "etf", script)
    env = dict(os.environ, PYTHONUTF8="1")
    t0 = time.time()
    proc = subprocess.run([PY, path], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, cwd=BASE)
    dur = time.time() - t0
    okay = proc.returncode == 0
    tail = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()][-1:] \
        or [(proc.stderr or "").strip().splitlines()[-1:] or ["(출력 없음)"]][0]
    return {"단계": label, "스크립트": script,
            "결과": "OK" if okay else ("경고" if allow_fail else "실패"),
            "초": round(dur, 1), "마지막 출력": tail[0][:70]}


def main() -> int:
    ap = argparse.ArgumentParser(description="설계 검증 전체 재현")
    ap.add_argument("--skip-network", action="store_true",
                    help="네트워크 필요 단계 제외")
    ap.add_argument("--gate-only", action="store_true", help="EOD 게이트만")
    ap.add_argument("--force", action="store_true",
                    help="게이트 실패에도 진행 (비권장 — 장중 수치가 섞인다)")
    args = ap.parse_args()

    print(f"=== 정가 HBM ETF 설계 검증 전체 재현 ({dt.datetime.now():%Y-%m-%d %H:%M}) ===\n")
    passed, msg = eod_gate(args.force)
    print(f"    → {'통과' if passed else '중단'}: {msg}\n")
    if not passed:
        print("게이트가 막았습니다. 마감 후 D:\\data 파이프라인 갱신을 확인하고 "
              "다시 실행하십시오 (정말 필요하면 --force).")
        return 1
    if args.gate_only:
        return 0

    steps = [s for s in STEPS if not (args.skip_network and s[2])]
    print(f"{len(steps)}단계 실행 (네트워크 단계 "
          f"{'제외' if args.skip_network else '포함'})\n")
    rows = []
    for i, (label, script, _net, allow_fail) in enumerate(steps, 1):
        print(f"[{i}/{len(steps)}] {label} ({script}) … ", end="", flush=True)
        r = run_step(label, script, allow_fail)
        rows.append(r)
        print(f"{r['결과']} {r['초']:.0f}초")

    df = pd.DataFrame(rows)
    print(f"\n=== 요약 ===")
    print(df.to_string(index=False))
    n_fail = int((df["결과"] == "실패").sum())
    n_warn = int((df["결과"] == "경고").sum())
    print(f"\nOK {int((df['결과'] == 'OK').sum())} · 경고 {n_warn} · 실패 {n_fail}"
          f" · 총 {df['초'].sum():.0f}초")
    if n_fail:
        print("⚠ 실패 단계가 있습니다 — 해당 스크립트를 단독 실행해 원문 오류를 볼 것")
    else:
        print("설계 검증 산출물이 전부 갱신됐습니다. 설계서 PDF는 "
              "make_pdf_etf.py로 별도 재생성(하드코딩이라 수동 동기화).")
    rep = os.path.join(BASE, "etf", "output", "daily_report.html")
    if os.path.exists(rep):
        print(f"\n📄 오늘 요약 한 장: {rep}")
        print("   (브라우저로 열면 된다 — 외부 요청 없는 자립형 HTML)")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
