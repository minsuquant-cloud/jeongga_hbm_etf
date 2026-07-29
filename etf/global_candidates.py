# -*- coding: utf-8 -*-
"""
etf/global_candidates.py — 글로벌 확장(경로 B) 후보 등록부 + fail-closed 검증
=============================================================================
"정가 HBM ETF"를 해외로 확장하되 **팀 방법론을 그대로 적용**하기 위한 레이어.

큰 틀 (바꾸지 않는 것)
----------------------
- 판정 규칙: selection.py의 규칙 0/A/C 그대로 (앵커 = 메모리제조×HBM양산,
  핵심 = 노출도≥30%, 위성 = 메모리향≥70%+공정확인+위원회확인). 문턱 무수정.
- 실사 원칙: fail-closed — 공시 문서 근거가 없으면 빈칸으로 두고, 빈칸은
  편입 불가다. "앞으로 연관될 것"은 전망이지 판정 요건이 아니다.
- 실사 판정의 주체는 사용자다. 이 모듈은 판정을 **하지 않는다** —
  후보를 등록하고, 채워진 판정을 검증하고, 엔진에 넘길 뿐이다.

테마 가드
---------
등록부(CANDIDATES)에 없는 티커는 판정 CSV에 있어도 거부한다. 체인구간
근거 없이 종목이 늘어나는 것(테마 이탈)을 코드로 막는 장치다. 수요측
(NVIDIA·AMD)과 전공정 광의(AMAT·LRCX·TEL)는 방법론상 제외 — 사유는
EXCLUDED에 기록해 "왜 없나"라는 질문에 코드가 답하게 한다.

단위 계약 (판정 CSV — 국내 판정완료와 동일 스키마)
  시가총액·유동시총·거래대금: **억 원(KRW 환산)** — 환산기준일 컬럼에 날짜 기록
  FF: 0~1 / HBM노출도·메모리향비중: 0~1 (35% → 0.35. 35로 쓰면 오류로 잡는다)
  감사의견: 적정/한정/부적정/의견거절 (unqualified opinion → '적정')
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
TEMPLATE = os.path.join(PROC, "글로벌후보_실사_20260729.csv")

# ── 후보 등록부 — 체인구간 근거가 편입의 전제다 ──────────────────────────
# 조회티커: FDR 조회 시도 순서(원주 우선, OTC ADR 폴백 — 원주가 데이터 질이 좋다).
CANDIDATES = [
    {"코드": "MU", "종목명": "Micron Technology", "거래소": "NASDAQ", "통화": "USD",
     "체인구간": "HBM 제조", "유형": "메모리제조", "조회티커": ["MU"],
     "근거문서": "10-K Part I·II — DRAM/HBM 매출 구성, HBM 양산 공시",
     "국내대응": "삼성전자·SK하이닉스 (세계 HBM 3사 중 유일한 비편입)"},
    {"코드": "TSM", "종목명": "TSMC", "거래소": "NYSE(ADR)", "통화": "USD",
     "체인구간": "로직다이·CoWoS 패키징", "유형": "파운드리", "조회티커": ["TSM"],
     "근거문서": "20-F — HBM 관련(CoWoS/SoIC) 매출 귀속 근거",
     "국내대응": "없음 ※규칙상 핵심(노출도30%)·위성(메모리향70%) 문턱을 넘기 어려움 — 그 판정도 유효한 결과"},
    {"코드": "BESI.AS", "종목명": "BE Semiconductor", "거래소": "Euronext", "통화": "EUR",
     "체인구간": "하이브리드 본딩 장비", "유형": "장비", "조회티커": ["BESI.AS", "BESIY"],
     "근거문서": "Annual Report — hybrid bonding 수주·매출 비중",
     "국내대응": "한미반도체"},
    {"코드": "0522.HK", "종목명": "ASMPT", "거래소": "HKEX", "통화": "HKD",
     "체인구간": "TC 본더", "유형": "장비", "조회티커": ["0522.HK", "ASMVF"],
     "근거문서": "Annual Report — advanced packaging(TCB) 부문",
     "국내대응": "한미반도체 (직접 경쟁)"},
    {"코드": "6857.T", "종목명": "Advantest", "거래소": "TSE", "통화": "JPY",
     "체인구간": "메모리 테스터", "유형": "장비", "조회티커": ["6857.T", "ATEYY"],
     "근거문서": "유가증권보고서 — 메모리 테스터 매출 비중, HBM 수요 언급",
     "국내대응": "테크윙·네오셈"},
    {"코드": "CAMT", "종목명": "Camtek", "거래소": "NASDAQ", "통화": "USD",
     "체인구간": "검사", "유형": "장비", "조회티커": ["CAMT"],
     "근거문서": "20-F — HBM/advanced packaging 검사 수주 공시",
     "국내대응": "오로스테크놀로지"},
    {"코드": "ONTO", "종목명": "Onto Innovation", "거래소": "NYSE", "통화": "USD",
     "체인구간": "계측", "유형": "장비", "조회티커": ["ONTO"],
     "근거문서": "10-K — advanced nodes/packaging 계측 매출",
     "국내대응": "오로스테크놀로지 ※2019 합병 상장 — 위기표본 2018 없음"},
    {"코드": "4004.T", "종목명": "Resonac", "거래소": "TSE", "통화": "JPY",
     "체인구간": "HBM 소재(접착필름 등)", "유형": "소재", "조회티커": ["4004.T"],
     "근거문서": "유가증권보고서 — 반도체 소재 부문 중 HBM 귀속(NCF 등)",
     "국내대응": "솔브레인·티이엠씨"},
]

# 방법론상 제외 — "왜 없나"에 코드가 답한다
EXCLUDED = {
    "NVDA/AMD": "수요측 — HBM 밸류체인 공급망이 아니며 메모리향비중 기준 미달",
    "AMAT/LRCX/TEL": "전공정 광의 — HBM 노출도가 낮아 핵심 문턱(30%) 구조적 미달",
    "Teradyne": "메모리 테스트 비중 낮음 (SoC 중심)",
    "Amkor": "HBM 조립은 메모리 3사가 내재화 — OSAT 귀속 매출 근거 없음",
}

# 판정 CSV 필수 컬럼 (국내 판정완료 스키마 + 환산기준일)
JUDGE_COLS = ("시가총액", "FF", "유동시총", "거래대금", "자본잠식", "유형",
              "HBM양산", "HBM노출도", "메모리향비중", "HBM공정확인",
              "위원회확인", "감사의견", "관리종목")
_RATIO_COLS = ("FF", "HBM노출도", "메모리향비중")   # 0~1 계약 — %면 하드 에러


def normalize_code(c) -> str:
    """국내 6자리는 zfill, 해외 티커는 대문자 유지.

    'MU'.zfill(6) → '0000MU'가 되는 사고를 막는다 — zfill은 숫자 코드에만.
    """
    c = str(c).strip().upper()
    return c.zfill(6) if c.isdigit() else c


def registry() -> pd.DataFrame:
    d = pd.DataFrame(CANDIDATES)
    assert d["코드"].is_unique, "등록부 티커 중복"
    return d


def write_template(path: str = TEMPLATE) -> str:
    """실사 입력 템플릿 생성. **기존 파일은 절대 덮어쓰지 않는다** —
    사용자가 채운 실사를 재생성으로 날리는 사고 방지."""
    if os.path.exists(path):
        raise FileExistsError(
            f"이미 존재: {path} — 채운 실사를 보호하기 위해 덮어쓰지 않습니다. "
            "새 템플릿이 필요하면 다른 파일명을 지정하십시오.")
    d = registry().drop(columns=["조회티커"])
    for c in JUDGE_COLS:
        if c not in d.columns:
            d[c] = ""                     # 실사로 채울 빈칸 — 빈칸 = 편입 불가
    d["PER"] = ""
    d["PBR"] = ""
    d["환산기준일"] = ""                  # 시총·거래대금 KRW 환산에 쓴 날짜
    cols = ["종목명", "코드", "거래소", "통화", "체인구간", "국내대응", "근거문서",
            "시가총액", "FF", "유동시총", "거래대금", "PER", "PBR", "자본잠식",
            "유형", "HBM양산", "HBM노출도", "메모리향비중", "HBM공정확인",
            "위원회확인", "감사의견", "관리종목", "환산기준일"]
    d[cols].to_csv(path, index=False, encoding="utf-8-sig")
    return path


def load_global_judged(path: str = TEMPLATE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """채워진 실사 CSV를 검증해 (판정 완료 행, 미완 사유 행)으로 나눈다.

    fail-closed:
      · 등록부에 없는 티커 → 즉시 예외 (테마 가드 — 조용한 편입 확대 금지)
      · 필수 필드 하나라도 빈 행 → '미실사'로 제외하고 사유를 남긴다
      · 비율 컬럼에 1.5 초과 값 → 즉시 예외 (% 표기 의심 — 35는 0.35의 100배다)
      · 유동시총 > 시가총액 → 즉시 예외 (단위 사고)
    """
    d = pd.read_csv(path, encoding="utf-8-sig")
    d["코드"] = d["코드"].map(normalize_code)
    reg_codes = set(registry()["코드"])
    alien = sorted(set(d["코드"]) - reg_codes)
    if alien:
        raise ValueError(
            f"등록부에 없는 티커: {alien} — 테마 가드. 체인구간 근거와 함께 "
            "global_candidates.CANDIDATES에 먼저 등록할 것")
    if d["코드"].duplicated().any():
        raise ValueError(f"중복 티커: {d.loc[d['코드'].duplicated(), '코드'].tolist()}")

    pending: list = []
    complete_mask = pd.Series(True, index=d.index)
    for c in JUDGE_COLS:
        if c not in d.columns:
            raise ValueError(f"판정 컬럼 누락: {c} — 템플릿을 다시 확인할 것")
        blank = d[c].isna() | (d[c].astype(str).str.strip() == "")
        complete_mask &= ~blank
        for i in d.index[blank]:
            pending.append({"종목명": d.at[i, "종목명"], "코드": d.at[i, "코드"],
                            "빈 필드": c})
    done = d[complete_mask].copy()
    pend = (pd.DataFrame(pending, columns=["종목명", "코드", "빈 필드"])
            .groupby(["종목명", "코드"])["빈 필드"]
            .apply(lambda s: ", ".join(s)).reset_index()
            if pending else pd.DataFrame(columns=["종목명", "코드", "빈 필드"]))

    if len(done):
        for c in _RATIO_COLS:
            v = pd.to_numeric(done[c], errors="coerce")
            if v.isna().any():
                raise ValueError(f"{c}에 숫자가 아닌 값: "
                                 f"{done.loc[v.isna(), '종목명'].tolist()}")
            if (v > 1.5).any():
                raise ValueError(
                    f"{c} > 1.5: {done.loc[v > 1.5, '종목명'].tolist()} — "
                    "0~1 계약 위반(% 표기 의심. 35% → 0.35)")
            if ((v <= 0) | (v > 1)).any() and c == "FF":
                raise ValueError(f"FF는 (0,1]: {done.loc[(v <= 0) | (v > 1), '종목명'].tolist()}")
            done[c] = v
        for c in ("시가총액", "유동시총", "거래대금"):
            done[c] = pd.to_numeric(done[c], errors="coerce")
            if done[c].isna().any() or (done[c] <= 0).any():
                raise ValueError(f"{c}가 결측/0 이하 — 억 원(KRW 환산) 양수여야 함")
        over = done["유동시총"] > done["시가총액"] * (1 + 1e-9)
        if over.any():
            raise ValueError(f"유동시총 > 시가총액: {done.loc[over, '종목명'].tolist()} "
                             "— 단위(억 원 KRW) 확인")
    return done, pend


def merge_with_korean(judged_kr: pd.DataFrame,
                      judged_gl: pd.DataFrame) -> pd.DataFrame:
    """국내 판정 33종목 + 판정 완료 해외 후보 → 하나의 심사 테이블.

    국내 스키마 기준으로 합친다(해외 전용 컬럼은 버림). 코드 충돌 검사.
    """
    kr = judged_kr.copy()
    kr["코드"] = kr["코드"].map(normalize_code)
    gl = judged_gl.copy()
    dup = set(kr["코드"]) & set(gl["코드"])
    if dup:
        raise ValueError(f"국내·해외 코드 충돌: {sorted(dup)}")
    cols = [c for c in kr.columns if c in gl.columns]
    merged = pd.concat([kr[cols], gl[cols]], ignore_index=True)
    return merged
