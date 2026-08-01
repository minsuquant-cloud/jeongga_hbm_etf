# -*- coding: utf-8 -*-
"""etf/make_daily_report.py 검증 — 오프라인.

자동 실행 결과를 사람이 보는 유일한 창구다. 계약:
  · 자립형 HTML (외부 요청 0) — 오프라인·다른 PC에서도 열린다
  · 산출 CSV가 없어도 죽지 않고, 무엇을 못 읽었는지 남긴다
  · 이력은 기준일 단위로 누적하되 같은 날 재실행은 덮어쓴다 (중복 방지)
  · 값은 이스케이프한다 (종목명에 <, & 가 들어와도 HTML이 깨지지 않게)
"""
import os
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import etf.make_daily_report as mdr  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


# ── 1) 이력 누적: 같은 날 재실행은 덮어쓴다 ───────────────────────────
tmp = Path(tempfile.mkdtemp())
orig_hist = mdr.HISTORY
try:
    mdr.HISTORY = tmp / "h.csv"
    h1 = mdr.update_history({"기준일": "2026-07-30", "지수": 100.0, "경보": 1})
    check("첫 행 생성", len(h1) == 1, len(h1))
    h2 = mdr.update_history({"기준일": "2026-07-31", "지수": 110.0, "경보": 2})
    check("다음 날 누적", len(h2) == 2, len(h2))
    h3 = mdr.update_history({"기준일": "2026-07-31", "지수": 115.0, "경보": 0})
    check("같은 날 재실행은 덮어쓰기", len(h3) == 2, len(h3))
    check("덮어쓴 값이 최신", float(h3["지수"].iloc[-1]) == 115.0,
          h3["지수"].tolist())
    check("날짜 오름차순 정렬",
          list(h3["기준일"]) == ["2026-07-30", "2026-07-31"], list(h3["기준일"]))

    # ── 2) delta: 전일 대비 ───────────────────────────────────────────
    check("상승 화살표", "▲" in mdr.delta(h3, "지수"), mdr.delta(h3, "지수"))
    check("하락 화살표", "▼" in mdr.delta(
        pd.DataFrame({"지수": [100.0, 90.0]}), "지수"))
    flat = pd.DataFrame({"지수": [100.0, 100.0]})
    check("변화 없으면 '변화 없음'", "변화 없음" in mdr.delta(flat, "지수"))
    # 빈칸은 "안 변했다"로 오독된다 — 비교가 안 된 경우는 그렇게 적는다
    check("1행이면 '첫 기록'", "첫 기록" in mdr.delta(h1, "지수"),
          mdr.delta(h1, "지수"))
    check("없는 컬럼이면 빈 문자열", mdr.delta(h3, "없는칼럼") == "")
    nan_h = pd.DataFrame({"지수": [None, 100.0]})
    check("이전 값 결측이면 '비교 불가'(변화 없음과 구분)",
          "비교 불가" in mdr.delta(nan_h, "지수"), mdr.delta(nan_h, "지수"))
    # 표시 단위가 이력과 다를 때(만원→억) 화살표 숫자도 같은 단위여야 한다
    scaled = mdr.delta(pd.DataFrame({"복제100bp(만원)": [10000.0, 30000.0]}),
                       "복제100bp(만원)", 1 / 10000)
    check("scale 적용(만원→억)", "2.00" in scaled, scaled)
finally:
    mdr.HISTORY = orig_hist

# ── 2b) sparkline: 인라인 SVG (외부 라이브러리 0) ─────────────────────
check("점이 모자라면 안 그린다", mdr.sparkline([1.0, 2.0]) == "")
up = mdr.sparkline([1.0, 2.0, 3.0, 5.0])
dn = mdr.sparkline([5.0, 3.0, 2.0, 1.0])
check("상승은 기본 색", 'class="spark"' in up)
check("하락은 dn 클래스", 'class="spark dn"' in dn, dn[:40])
check("스파크도 자립형(외부 요청 없음)",
      not re.search(r'https?://|src=', up))
check("평평한 값도 0으로 나누지 않는다", "polyline" in mdr.sparkline([7.0] * 5))
# 끝점 원이 viewBox 밖으로 나가면 잘려 보인다 — 좌우 여백 확인
_pts = re.search(r'class="sl" points="([^"]+)"', up).group(1).split()
_xs = [float(p.split(",")[0]) for p in _pts]
_ys = [float(p.split(",")[1]) for p in _pts]
check("x가 viewBox 안(끝점 잘림 없음)", 0 < min(_xs) and max(_xs) < 720,
      (min(_xs), max(_xs)))
check("y가 viewBox 안", 0 < min(_ys) and max(_ys) < 90, (min(_ys), max(_ys)))

