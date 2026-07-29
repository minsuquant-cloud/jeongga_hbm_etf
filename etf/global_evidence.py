# -*- coding: utf-8 -*-
"""
etf/global_evidence.py — 해외 후보 판정근거 수집 (SEC EDGAR판)
==============================================================
src/hbm_evidence.py("찾는 시간을 없애고 판단만 남긴다")의 해외 이식.
SEC 제출사(MU·ONTO·CAMT 10-K, TSM 20-F)의 최신 연차보고서를 받아
종목별 판정 카드(.md)를 만든다. **판정 주체는 사용자** — 이 도구는
카드만 만들고 실사 CSV(글로벌후보_실사_*.csv)에는 절대 쓰지 않는다.

관할 커버리지 (이번 단계)
    NASDAQ·NYSE 상장 = SEC EDGAR      → 지원 (MU, TSM, CAMT, ONTO)
    TSE(6857.T·4004.T)=EDINET, HKEX(0522.HK), Euronext(BESI.AS)=자체 IR
                                       → 다음 단계 (지정 시 안내 후 스킵)

데이터 접근 (API 키 불필요 — User-Agent만 필수)
    CIK 해석   : https://www.sec.gov/files/company_tickers.json (캐시)
    최신 보고서: https://data.sec.gov/submissions/CIK##########.json
    원문       : https://www.sec.gov/Archives/edgar/data/... (캐시)
    자본총계   : companyconcept XBRL (us-gaap → 실패 시 ifrs-full)

사용법
    .venv/Scripts/python.exe etf/global_evidence.py             # SEC 4종 전부
    .venv/Scripts/python.exe etf/global_evidence.py --codes MU
    .venv/Scripts/python.exe etf/global_evidence.py --refresh   # 캐시 무시

결과: etf/evidence_global/<코드>_<종목명>.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.global_candidates import registry, normalize_code  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
OUTDIR = BASE / "etf" / "evidence_global"
CACHE = BASE / "docs_cache" / "edgar"

# SEC 규정: 자동화 접근은 연락처가 든 User-Agent 필수. 없으면 403이 온다.
USER_AGENT = "jeongga-hbm-etf estcamp.ai.22@gmail.com"
SLEEP_SEC = 0.15          # 초당 10회 미만 권고 준수

# 이번 단계에서 지원하는 거래소 (SEC 제출사)
SEC_EXCHANGES = ("NASDAQ", "NYSE")

# ── 영문 키워드 세트 — hbm_evidence.py의 한글 세트와 같은 역할 ───────────
#   전부 대문자인 약어(HBM·TSV·TCB·DRAM·NAND)는 대소문자 구분 매칭:
#   'tsv 파일' 같은 무관 소문자 오탐 방지. 나머지는 대소문자 무시.
HBM_KW = ["HBM", "high bandwidth memory", "high-bandwidth memory"]
PROC_KW = ["hybrid bonding", "TSV", "through-silicon via", "through silicon via",
           "TCB", "thermocompression", "thermo-compression",
           "advanced packaging", "CoWoS", "die stacking", "stacked die"]
MEM_KW = ["DRAM", "NAND", "memory"]
NONMEM_KW = ["foundry", "logic", "display", "automotive", "SoC"]

# 세그먼트/매출 구성 표가 있을 법한 구간의 표식
SEGMENT_PAT = re.compile(
    r"disaggregation of revenue|revenue by (technology|market|product|segment|"
    r"business unit)|reportable segment", re.I)


# ═════════════════════════════════════════════════════════════════════════
# 순수 함수 (네트워크 없음 — 오프라인 테스트 대상)
# ═════════════════════════════════════════════════════════════════════════
def resolve_cik(mapping: dict, ticker: str) -> int:
    """company_tickers.json(dict) → CIK. 없으면 예외 (조용한 실패 금지).

    형식: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
    """
    t = str(ticker).strip().upper()
    for row in mapping.values():
        if str(row.get("ticker", "")).upper() == t:
            return int(row["cik_str"])
    raise ValueError(f"SEC 티커 매핑에 없음: {ticker} — 상장폐지/티커 변경 확인")


def pick_filing(submissions: dict) -> dict:
    """submissions json → 최신 연차보고서 1건.

    10-K/20-F 우선, 없으면 정정본(/A), 그것도 없으면 분기(10-Q/6-K) 폴백.
    반환: {form, accession, filingDate, reportDate, primaryDocument}
    """
    rec = submissions.get("filings", {}).get("recent", {})
    forms = rec.get("form", [])
    for wanted in (("10-K", "20-F"), ("10-K/A", "20-F/A"), ("10-Q", "6-K")):
        for i, f in enumerate(forms):
            if f in wanted:
                return {"form": f,
                        "accession": rec["accessionNumber"][i],
                        "filingDate": rec["filingDate"][i],
                        "reportDate": rec.get("reportDate", [""] * len(forms))[i],
                        "primaryDocument": rec["primaryDocument"][i]}
    raise ValueError("연차·분기 보고서를 찾지 못함 — submissions json 확인")


def doc_url(cik: int, accession: str, primary: str) -> str:
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{primary}")


def html_to_text(html: str) -> str:
    """공시 원문(HTML/XHTML) → 평문. bs4 실패 시 정규식 폴백."""
    try:
        import warnings
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
        # 최근 10-K는 iXBRL(XHTML)이라 lxml-html 경고가 뜨지만 텍스트 추출엔 무해
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        text = BeautifulSoup(html, "lxml").get_text("\n")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("\xa0", " ").replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _kw_hit(line: str, kw: str) -> bool:
    """대문자 약어는 그대로, 나머지는 대소문자 무시."""
    if kw.isupper():
        return kw in line
    return kw.lower() in line.lower()


def keyword_lines(text: str, keywords, limit: int = 25, width: int = 200) -> list[str]:
    """키워드가 나온 줄을 중복 없이 모은다 (hbm_evidence와 같은 계약)."""
    out, seen = [], set()
    for line in text.split("\n"):
        s = line.strip()
        if len(s) < 20:                    # 목차·표 조각 제외
            continue
        if any(_kw_hit(s, k) for k in keywords):
            key = s[:60]
            if key in seen:
                continue
            seen.add(key)
            out.append(s[:width])
            if len(out) >= limit:
                break
    return out


def audit_opinion_en(text: str) -> tuple[str, list[str]]:
    """감사보고서 문구 → 국내 실사 CSV 표기로 매핑.

    가이드 규약: unqualified→적정 / qualified→한정 / adverse→부적정 /
    disclaimer→의견거절. 최근 10-K는 'unqualified'라는 단어 대신
    "present fairly, in all material respects"로 쓰므로 그 문구도 적정 판정.
    ⚠ 'unqualified'가 'qualified'를 포함하므로 판정 순서가 중요하다.
    """
    low = text.lower()

    def _ctx(phrase: str) -> list[str]:
        i = low.find(phrase)
        if i < 0:
            return []
        return [re.sub(r"\s+", " ", text[max(0, i - 150): i + 300]).strip()]

    if "disclaimer of opinion" in low:
        return "의견거절", _ctx("disclaimer of opinion")
    if "adverse opinion" in low:
        return "부적정", _ctx("adverse opinion")
    if "unqualified opinion" in low:
        return "적정", _ctx("unqualified opinion")
    # unqualified를 먼저 걸렀으므로 남은 'qualified opinion'은 진짜 한정의견.
    m = re.search(r"(?<!un)qualified opinion", low)
    if m:
        return "한정", [re.sub(r"\s+", " ",
                               text[max(0, m.start() - 150): m.start() + 300]).strip()]
    if "fairly, in all material respects" in low:
        return "적정", _ctx("fairly, in all material respects")
    return "확인필요", []


def latest_equity(concept_json: dict) -> tuple[float, str] | None:
    """companyconcept XBRL json → (최근 자본총계, 기준일). 없으면 None."""
    units = concept_json.get("units", {})
    rows = []
    for vals in units.values():          # USD·TWD 등 통화 무관 — 부호만 본다
        rows += [v for v in vals if v.get("val") is not None and v.get("end")]
    if not rows:
        return None
    best = max(rows, key=lambda v: v["end"])
    return float(best["val"]), str(best["end"])


def segment_excerpts(text: str, span: int = 2500, limit: int = 2) -> list[str]:
    """세그먼트/매출 구성 표식 주변 발췌 — 노출도·메모리향 판단 재료.

    앞쪽 매치는 목차인 경우가 많아 **뒤쪽(본문) 매치부터** 고른다.
    """
    hits = [m.start() for m in SEGMENT_PAT.finditer(text)]
    out = []
    for pos in reversed(hits):
        seg = text[pos: pos + span].strip()
        if len(seg) < 200:               # 목차 줄 조각은 제외
            continue
        out.append(seg)
        if len(out) >= limit:
            break
    return out


# ═════════════════════════════════════════════════════════════════════════
# 네트워크 계층 (캐시 + User-Agent)
# ═════════════════════════════════════════════════════════════════════════
def _get(url: str, cache_name: str | None = None, refresh: bool = False,
         binary: bool = False) -> str:
    """GET + 파일 캐시. 캐시 히트면 네트워크를 건드리지 않는다."""
    if cache_name:
        fp = CACHE / cache_name
        if fp.exists() and not refresh:
            return fp.read_text(encoding="utf-8", errors="replace")
    import requests
    time.sleep(SLEEP_SEC)
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    body = r.text
    if cache_name:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / cache_name).write_text(body, encoding="utf-8", errors="replace")
    return body


def fetch_cik(ticker: str, refresh: bool = False) -> int:
    body = _get("https://www.sec.gov/files/company_tickers.json",
                cache_name="company_tickers.json", refresh=refresh)
    return resolve_cik(json.loads(body), ticker)


def fetch_filing(cik: int) -> dict:
    # submissions는 새 공시마다 바뀌므로 캐시하지 않는다 (파일 하나라 부담 없음)
    body = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    return pick_filing(json.loads(body))


def fetch_document(cik: int, filing: dict, ticker: str,
                   refresh: bool = False) -> str:
    acc = filing["accession"].replace("-", "")
    safe = re.sub(r"[^\w.]", "_", filing["primaryDocument"])
    return _get(doc_url(cik, filing["accession"], filing["primaryDocument"]),
                cache_name=f"{ticker}_{acc}_{safe}", refresh=refresh)


def fetch_equity(cik: int) -> tuple[float, str, str] | str:
    """자본총계 (us-gaap → ifrs-full 폴백). 성공: (값, 기준일, 택소노미) /
    실패: 사유 문자열 — '확인필요'를 사람에게 그대로 보인다."""
    for taxo, tag in (("us-gaap", "StockholdersEquity"),
                      ("ifrs-full", "Equity")):
        url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
               f"CIK{cik:010d}/{taxo}/{tag}.json")
        try:
            got = latest_equity(json.loads(_get(url)))
            if got:
                return got[0], got[1], taxo
        except Exception:
            continue
    return "XBRL 자본총계 조회 실패 — 보고서 재무제표에서 직접 확인"


def krw_block(ticker: str, exchange: str) -> list[str]:
    """KRW 환산 도움 블록 — 시총·거래대금 **제안값** (판정은 사용자).

    실사 CSV 단위 계약: 억 원(KRW 환산) + 환산기준일 기록.
    실패는 사유를 그대로 적는다 — 조용히 생략하면 빈 블록이 '해당 없음'으로
    오독된다.
    """
    lines = ["**KRW 환산 도움 (제안값 — 사용자 확인 후 기입)**", ""]
    try:
        import FinanceDataReader as fdr
        px = fdr.DataReader(ticker, "2026-01-01")
        fx = fdr.DataReader("USD/KRW", "2026-01-01")["Close"].dropna()
        close = float(px["Close"].dropna().iloc[-1])
        rate = float(fx.iloc[-1])
        asof_px = str(px.index[-1].date())
        asof_fx = str(fx.index[-1].date())
        # 60거래일 평균 거래대금 (종가×거래량 근사 — fetch_adv 폴백과 같은 급)
        tail = px.dropna(subset=["Close", "Volume"]).tail(60)
        adv_usd = float((tail["Close"] * tail["Volume"]).mean())
        adv_eok = adv_usd * rate / 1e8
        lines += [
            f"- 종가 {close:,.2f} USD ({asof_px}) × 환율 {rate:,.1f} KRW/USD ({asof_fx})",
            f"- 60거래일 평균 거래대금 ≈ **{adv_eok:,.0f}억 원** "
            "(종가×거래량 근사 — 실사 CSV '거래대금' 제안값)",
            f"- 시가총액 = 종가 × 발행주식수 × 환율 ÷ 1e8 (억 원) — "
            "발행주식수는 보고서 표지(cover page)에서 확인해 계산",
            f"- `환산기준일`에 **{asof_fx}** 기입",
        ]
        if "ADR" in exchange.upper():
            lines.append("- ⚠ **ADR** — 1 ADR ≠ 1 원주일 수 있다(TSM은 1 ADR=5주). "
                         "시총 계산 시 원주 수 기준인지 반드시 확인")
    except Exception as e:
        lines.append(f"- (자동 조회 실패: {str(e)[:60]} — 수동 환산 필요)")
    return lines


# ═════════════════════════════════════════════════════════════════════════
# 카드 생성
# ═════════════════════════════════════════════════════════════════════════
def build_card(cand: dict, refresh: bool = False) -> dict:
    """후보 1종의 판정 카드 생성. 반환: 요약 dict"""
    ticker, name = cand["코드"], cand["종목명"]
    try:
        cik = fetch_cik(ticker, refresh=refresh)
        filing = fetch_filing(cik)
        html = fetch_document(cik, filing, ticker, refresh=refresh)
    except Exception as e:
        return {"코드": ticker, "종목명": name, "상태": f"EDGAR 조회 실패({str(e)[:40]})"}
    text = html_to_text(html)

    hbm_lines = keyword_lines(text, HBM_KW, limit=20)
    proc_lines = keyword_lines(text, PROC_KW, limit=15)
    mem_lines = keyword_lines(text, MEM_KW, limit=15)
    non_lines = keyword_lines(text, NONMEM_KW, limit=10)
    segments = segment_excerpts(text)
    opinion, op_lines = audit_opinion_en(text)
    equity = fetch_equity(cik)

    n_hbm = sum(text.count(k) if k.isupper() else text.lower().count(k.lower())
                for k in HBM_KW)
    n_proc = sum(text.count(k) if k.isupper() else text.lower().count(k.lower())
                 for k in PROC_KW)

    if isinstance(equity, tuple):
        eq_val, eq_end, eq_taxo = equity
        cap_note = (f"자본총계 {eq_val:,.0f} ({eq_taxo}, {eq_end} 기준) → "
                    + ("**양수 — 자본잠식 False 제안**" if eq_val > 0
                       else "**0 이하 — 자본잠식 True. 편입 불가 사유**"))
    else:
        cap_note = f"확인필요 — {equity}"

    url = doc_url(cik, filing["accession"], filing["primaryDocument"])
    md = [f"# {name} ({ticker}) — HBM 판정 근거 [EDGAR]",
          "",
          f"> 출처: **{filing['form']}** (제출 {filing['filingDate']}, "
          f"회계기준일 {filing['reportDate'] or '?'}, CIK {cik})",
          f"> 본문 {len(text):,}자 · HBM 언급 **{n_hbm}회** · "
          f"HBM 고유공정 키워드 **{n_proc}회**",
          "",
          "## ■ 판정 입력값 — 실사 CSV(글로벌후보_실사_*.csv)에 옮겨 적을 값",
          "",
          "**근거 칸을 반드시 채우세요** — 심사에서 \"이 숫자 어디서 왔나\"에",
          "답하는 유일한 기록입니다 (국내 카드 7장은 근거가 안 남아 소급 못 함).",
          "",
          "| 항목 | 값 | 근거(본 문서 어느 부분 / 원문 몇 페이지) |",
          "|---|---|---|",
          "| HBM양산 (규칙 0) | True / False |  |",
          "| HBM노출도 (규칙 A) | 0.__ |  |",
          "| 메모리향비중 (규칙 C①) | 0.__ |  |",
          "| HBM공정확인 (규칙 C②) | True / False |  |",
          "| FF | 0.__ |  |",
          "| 시가총액 (억 원 KRW) |  |  |",
          "| 유동시총 (억 원 KRW) |  |  |",
          "| 거래대금 (억 원 KRW) |  |  |",
          "",
          "**자동 조회된 사전 스크린 항목**",
          "",
          f"- 감사의견: **{opinion}**"
          + ("  ← 적정이 아니므로 **제외 대상**"
             if opinion not in ("적정", "확인필요") else "")
          + ("  ← 본문에서 감사보고서 문구를 못 찾음 — 원문 확인"
             if opinion == "확인필요" else ""),
          f"- 자본잠식: {cap_note}",
          "- 관리종목: SEC 상장사는 국내 '관리종목' 개념이 없다 — 상장폐지 심사·"
          "거래정지 중이 아니면 False (거래소 공지 확인)",
          ""]
    md += krw_block(ticker, cand.get("거래소", ""))
    md += ["",
           "---",
           "",
           "## 1. 세그먼트/매출 구성 발췌 (노출도·메모리향 판단 재료)",
           ""]
    if segments:
        for i, seg in enumerate(segments, 1):
            md += [f"### 발췌 {i}", "```", seg[:3000], "```", ""]
    else:
        md += ["(표식을 찾지 못함 — 원문 링크에서 segment note를 직접 확인)", ""]
    md += ["## 2. HBM 언급 문장", ""]
    md += [f"- {l}" for l in hbm_lines] or \
          ["- (언급 없음 → 노출도 산정 곤란 가능성. 규칙 A의 보수 원칙 적용 검토)"]
    md += ["", "## 3. HBM 고유공정 관련 (규칙 C② 판정용)", ""]
    md += [f"- {l}" for l in proc_lines] or ["- (관련 언급 없음)"]
    md += ["", "## 4. 메모리 관련 언급 (메모리향 비중 판단용)", ""]
    md += [f"- {l}" for l in mem_lines] or ["- (언급 없음)"]
    md += ["", "## 5. 비메모리·타 산업 언급 (메모리향 비중을 낮추는 요인)", ""]
    md += [f"- {l}" for l in non_lines] or ["- (언급 없음 → 메모리 전문 기업일 가능성)"]
    md += ["",
           "---",
           "",
           f"원문 보기: {url}",
           "",
           "> 노출도 산정이 곤란하면 **규칙 A에 따라 제외**한다(억지로 추정하지 않는다).",
           "> 이 카드는 판정하지 않는다 — 실사 CSV 기입과 판정은 사용자의 몫.",
           ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w가-힣]", "_", name)
    ticker_safe = re.sub(r"[^\w]", "_", ticker)
    out = OUTDIR / f"{ticker_safe}_{safe}.md"
    out.write_text("\n".join(md), encoding="utf-8")

    return {"코드": ticker, "종목명": name, "보고서": filing["form"],
            "제출일": filing["filingDate"], "HBM언급": n_hbm,
            "고유공정언급": n_proc, "감사의견": opinion, "상태": "ok",
            "카드": str(out)}


def main() -> int:
    ap = argparse.ArgumentParser(description="해외 후보 판정근거 수집 (SEC EDGAR)")
    ap.add_argument("--codes", help="쉼표 구분 티커 (예: MU,ONTO). 생략 시 SEC 제출사 전부")
    ap.add_argument("--refresh", action="store_true", help="캐시 무시하고 재다운로드")
    args = ap.parse_args()

    reg = registry().set_index("코드", drop=False)
    if args.codes:
        codes = [normalize_code(c) for c in args.codes.split(",")]
        alien = [c for c in codes if c not in reg.index]
        if alien:
            print(f"등록부에 없는 티커: {alien} — 테마 가드. "
                  "체인구간 근거와 함께 global_candidates.CANDIDATES에 먼저 등록할 것")
            return 1
    else:
        codes = list(reg.index)

    rows = []
    for c in codes:
        cand = reg.loc[c].to_dict()
        exch = str(cand.get("거래소", ""))
        if not any(x in exch.upper() for x in SEC_EXCHANGES):
            print(f"  {c} {cand['종목명']} … 관할 미지원({exch}) — "
                  "EDINET/HKEX/Euronext 수집기는 다음 단계. 건너뜀")
            continue
        print(f"  {c} {cand['종목명']} … ", end="", flush=True)
        res = build_card(cand, refresh=args.refresh)
        rows.append(res)
        if res["상태"] != "ok":
            print(res["상태"])
        else:
            print(f"{res['보고서']} · HBM {res['HBM언급']}회 · "
                  f"공정 {res['고유공정언급']}회 · 감사 {res['감사의견']}")

    if rows:
        print(f"\n판정 카드: {OUTDIR}\\<티커>_<종목명>.md  ({len(rows)}건)")
        print("→ 카드를 읽고 글로벌후보_실사_20260729.csv의 빈칸을 채우면 "
              "run_global_scenario.py가 글로벌판을 낸다 (빈칸 = 편입 불가).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
