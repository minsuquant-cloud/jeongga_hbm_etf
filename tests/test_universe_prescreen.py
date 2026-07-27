# -*- coding: utf-8 -*-
"""src/universe.py 사전 스크린 검증 — 오프라인(합성 픽스처).

배경: 이 스크린은 methodology.md 1장이 약속하고 판정 CSV가 열까지 갖췄는데
집행 코드가 없어서, 관리종목·자본잠식·의견거절 종목이 그대로 18% 비중으로
편입되던 구멍이다. 아래 회귀 테스트가 그 구멍을 다시 열지 못하게 한다.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.universe import (MIN_MCAP_EOK, MIN_TURNOVER_EOK,  # noqa: E402
                          prescreen, prescreen_summary)

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


def row(name, code, **kw):
    base = {"종목명": name, "코드": code, "관리종목": False, "자본잠식": False,
            "감사의견": "적정", "FF": 0.50, "시가총액": 5000.0, "거래대금": 100.0}
    base.update(kw)
    return base


# ── 1) 깨끗한 데이터는 한 종목도 떨어지지 않는다 ──────────────────────
clean = pd.DataFrame([row("정상A", "000001"), row("정상B", "000002")])
passed, rej = prescreen(clean)
check("정상 데이터 탈락 0", len(passed) == 2 and len(rej) == 0,
      f"passed={len(passed)} rej={len(rej)}")
check("요약 문구 = 탈락 0", "탈락 0종목" in prescreen_summary(rej, []))

# ── 2) 규칙별 단독 탈락 (경계값 포함) ─────────────────────────────────
cases = [
    ("관리종목", dict(관리종목=True), "[시장조치]"),
    ("자본잠식", dict(자본잠식=True), "[재무] 자본잠식"),
    ("의견거절", dict(감사의견="의견거절"), "감사의견"),
    ("한정의견", dict(감사의견="한정"), "감사의견"),
    ("유동비율 9.9%", dict(FF=0.099), "유동비율"),
    ("시총 349억", dict(시가총액=MIN_MCAP_EOK - 1), "시가총액"),
    ("거래대금 9억", dict(거래대금=MIN_TURNOVER_EOK - 1), "거래대금"),
]
for label, kw, expect in cases:
    df = pd.DataFrame([row("정상", "000001"), row("불량", "000009", **kw)])
    p, r = prescreen(df)
    hit = len(r) and expect in r.iloc[0]["사유"] and "000009" not in set(p["코드"])
    check(f"{label} 탈락", hit, r["사유"].tolist() if len(r) else "탈락 없음")

# ── 3) 경계값은 통과한다 (미만이 제외, 이하가 아니다) ─────────────────
edge = pd.DataFrame([row("경계", "000001", FF=0.10, 시가총액=MIN_MCAP_EOK,
                         거래대금=MIN_TURNOVER_EOK)])
p, r = prescreen(edge)
check("경계값(FF 10%·시총 350억·거래대금 10억)은 통과", len(p) == 1 and len(r) == 0,
      r["사유"].tolist() if len(r) else "")

# ── 4) 한 종목이 여러 규칙에 걸리면 사유가 전부 남는다 ────────────────
multi = pd.DataFrame([row("복합", "000009", 관리종목=True, 자본잠식=True,
                          감사의견="의견거절")])
p, r = prescreen(multi)
check("복수 사유 전부 기록", len(p) == 0 and len(r) == 3, f"사유 {len(r)}건")
check("요약에 종목명 표기", "복합" in prescreen_summary(r, []))

# ── 5) 열 누락은 조용히 통과시키지 않는다 ─────────────────────────────
no_col = clean.drop(columns=["관리종목"])
try:
    prescreen(no_col)
    check("열 누락 시 strict 예외", False)
except ValueError:
    check("열 누락 시 strict 예외", True)
p, r = prescreen(no_col, strict=False)
check("strict=False면 '검사 불가'로 기록", p.attrs["unchecked"] == [
    "[시장조치] 관리종목·투자주의환기 지정"], p.attrs["unchecked"])
check("요약에 검사 불가 경고", "검사 불가" in prescreen_summary(r, p.attrs["unchecked"]))

# ── 6) 빈 입력 방어 ───────────────────────────────────────────────────
try:
    prescreen(pd.DataFrame(columns=clean.columns))
    check("빈 입력 방어", False)
except ValueError:
    check("빈 입력 방어", True)

# ── 7) 회귀: 파이프라인 끝까지 — 오염 종목이 구성에 들어오지 못한다 ───
from etf.scenario_min10 import load_judged, run_scenario  # noqa: E402

GRANTED = ["253590", "425040", "357780", "036930", "322310"]
j = load_judged()
base = run_scenario(j, grant_codes=GRANTED)
check("실데이터 스크린 탈락 0 (현 판정 33종목은 전원 적격)",
      base["사전스크린 탈락"] == 0)
check("스크린 도입 후에도 최종 12종목·순도 29.0% 불변",
      base["종목수"] == 12 and abs(base["HBM순도(%)"] - 29.0) < 0.01,
      f"{base['종목수']}종목 순도 {base['HBM순도(%)']}")

dirty = j.copy()
m = dirty["종목명"] == "한미반도체"
dirty.loc[m, ["관리종목", "자본잠식"]] = [True, True]
dirty.loc[m, "감사의견"] = "의견거절"
bad = run_scenario(dirty, grant_codes=GRANTED)
check("오염 종목은 구성에서 차단",
      "한미반도체" not in set(bad["_구성"]["종목명"]),
      bad["_구성"]["종목명"].tolist())
check("차단 후 종목수 1 감소", bad["종목수"] == base["종목수"] - 1,
      f"{bad['종목수']} vs {base['종목수']}")
check("탈락 건수 리포트", bad["사전스크린 탈락"] == 1, bad["사전스크린 탈락"])

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
