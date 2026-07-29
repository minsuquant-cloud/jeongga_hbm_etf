# -*- coding: utf-8 -*-
"""etf/run_rebalance_review.py 검증 — 오프라인(합성 판정), 네트워크 불필요.

승인 게이트의 가드:
  · 판정 불변이면 제안 = 현행 (기준선 — 가짜 변경을 만들지 않는다)
  · 버퍼: 기존 핵심 0.28은 유지(hold 0.27), 신규 0.28은 미편입 (히스테리시스)
  · 사전 스크린 탈락은 버퍼보다 우선 (하드 탈락)
  · 해외 티커(MU)가 zfill로 '0000MU'가 되면 기존 대조가 깨진다 — 회귀
  · diff 손계산: 회전율 = 0.5Σ|Δw|
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.rebalance import ConfigV2, select_from_selection  # noqa: E402
from etf.run_rebalance_review import composition_diff, propose  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


def jrow(name, code, 유형="장비", 양산=False, 노출=0.5, 메모리=0.8,
         공정=True, 위원회=True, 시총=50_000.0, ff=0.6, **kw):
    r = {"종목명": name, "코드": code, "시가총액": 시총, "FF": ff,
         "유동시총": 시총 * ff, "거래대금": 500.0, "PER": 10.0, "PBR": 1.0,
         "자본잠식": False, "유형": 유형, "HBM양산": 양산, "HBM노출도": 노출,
         "메모리향비중": 메모리, "HBM공정확인": 공정, "위원회확인": 위원회,
         "감사의견": "적정", "관리종목": False}
    r.update(kw)
    return r


JUDGED = pd.DataFrame([
    jrow("삼성전자", "005930", 유형="메모리제조", 양산=True, 노출=0.10,
         메모리=0.55, 시총=15_000_000.0, ff=0.78),
    jrow("Micron Technology", "MU", 유형="메모리제조", 양산=True, 노출=0.25,
         메모리=0.98, 시총=2_000_000.0, ff=0.9),
    jrow("한미핵심", "042700", 노출=0.60, 메모리=0.80, 시총=200_000.0),
    jrow("경계핵심", "089030", 노출=0.28, 메모리=0.50, 시총=20_000.0),   # 버퍼 구간
    jrow("신규경계", "999990", 노출=0.28, 메모리=0.50, 시총=20_000.0),   # 같은 값, 신규
    jrow("위성A", "357780", 노출=0.05, 메모리=0.72, 시총=23_000.0),
])

CURRENT = pd.DataFrame([
    {"종목명": "삼성전자", "코드": "005930", "군": "앵커", "편입비중(%)": 20.0},
    {"종목명": "Micron Technology", "코드": "MU", "군": "앵커", "편입비중(%)": 20.0},
    {"종목명": "한미핵심", "코드": "042700", "군": "핵심", "편입비중(%)": 30.0},
    {"종목명": "경계핵심", "코드": "089030", "군": "핵심", "편입비중(%)": 12.0},
    {"종목명": "위성A", "코드": "357780", "군": "위성", "편입비중(%)": 18.0},
])

# ── 1) 버퍼 히스테리시스: 같은 0.28인데 기존은 유지·신규는 미편입 ─────
r = propose(JUDGED, CURRENT, ConfigV2())            # mid: hold_core 0.27
prop = r["proposal"].set_index("코드")
check("기존 경계핵심(0.28) 버퍼 유지", "089030" in prop.index)
check("신규 경계(0.28) 미편입", "999990" not in prop.index)
check("버퍼 유지 비고 표시",
      r["diff"].set_index("코드").at["089030", "비고"].startswith("⚠버퍼"),
      r["diff"].set_index("코드").at["089030", "비고"])

# ── 2) MU 정규화 회귀: '0000MU'가 되면 기존 대조 실패 ─────────────────
check("MU가 앵커로 유지 (zfill 미적용)",
      "MU" in prop.index and prop.at["MU", "군"] == "앵커",
      prop.index.tolist())
check("'0000MU' 없음", "0000MU" not in prop.index)

# ── 3) 하드 탈락 > 버퍼 ───────────────────────────────────────────────
dirty = JUDGED.copy()
dirty.loc[dirty["코드"] == "089030", "관리종목"] = True
r3 = propose(dirty, CURRENT, ConfigV2())
check("관리종목 지정 시 버퍼 무시하고 편출",
      "089030" not in r3["proposal"].set_index("코드").index)
check("편출 사유에 스크린 기록",
      "스크린" in r3["diff"].set_index("코드").at["089030", "비고"])

# ── 4) 버퍼 none이면 경계핵심도 편출 (정책이 결과를 바꾼다) ───────────
r4 = propose(JUDGED, CURRENT, ConfigV2.with_policy("none"))
check("버퍼 none → 경계핵심 편출",
      "089030" not in r4["proposal"].set_index("코드").index)

# ── 5) diff 손계산 ────────────────────────────────────────────────────
old = pd.DataFrame([{"종목명": "A", "코드": "000001", "군": "핵심", "편입비중(%)": 60.0},
                    {"종목명": "B", "코드": "000002", "군": "위성", "편입비중(%)": 40.0}])
new = pd.DataFrame([{"종목명": "A", "코드": "000001", "군": "핵심", "편입비중(%)": 50.0},
                    {"종목명": "C", "코드": "000003", "군": "위성", "편입비중(%)": 50.0}])
diff, tno = composition_diff(old, new)
d = diff.set_index("코드")
check("신규/편출/유지 구분", d.at["000003", "구분"] == "신규 편입"
      and d.at["000002", "구분"] == "편출" and d.at["000001", "구분"] == "유지")
check("회전율 = 0.5×(10+40+50) = 50%", abs(tno - 50.0) < 1e-9, tno)

grp = pd.DataFrame([{"종목명": "A", "코드": "000001", "군": "위성", "편입비중(%)": 100.0}])
diff2, _ = composition_diff(old.iloc[:1].assign(**{"편입비중(%)": 100.0}), grp)
check("군 이동 표기", diff2["구분"].iloc[0] == "군 이동 핵심→위성",
      diff2["구분"].iloc[0])

# ── 6) 순도 계산: 노출도 모르는 편입 종목은 예외 (fail-closed) ────────
try:
    propose(JUDGED[JUDGED["코드"] != "MU"], CURRENT, ConfigV2())
    check("노출도 미상 종목 예외", False)
except ValueError as e:
    check("노출도 미상 종목 예외", "MU" in str(e), str(e)[:60])

# ── 7) select_from_selection 직접 회귀: 판정 불변 → 구성 불변 ─────────
sel = select_from_selection(JUDGED, prev_members=set(CURRENT["코드"]),
                            cfg=ConfigV2())
check("판정 불변 시 기존 5종목 전원 잔류 + 신규 없음",
      set(sel["코드"]) == set(CURRENT["코드"]), sorted(sel["코드"]))

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
