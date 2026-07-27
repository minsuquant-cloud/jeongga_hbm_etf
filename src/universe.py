# -*- coding: utf-8 -*-
"""
src/universe.py — 기초 유니버스 사전 스크린 (methodology.md 1장)
================================================================
selection.py는 "사전 스크린(자본잠식·관리종목·감사의견·거래대금·유동비율 등)은
본 모듈의 책임이 아니다"라고 명시하며 이 모듈을 지목한다. 그런데 팀 완성본
스냅샷에서 이 파일은 **빈 파일**이었다 — 방법론 문서와 판정 CSV는 스크린을
약속하는데 집행하는 코드가 없었다(2026-07-27 점검에서 확인. 관리종목·자본잠식·
의견거절로 표시한 종목이 그대로 18% 비중으로 편입되는 것을 실증).

여기서 채우는 것은 새 규칙이 아니라 **methodology.md 1장 표를 그대로 옮긴 것**이다.

  [시장 조치]   관리종목·투자주의환기 지정 또는 상장폐지 확정
  [재무건전성]  자본잠식 / 감사의견 비적정
                (둘 다 관리종목 지정 사유 — 지정 전에 미리 걸러낸다)
  [유동성]      유동비율(FF) 10% 미만
  [재무건전성]  시가총액 350억원 미만
  [재무건전성]  직전 60영업일 평균 거래대금 10억원 미만

설계 원칙
---------
- **판정하지 창작하지 않는다.** 입력에 없는 열은 그 규칙을 '검사 불가'로
  기록하고(strict=True면 예외), 통과로 간주하지 않는다. 조용한 통과가
  스크린 부재보다 위험하다.
- 탈락 사유를 종목별로 전부 남긴다(한 종목이 여러 규칙에 걸릴 수 있다).
- selection.py·weighting.py는 건드리지 않는다 — 팀 엔진과의 diff를 최소화하고,
  호출자가 스크린을 통과한 데이터를 넘기는 구조를 유지한다.

단위 계약 (판정완료 CSV 기준)
  시가총액·거래대금 : 억 원 / FF : 0~1 비율 / 자본잠식·관리종목 : bool
"""
from __future__ import annotations

import pandas as pd

# methodology.md 1장 — 기초 유니버스 필터
MIN_FLOAT_RATE = 0.10        # 유동비율 10% 미만 제외
MIN_MCAP_EOK = 350.0         # 시가총액 350억원 미만 제외
MIN_TURNOVER_EOK = 10.0      # 60영업일 평균 거래대금 10억원 미만 제외
CLEAN_OPINION = "적정"       # 감사의견

# (열 이름, 규칙 라벨, 탈락 판정 함수) — 열이 없으면 '검사 불가'로 기록한다
_RULES: tuple = (
    ("관리종목", "[시장조치] 관리종목·투자주의환기 지정",
     lambda s: s.astype(bool)),
    ("자본잠식", "[재무] 자본잠식",
     lambda s: s.astype(bool)),
    ("감사의견", "[재무] 감사의견 비적정",
     lambda s: s.astype(str).str.strip() != CLEAN_OPINION),
    ("FF", f"[유동성] 유동비율 < {MIN_FLOAT_RATE:.0%}",
     lambda s: pd.to_numeric(s, errors="coerce") < MIN_FLOAT_RATE),
    ("시가총액", f"[재무] 시가총액 < {MIN_MCAP_EOK:,.0f}억",
     lambda s: pd.to_numeric(s, errors="coerce") < MIN_MCAP_EOK),
    ("거래대금", f"[재무] 60일 평균 거래대금 < {MIN_TURNOVER_EOK:,.0f}억",
     lambda s: pd.to_numeric(s, errors="coerce") < MIN_TURNOVER_EOK),
)


def prescreen(judged: pd.DataFrame,
              strict: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """사전 스크린을 집행한다.

    judged : 판정완료 CSV 형식 DataFrame
    strict : True면 필요한 열이 없을 때 예외(기본). False면 '검사 불가'로
             기록만 하고 계속한다 — 열이 없는 규칙은 통과 처리되지 않고,
             검사되지 않았다는 사실이 반환값 attrs["unchecked"]에 남는다.

    반환: (통과 DataFrame, 탈락 사유 DataFrame[종목명, 코드, 사유])
    """
    if len(judged) == 0:
        raise ValueError("판정 데이터가 비어 있습니다")

    missing_cols = [c for c, _, _ in _RULES if c not in judged.columns]
    if missing_cols and strict:
        raise ValueError(
            f"사전 스크린에 필요한 열이 없습니다: {missing_cols} — "
            "열을 채우거나 strict=False로 '검사 불가'를 감수할 것")

    rejects: list = []
    unchecked: list = []
    fail_any = pd.Series(False, index=judged.index)
    for col, label, test in _RULES:
        if col not in judged.columns:
            unchecked.append(label)
            continue
        hit = test(judged[col]).fillna(False).astype(bool)
        fail_any |= hit
        for i in judged.index[hit]:
            rejects.append({"종목명": judged.at[i, "종목명"],
                            "코드": judged.at[i, "코드"],
                            "사유": label})

    passed = judged[~fail_any].copy()
    passed.attrs["unchecked"] = unchecked
    return passed, pd.DataFrame(rejects, columns=["종목명", "코드", "사유"])


def prescreen_summary(rejects: pd.DataFrame, unchecked: list) -> str:
    """리포트 머리글 한 줄 — 스크린이 집행됐다는 사실을 산출물에 남긴다."""
    if len(rejects) == 0:
        head = "사전 스크린: 탈락 0종목"
    else:
        names = sorted(set(rejects["종목명"]))
        head = f"사전 스크린: {rejects['코드'].nunique()}종목 탈락 ({', '.join(names)})"
    if unchecked:
        head += f" · ⚠검사 불가 {len(unchecked)}건: {', '.join(unchecked)}"
    return head
