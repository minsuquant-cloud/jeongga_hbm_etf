# -*- coding: utf-8 -*-
"""etf/global_candidates.py 검증 — 오프라인(합성 실사), 네트워크 불필요.

경로 B(글로벌 확장)의 가드들:
  · zfill 사고: 'MU'.zfill(6)='0000MU' — 티커 정규화가 숫자에만 zfill
  · 테마 가드: 등록부에 없는 티커는 실사 CSV에 있어도 거부
  · 단위 사고: 노출도 % 표기(35 vs 0.35)·유동시총>시가총액 즉시 예외
  · fail-closed: 빈 필드 후보는 제외 + 사유 보고, 전원 미실사면 국내판 동일
  · 엔진 정합: 판정 완료 해외 행이 규칙 그대로 앵커/핵심에 편입되고
    비중 상한·R2가 유지된다 (문턱 무수정 검증)
"""
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.global_candidates import (CANDIDATES, JUDGE_COLS,  # noqa: E402
                                   load_global_judged, merge_with_korean,
                                   normalize_code, registry, write_template)

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


TMP = tempfile.mkdtemp()


def tpl_path(name):
    return os.path.join(TMP, name)


# ── 1) 티커 정규화 — zfill은 숫자에만 ─────────────────────────────────
check("국내 코드 zfill", normalize_code("5930") == "005930")
check("해외 티커 zfill 금지", normalize_code("MU") == "MU",
      normalize_code("MU"))
check("소문자·접미사 정규화", normalize_code("besi.as") == "BESI.AS")
check("공백 정리", normalize_code(" 0522.HK ") == "0522.HK")

# ── 2) 등록부 무결성 ──────────────────────────────────────────────────
reg = registry()
check("등록부 8종목", len(reg) == 8, len(reg))
check("티커 유일", reg["코드"].is_unique)
check("전원 체인구간·근거문서 보유",
      bool((reg["체인구간"].str.len() > 0).all()
           and (reg["근거문서"].str.len() > 0).all()))
kr = pd.read_csv("data/processed/판정완료_20260725_실사확정.csv",
                 encoding="utf-8-sig")
kr["코드"] = kr["코드"].astype(str).str.zfill(6)
check("국내 33종목과 코드 충돌 없음",
      not (set(reg["코드"]) & set(kr["코드"])))

# ── 3) 템플릿: 생성·덮어쓰기 거부 ─────────────────────────────────────
p = tpl_path("t1.csv")
write_template(p)
t = pd.read_csv(p, encoding="utf-8-sig")
check("템플릿 = 등록부 전 종목", len(t) == len(reg))
check("판정 컬럼 전부 존재", all(c in t.columns for c in JUDGE_COLS),
      [c for c in JUDGE_COLS if c not in t.columns])
try:
    write_template(p)
    check("기존 실사 덮어쓰기 거부", False)
except FileExistsError:
    check("기존 실사 덮어쓰기 거부", True)

# ── 4) fail-closed: 빈 템플릿 → 전원 미실사 ───────────────────────────
done, pend = load_global_judged(p)
check("미실사 전원 제외", len(done) == 0 and len(pend) == len(reg),
      f"done={len(done)} pend={len(pend)}")
check("빈 필드 사유 보고", "시가총액" in str(pend["빈 필드"].iloc[0]))


def filled_row(base, **kw):
    """판정 완료 행 하나 (테스트용 합성값 — 실사 아님)."""
    r = {"시가총액": 2_000_000.0, "FF": 0.9, "유동시총": 1_700_000.0,
         "거래대금": 5_000.0, "자본잠식": False, "HBM양산": False,
         "HBM노출도": 0.2, "메모리향비중": 0.9, "HBM공정확인": True,
         "위원회확인": True, "감사의견": "적정", "관리종목": False,
         "환산기준일": "2026-07-29"}
    r.update(base)
    r.update(kw)
    return r


def make_judged(path, rows):
    # astype(object): 빈 템플릿 컬럼은 float64로 읽혀서 문자열 대입이
    # FutureWarning(향후 에러)이 된다 — 명시 캐스팅으로 차단
    t2 = pd.read_csv(p, encoding="utf-8-sig").astype(object)
    for code, kw in rows.items():
        for k, v in kw.items():
            t2.loc[t2["코드"] == code, k] = v
    t2.to_csv(path, index=False, encoding="utf-8-sig")
    return path


# ── 5) 단위·범위 사고 즉시 예외 ───────────────────────────────────────
mu_ok = filled_row({"유형": "메모리제조", "HBM양산": True, "HBM노출도": 0.25,
                    "메모리향비중": 0.98})