# ── 3) HTML: 자립형 + 이스케이프 ──────────────────────────────────────
d = {"기준일": "2026-07-31", "생성": "2026-08-01 12:00",
     "지수": 51013.1, "일간(%)": 25.4, "MDD(%)": -44.9, "순도(%)": 29.81,
     "용량(억)": 1692, "갭12.5y(bp)": 79.0, "CU(억)": 30,
     "복제100bp(만원)": 38395, "상장요건": "[R1] PASS · [R2] PASS",
     "경보": 1, "미검사": 1,
     "_경보목록": [["<script>x</script>", "편입", "⛔4분기연속적자"]],
     "_미검사목록": ["MU & Co"]}
hist = pd.DataFrame([{"기준일": "2026-07-30", "지수": 40688.1, "일간(%)": -5.7,
                      "순도(%)": 29.81, "용량(억)": 1741, "CU(억)": 20, "경보": 2},
                     {"기준일": "2026-07-31", "지수": 51013.1, "일간(%)": 25.4,
                      "순도(%)": 29.81, "용량(억)": 1692, "CU(억)": 30, "경보": 1}])
h = mdr.build_html(d, hist)
check("외부 요청 0 (자립형)",
      not re.search(r'https?://|<script\s|<link\s|src=', h),
      re.findall(r'https?://|<script\s|<link\s|src=', h))
check("HTML 태그 이스케이프 (종목명에 <script> 넣어도)",
      "<script>x</script>" not in h and "&lt;script&gt;" in h)
check("앰퍼샌드 이스케이프", "MU &amp; Co" in h, "MU & Co" in h)
check("핵심 수치 포함", all(s in h for s in ("51,013.1", "29.81", "1,692")),
      "")
check("경보 배지 표시", 'class="badge bad"' in h)
check("미검사 배지 표시", "미검사 1" in h)
check("전일 대비 화살표 렌더", "▲" in h or "▼" in h)
check("수익률 주의 문구 유지", "성과 주장에 쓰지 않는다" in h)

# ── 4) 경보 0이면 초록 배지 ───────────────────────────────────────────
d0 = dict(d, 경보=0, 미검사=0, _경보목록=[], _미검사목록=[])
h0 = mdr.build_html(d0, hist)
check("경보 0 → ok 배지", 'class="badge ok"' in h0)
check("경보 없음 문구", "경보 없음" in h0)

# ── 5) 값이 없어도 죽지 않는다 (— 로 표기) ────────────────────────────
h_empty = mdr.build_html({"기준일": None, "생성": "x"}, pd.DataFrame())
check("빈 입력에도 HTML 생성", len(h_empty) > 500 and "<html" in h_empty)
check("없는 값은 —", "—" in h_empty)

# ── 6) 실데이터 스모크: 실제 산출로 리포트가 만들어진다 ───────────────
if (mdr.OUT / "compliance_report.csv").exists():
    real = mdr.collect()
    check("실데이터 기준일 존재", bool(real.get("기준일")), real.get("기준일"))
    check("실데이터 상장요건 읽힘", "PASS" in str(real.get("상장요건")),
          real.get("상장요건"))
    check("읽지 못한 항목 없음", not mdr._missing, mdr._missing)
else:
    check("산출물 스모크(건너뜀 — run_all 미실행)", True)

# ── 7) 데이터 신선도 — 체인이 끊기면 알아채야 한다 ────────────────────
# D:\data\_live는 JVS_Daily(20:00, 주중)가 갱신하고 이 레포는 21:00에 읽는다.
# 그 체인이 끊기면 리포트가 조용히 어제 숫자를 계속 보여주므로 등급으로 드러낸다.
import datetime as _dt  # noqa: E402

_today = _dt.date.today()


def _fr(days_ago):
    return mdr._freshness((_today - _dt.timedelta(days=days_ago)).isoformat())


check("기준일 없으면 unknown", mdr._freshness(None)["등급"] == "unknown")
check("어제 데이터는 정상", _fr(1)["등급"] == "ok", _fr(1))
# 영업일 기준이라 주말을 끼면 달력일이 늘어도 정상이어야 한다
mon = _today - _dt.timedelta(days=(_today.weekday() - 0) % 7)   # 이번 주 월요일
fri_before = mon - _dt.timedelta(days=3)                        # 그 전 금요일
check("월요일에 직전 금요일 데이터는 정상(주말 제외)",
      mdr._freshness(fri_before.isoformat())["등급"] == "ok"
      if _today.weekday() == 0 else True)
check("영업일 3일 이상 경과는 bad", _fr(7)["등급"] == "bad", _fr(7))
check("bad 등급은 원인 안내 포함", "JVS_Daily" in _fr(7)["말"], _fr(7)["말"])

# 신선도가 나쁘면 HTML에 배너가 뜬다
d_stale = dict(d, _신선도={"등급": "bad", "말": "9일 전 데이터 — 자동 갱신 멈춤"})
h_stale = mdr.build_html(d_stale, hist)
check("stale이면 배너 표시", "데이터 신선도" in h_stale and "9일 전" in h_stale)
d_ok = dict(d, _신선도={"등급": "ok", "말": "최신 (1일 전 종가)"})
check("정상이면 배너 없음", "데이터 신선도" not in mdr.build_html(d_ok, hist))

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
