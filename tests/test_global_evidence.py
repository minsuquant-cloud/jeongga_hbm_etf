# -*- coding: utf-8 -*-
"""etf/global_evidence.py 검증 — 오프라인(합성 픽스처, 네트워크 불필요).

배경: S6 글로벌 확장의 실사는 해외 공시(10-K/20-F)에서 근거를 찾아야 하는데
국내 수집기(src/hbm_evidence.py)는 DART 전용 + 무조건 zfill(6)이라
'MU' → '0000MU'로 조용히 헛조회했다. 여기서는 EDGAR판의 순수 함수와
그 zfill 사고의 회귀를 검증한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.global_candidates import normalize_code, registry  # noqa: E402
from etf.global_evidence import (SEC_EXCHANGES, HBM_KW, PROC_KW,  # noqa: E402
                                 audit_opinion_en, doc_url, keyword_lines,
                                 latest_equity, pick_filing, resolve_cik,
                                 segment_excerpts)

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


# ── 1) zfill 회귀 — 'MU'가 '0000MU'가 되던 사고 ───────────────────────
check("normalize_code('MU') == 'MU'", normalize_code("MU") == "MU",
      normalize_code("MU"))
check("normalize_code('5930') == '005930'", normalize_code("5930") == "005930")
check("normalize_code('besi.as') 대문자 유지", normalize_code("besi.as") == "BESI.AS")

# ── 2) CIK 해석 — 고정 샘플 json ─────────────────────────────────────
SAMPLE = {"0": {"cik_str": 723125, "ticker": "MU", "title": "MICRON TECHNOLOGY INC"},
          "1": {"cik_str": 1046179, "ticker": "TSM",
                "title": "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"}}
check("CIK: MU", resolve_cik(SAMPLE, "MU") == 723125)
check("CIK: 소문자 입력 허용", resolve_cik(SAMPLE, "tsm") == 1046179)
try:
    resolve_cik(SAMPLE, "NVDA")
    check("CIK: 미존재 티커는 예외", False, "예외가 나지 않음")
except ValueError:
    check("CIK: 미존재 티커는 예외", True)

# ── 3) 보고서 선택 — 10-K 우선, 정정본·분기 폴백 ──────────────────────
SUB = {"filings": {"recent": {
    "form": ["8-K", "10-Q", "10-K", "10-K"],
    "accessionNumber": ["a-1", "a-2", "a-3", "a-4"],
    "filingDate": ["2026-07-01", "2026-06-01", "2025-10-01", "2024-10-01"],
    "reportDate": ["", "2026-05-28", "2025-08-28", "2024-08-29"],
    "primaryDocument": ["x.htm", "q.htm", "k1.htm", "k2.htm"]}}}
f = pick_filing(SUB)
check("10-K 우선(최신 것)", f["form"] == "10-K" and f["accession"] == "a-3",
      f)
SUB_Q = {"filings": {"recent": {
    "form": ["8-K", "10-Q"], "accessionNumber": ["a-1", "a-2"],
    "filingDate": ["2026-07-01", "2026-06-01"], "reportDate": ["", "2026-05-28"],
    "primaryDocument": ["x.htm", "q.htm"]}}}
check("연차 없으면 10-Q 폴백", pick_filing(SUB_Q)["form"] == "10-Q")
check("문서 URL 형식",
      doc_url(723125, "0000723125-25-000123", "mu-10k.htm")
      == "https://www.sec.gov/Archives/edgar/data/723125/000072312525000123/mu-10k.htm")

# ── 4) 영문 keyword_lines — 대문자 약어는 대소문자 구분 ───────────────
TEXT = "\n".join([
    "Our HBM products delivered record revenue in fiscal 2026.",
    "We ship high bandwidth memory to data center customers worldwide.",
    "the tsv file format is unrelated to semiconductors here.",   # 소문자 tsv — 오탐 금지
    "Through-silicon via (TSV) stacking enables our HBM3E products.",
    "Advanced packaging demand, including CoWoS capacity, grew rapidly.",
    "short line",
])
hbm = keyword_lines(TEXT, HBM_KW)
check("HBM 문장 2건+ 추출", len(hbm) >= 2, hbm)
proc = keyword_lines(TEXT, PROC_KW)
check("소문자 'tsv' 오탐 없음", all("unrelated" not in l for l in proc), proc)
check("TSV·CoWoS 문장 추출", len(proc) >= 2, proc)

# ── 5) 감사의견 매핑 — unqualified가 qualified로 오판되지 않는다 ──────
check("적정: present fairly",
      audit_opinion_en("In our opinion, the financial statements present "
                       "fairly, in all material respects, the position")[0] == "적정")
check("적정: unqualified opinion",
      audit_opinion_en("We have issued an unqualified opinion thereon")[0] == "적정")
check("한정: qualified opinion",
      audit_opinion_en("The auditors issued a qualified opinion on the accounts")[0] == "한정")
check("부적정: adverse", audit_opinion_en("an adverse opinion was issued")[0] == "부적정")
check("의견거절: disclaimer",
      audit_opinion_en("a disclaimer of opinion was expressed")[0] == "의견거절")
check("문구 없으면 확인필요", audit_opinion_en("no auditor language here")[0] == "확인필요")

# ── 6) 자본총계 파서 — 최근 기준일을 고른다 ───────────────────────────
CONCEPT = {"units": {"USD": [
    {"end": "2024-08-29", "val": 44000000000},
    {"end": "2025-08-28", "val": 49500000000}]}}
eq = latest_equity(CONCEPT)
check("자본총계 최근값", eq == (49500000000.0, "2025-08-28"), eq)
check("빈 concept은 None", latest_equity({"units": {}}) is None)

# ── 7) 세그먼트 발췌 — 목차(짧은 조각)가 아니라 본문을 고른다 ─────────
LONG = ("Table of contents ... reportable segment ... 5\n"
        + "filler\n" * 5
        + "Our reportable segments are Compute and Networking, Mobile, "
          "Embedded and Storage. Revenue by segment for fiscal 2026: " + "x" * 400)
seg = segment_excerpts(LONG)
check("본문 세그먼트 발췌", len(seg) >= 1 and "fiscal 2026" in seg[0],
      [s[:60] for s in seg])

# ── 8) 관할 가드 — 등록부 8종 중 SEC 제출사만 지원 대상 ───────────────
reg = registry()
sec = reg[reg["거래소"].str.upper().str.contains("|".join(SEC_EXCHANGES))]
check("SEC 제출사 = MU·TSM·CAMT·ONTO",
      set(sec["코드"]) == {"MU", "TSM", "CAMT", "ONTO"}, set(sec["코드"]))
non_sec = set(reg["코드"]) - set(sec["코드"])
check("비SEC = BESI.AS·0522.HK·6857.T·4004.T (다음 단계)",
      non_sec == {"BESI.AS", "0522.HK", "6857.T", "4004.T"}, non_sec)

# ═══════════════════════════════════════════════════════════════════════
# 해외 KRW 환산 레이어 (2026-07-29 리뷰 반영 — 정본 전환의 위험 지점들)
# 네트워크 없이 순수 함수만 검증한다.
# ═══════════════════════════════════════════════════════════════════════
import pandas as pd
from etf.hist_data import _norm, align_foreign
from etf.global_evidence import _user_agent

# ── 9) _norm — 정본 로더의 코드 정규화 (0000MU 사고 재발 방지) ─────────
check("_norm('MU') == 'MU'", _norm("MU") == "MU", _norm("MU"))
check("_norm('5930') == '005930'", _norm("5930") == "005930")

# ── 10) align_foreign — T-1 시프트 (룩어헤드 제거) ─────────────────────
kr_cal = pd.to_datetime(["2026-07-20", "2026-07-21", "2026-07-22",
                         "2026-07-23", "2026-07-24"])
us = pd.Series([100.0, 110.0, 120.0],
               index=pd.to_datetime(["2026-07-20", "2026-07-21", "2026-07-23"]))
a = align_foreign(us, kr_cal)
check("T-1: 한국 7/21에는 미국 7/20 종가", a.loc["2026-07-21"] == 100.0, a.tolist())
check("T-1: 해외 휴일(7/22) 다음날은 직전가 유지+시프트",
      a.loc["2026-07-23"] == 110.0, a.tolist())
check("T-1: 첫날은 NaN (관측 가능한 이전 종가 없음)",
      pd.isna(a.loc["2026-07-20"]))
check("T-1: 마지막날 = 미국 7/23 종가", a.loc["2026-07-24"] == 120.0)
pre = pd.Series([50.0], index=pd.to_datetime(["2026-07-23"]))   # 7/23 상장
b = align_foreign(pre, kr_cal)
check("상장 전 구간은 NaN 유지 (소급 편입 금지)",
      b.loc[:"2026-07-23"].isna().all() and b.loc["2026-07-24"] == 50.0, b.tolist())

# ── 11) fetch_prices 해외 가드 — 오프라인 실패 시 USD 혼입 대신 예외 ───
import etf.hist_data as hd
import etf.run_tracking as rt
_orig = hd.prices_offline
hd.prices_offline = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("모의 실패"))
try:
    rt.fetch_prices(["005930", "MU"], "2026-01-01", "2026-07-29")
    check("오프라인 실패+해외 → 예외 (통화 혼입 차단)", False, "예외가 나지 않음")
except RuntimeError as e:
    check("오프라인 실패+해외 → 예외 (통화 혼입 차단)", "MU" in str(e), str(e)[:80])
finally:
    hd.prices_offline = _orig

# ── 12) EDGAR UA — 이메일 하드코딩 금지, 미설정이면 즉시 실패 ──────────
import os as _os
_saved = _os.environ.pop("EDGAR_CONTACT_EMAIL", None)
try:
    _user_agent()
    check("EDGAR_CONTACT_EMAIL 미설정 → 예외", False, "예외가 나지 않음")
except RuntimeError:
    check("EDGAR_CONTACT_EMAIL 미설정 → 예외", True)
_os.environ["EDGAR_CONTACT_EMAIL"] = "test@example.com"
check("설정 시 UA에 이메일 포함", "test@example.com" in _user_agent())
if _saved is not None:
    _os.environ["EDGAR_CONTACT_EMAIL"] = _saved

print()
print("전체:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