pct = dict(mu_ok, HBM노출도=25)               # % 표기 사고
try:
    load_global_judged(make_judged(tpl_path("t2.csv"), {"MU": pct}))
    check("노출도 % 표기 예외", False)
except ValueError as e:
    check("노출도 % 표기 예외", "0~1" in str(e) or "%" in str(e), str(e)[:60])
inv = dict(mu_ok, 유동시총=3_000_000.0)       # 유동시총 > 시가총액
try:
    load_global_judged(make_judged(tpl_path("t3.csv"), {"MU": inv}))
    check("유동시총>시총 예외", False)
except ValueError:
    check("유동시총>시총 예외", True)

# ── 6) 테마 가드: 등록부 밖 티커 거부 ─────────────────────────────────
t4 = pd.read_csv(p, encoding="utf-8-sig")
t4.loc[len(t4)] = t4.iloc[0]
t4.loc[len(t4) - 1, "코드"] = "NVDA"
t4.loc[len(t4) - 1, "종목명"] = "NVIDIA"
p4 = tpl_path("t4.csv")
t4.to_csv(p4, index=False, encoding="utf-8-sig")
try:
    load_global_judged(p4)
    check("테마 가드(등록부 밖 거부)", False)
except ValueError as e:
    check("테마 가드(등록부 밖 거부)", "NVDA" in str(e), str(e)[:60])

# ── 7) 엔진 정합: 판정 완료 행이 규칙 그대로 흘러간다 ─────────────────
from etf.run_final import GRANTED  # noqa: E402
from etf.scenario_min10 import load_judged, run_scenario  # noqa: E402

judged_kr = load_judged()
base = run_scenario(judged_kr, grant_codes=list(GRANTED))

# MU(합성): 메모리제조×HBM양산 → 앵커 / CAMT(합성): 노출도 0.35 → 핵심
p5 = make_judged(tpl_path("t5.csv"), {
    "MU": filled_row({"유형": "메모리제조", "HBM양산": True, "HBM노출도": 0.25,
                      "메모리향비중": 0.98, "시가총액": 1_800_000.0,
                      "유동시총": 1_700_000.0}),
    "CAMT": filled_row({"유형": "장비", "HBM노출도": 0.35,
                        "메모리향비중": 0.60, "시가총액": 60_000.0,
                        "유동시총": 50_000.0}),
})
done5, pend5 = load_global_judged(p5)
check("판정 완료 2건 인식", len(done5) == 2 and len(pend5) == 6,
      f"done={len(done5)} pend={len(pend5)}")
merged = merge_with_korean(judged_kr, done5)
check("병합 행수 = 33 + 2", len(merged) == 35, len(merged))

r = run_scenario(merged, grant_codes=list(GRANTED))
comp = r["_구성"]
mu = comp[comp["코드"] == "MU"]
camt = comp[comp["코드"] == "CAMT"]
check("MU → 앵커 (규칙 0: 메모리제조×양산)",
      len(mu) == 1 and mu["군"].iloc[0] == "앵커",
      comp[["종목명", "군"]].to_dict("records")[:4])
check("CAMT → 핵심 (규칙 A: 노출도 0.35≥0.30)",
      len(camt) == 1 and camt["군"].iloc[0] == "핵심")
check("종목수 = 12 + 2", r["종목수"] == 14, r["종목수"])
check("R1·R2 PASS 유지", r["R1 종목수≥10"] == "PASS" and r["R2 ≤30%"] == "PASS")
check("앵커 합 40% 유지 (3사 재배분)",
      abs(comp[comp["군"] == "앵커"]["편입비중(%)"].sum() - 40.0) < 0.01,
      comp[comp["군"] == "앵커"]["편입비중(%)"].sum())
check("최대비중 감소 또는 유지 (분산 개선 방향)",
      r["최대비중(%)"] <= base["최대비중(%)"] + 1e-9,
      f"{r['최대비중(%)']} vs {base['최대비중(%)']}")

# 미실사 6종은 편입되지 않았다 (fail-closed 관통)
check("미실사 후보 미편입",
      not set(pend5["코드"]) & set(comp["코드"]))

# ── 8) 병합 충돌 방어 ─────────────────────────────────────────────────
dup = done5.copy()
dup.loc[dup.index[0], "코드"] = "005930"      # 삼성전자와 충돌
try:
    merge_with_korean(judged_kr, dup)
    check("코드 충돌 예외", False)
except ValueError:
    check("코드 충돌 예외", True)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
