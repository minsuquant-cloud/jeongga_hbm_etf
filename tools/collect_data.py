"""
데이터 자동 수집 — 코드 리스트만 주면 시장·재무 컬럼을 채운 CSV를 만든다.

자동 채움:
  · 종목명·시가총액·상장주식수·거래대금(**60영업일 평균**)·PER·PBR → pykrx (키 불필요)
      거래대금 기간은 팀 유니버스 필터 기준(직전 60영업일 평균 10억 미만 제외)에 맞춘다.
  · 자본잠식(자본총계 < 자본금)                                 → DART (키 필요)
  · **FF(유동주식비율) → 유동시총**                             → DART (키 필요)
      FF = 1 − 최대주주등 지분율 − 자기주식비율   (KRX 유동비율 정의에 가장 근접)
      유동시총 = 시가총액 × FF
직접 채움(자동 불가):
  · HBM노출도·메모리향비중 ← DART 사업보고서 제품별 매출 + IR 읽고 사람이 추정
      (대부분 기업이 HBM을 별도 세그먼트로 공시하지 않아 자동화 불가 — 지수 핵심 입력)
  · HBM공정확인·위원회확인(규칙 C②③), 유형, 관리종목, 감사의견 ← 확인 후 입력

DART 키: 프로젝트 폴더 `.env` 에  DART_API_KEY=발급받은키  한 줄. (채팅에 붙여넣지 말 것)

입력 CSV: 최소 `코드` 컬럼(6자리, 문자열). 종목명·유형·HBM노출도가 이미 있으면 보존.
출력 CSV: build_index.py 에 바로 넣을 수 있는 형식.
"""
from __future__ import annotations

import argparse
import datetime as dt
import unicodedata

import pandas as pd
from pykrx import stock

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import os

OUT_COLS = ["종목명", "코드", "유형", "HBM양산", "HBM노출도", "메모리향비중",
            "HBM공정확인", "위원회확인", "시가총액", "FF", "유동시총",
            "거래대금", "PER", "PBR", "자본잠식", "관리종목", "감사의견"]


def _pad(text, width: int) -> str:
    """한글(전각 2칸) 폭을 반영한 왼쪽 정렬 패딩 — 진행 로그 열 맞춤용."""
    s = str(text)
    w = sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)
    return s + " " * max(0, width - w)


def _num(v, width: int, dec: int = 1) -> str:
    """숫자 오른쪽 정렬(천단위 콤마). None이면 '-'."""
    s = "-" if v is None else f"{v:,.{dec}f}"
    return s.rjust(width)


TURNOVER_DAYS = 60          # 팀 유니버스 필터 기준: 직전 60영업일 평균 거래대금
_LOOKBACK_CAL_DAYS = 120    # 60영업일 확보용 달력일수 (60영업일 ≈ 84일 + 공휴일 여유)


def _period():
    today = dt.date.today()
    return ((today - dt.timedelta(days=_LOOKBACK_CAL_DAYS)).strftime("%Y%m%d"),
            today.strftime("%Y%m%d"))


def collect_market(code: str) -> dict:
    """pykrx: 종목명·시가총액(억)·상장주식수·거래대금(억, 60영업일 평균)·PER·PBR.

    거래대금 평균 기간은 팀 유니버스 필터 기준인 **60영업일**이다(README '기초 유니버스 필터').
    20영업일(약 1개월) 평균은 테마 뉴스에 따른 일시적 급등 구간을 그대로 반영해
    평소 유동성이 부족한 종목까지 통과시키므로 쓰지 않는다.
    """
    s, e = _period()
    out = {"종목명": None, "시가총액": None, "상장주식수": None,
           "거래대금": None, "거래대금일수": None, "PER": None, "PBR": None}
    try:
        out["종목명"] = stock.get_market_ticker_name(code)
    except Exception:
        pass
    try:
        cap = stock.get_market_cap(s, e, code)
        if len(cap):
            out["시가총액"] = round(float(cap["시가총액"].iloc[-1]) / 1e8, 1)        # 억원
            out["상장주식수"] = int(cap["상장주식수"].iloc[-1])
            window = cap["거래대금"].tail(TURNOVER_DAYS)
            # 상장 3개월 미만 등으로 60영업일이 안 되면 평균이 실제보다 부정확해진다.
            # 조용히 넘기지 않고 실제 사용한 일수를 표시한다.
            if len(window) < TURNOVER_DAYS:
                out["거래대금일수"] = len(window)
            out["거래대금"] = round(float(window.mean()) / 1e8, 1)  # 억원
    except Exception:
        pass
    try:
        fund = stock.get_market_fundamental(s, e, code)
        if len(fund):
            out["PER"] = round(float(fund["PER"].iloc[-1]), 2)
            out["PBR"] = round(float(fund["PBR"].iloc[-1]), 2)
    except Exception:
        pass
    return out


def _make_dart(key: str):
    """OpenDartReader 버전차 흡수. 0.3.x=opendartreader.OpenDartReader / 0.2.x=OpenDartReader()."""
    try:
        import opendartreader
        return opendartreader.OpenDartReader(key)
    except ImportError:
        import OpenDartReader
        cls = getattr(OpenDartReader, "OpenDartReader", OpenDartReader)
        return cls(key)


def _to_num(v):
    """'1,234' / '12.34%' / '-' → float. 변환 불가면 None."""
    s = str(v).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def collect_float_ratio(dart, code: str, shares_out: int | None = None) -> dict:
    """DART: 유동주식비율(FF) = 1 − 최대주주등 지분율 − 자기주식비율.

    KRX 공식 유동비율(최대주주등·자기주식·정부지분·우리사주 제외)에 가장 가까운 근사다.
    「소액주주」 지분율은 '1% 미만 보유자'만 세어 국민연금 등 실제 유동물량을 빼버리므로
    FF를 과소평가한다 → 여기서는 쓰지 않는다.

    반환: {"FF": 0~1, "최대주주등": %, "자기주식": %}  (확인 불가 항목은 None)
    """
    out = {"FF": None, "최대주주등": None, "자기주식": None}
    if dart is None:
        return out

    for year in (dt.date.today().year - 1, dt.date.today().year - 2):
        # --- 최대주주 및 특수관계인 합계(공시 '계' 행을 그대로 사용) ---
        try:
            m = dart.report(code, "최대주주", year)
            if m is None or len(m) == 0:
                continue
            tot = m[m["nm"].astype(str).str.strip().isin(["계", "합계"])]
            if len(tot):
                # 보통주 기준 우선. 없으면 첫 합계행.
                com = tot[tot["stock_knd"].astype(str).str.contains("보통", na=False)]
                row = com.iloc[0] if len(com) else tot.iloc[0]
                out["최대주주등"] = _to_num(row["trmend_posesn_stock_qota_rt"])
        except Exception:
            pass

        # --- 자기주식(보통주 '총계' 행) ---
        if shares_out:
            try:
                t = dart.report(code, "자기주식", year)
                if t is not None and len(t):
                    tot = t[(t["acqs_mth1"].astype(str).str.strip() == "총계")
                            & (t["stock_knd"].astype(str).str.contains("보통", na=False))]
                    if len(tot):
                        qty = _to_num(tot["trmend_qy"].iloc[0])
                        if qty is not None:
                            out["자기주식"] = round(qty / shares_out * 100, 2)
            except Exception:
                pass

        if out["최대주주등"] is not None:
            ff = 1.0 - out["최대주주등"] / 100 - (out["자기주식"] or 0.0) / 100
            out["FF"] = round(max(0.0, min(1.0, ff)), 4)
            return out
    return out


def collect_capital_impairment(dart, code: str):
    """DART: 자본잠식 여부(자본총계 < 자본금). True/False/None(확인불가)."""
    if dart is None:
        return None
    for year in (dt.date.today().year - 1, dt.date.today().year - 2):
        try:
            fs = dart.finstate(code, year)
            if fs is None or len(fs) == 0:
                continue
            nm = fs["account_nm"].astype(str)

            def _amt(keyword):
                row = fs[nm.str.replace(" ", "").str.contains(keyword, na=False)]
                if len(row) == 0:
                    return None
                v = str(row["thstrm_amount"].iloc[0]).replace(",", "").strip()
                return float(v) if v not in ("", "-") else None

            equity = _amt("자본총계")
            capital = _amt("자본금")
            if equity is None:
                continue
            if equity < 0:
                return True                       # 완전자본잠식
            if capital is not None and equity < capital:
                return True                       # 부분자본잠식
            return False
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description="HBM 후보 데이터 자동수집")
    ap.add_argument("--input", help="코드 리스트 CSV (없으면 데모 코드)")
    ap.add_argument("--out", default="후보_자동채움.csv")
    args = ap.parse_args()

    if args.input:
        df = pd.read_csv(args.input, dtype={"코드": str})
    else:
        df = pd.DataFrame({"코드": ["005930", "000660", "042700", "039030", "357780"]})
        print("※ 입력 CSV 없어 데모 코드로 실행. 실제는 --input 으로 코드 리스트 CSV.\n")
    df["코드"] = df["코드"].astype(str).str.zfill(6)

    key = os.environ.get("DART_API_KEY")
    dart = None
    if key and not key.startswith("여기에"):
        try:
            dart = _make_dart(key)
            print("DART 연결 OK — 자본잠식 + 유동주식비율(FF) 자동 조회\n")
        except Exception as ex:
            print(f"DART 연결 실패({ex}) — 자본잠식·FF는 빈칸으로 둠\n")
    else:
        print("※ .env 에 유효한 DART_API_KEY 없음 — 시장데이터만 채우고 자본잠식·FF는 빈칸.\n")

    rows = []
    for _, r in df.iterrows():
        code = r["코드"]
        m = collect_market(code)
        imp = collect_capital_impairment(dart, code)
        ff = collect_float_ratio(dart, code, m["상장주식수"])

        # 유동시총 = 시가총액 × FF. FF 확인 불가 시 빈칸(전체시총으로 대체하지 않는다)
        float_cap = (round(m["시가총액"] * ff["FF"], 1)
                     if (m["시가총액"] is not None and ff["FF"] is not None) else None)

        rows.append({
            "종목명": r.get("종목명") or m["종목명"],
            "코드": code,
            "유형": r.get("유형", ""),                     # 수동
            "HBM양산": r.get("HBM양산", ""),               # 수동(규칙 0 결합 요건 — 누락 시 앵커 탈락!)
            "HBM노출도": r.get("HBM노출도", ""),            # 수동(핵심)
            "메모리향비중": r.get("메모리향비중", ""),       # 수동(규칙 C①)
            "HBM공정확인": r.get("HBM공정확인", ""),        # 수동(규칙 C②)
            "위원회확인": r.get("위원회확인", ""),          # 수동(규칙 C③)
            "시가총액": m["시가총액"],
            "FF": ff["FF"],
            "유동시총": float_cap,
            "거래대금": m["거래대금"],
            "PER": m["PER"], "PBR": m["PBR"],
            "자본잠식": {True: True, False: False, None: ""}[imp],
            "관리종목": r.get("관리종목", ""),               # 수동/확인
            "감사의견": r.get("감사의견", ""),               # 수동/확인
        })
        ff_txt = "-" if ff["FF"] is None else f"{ff['FF']*100:5.2f}%"
        short = (f" ⚠{m['거래대금일수']}일" if m["거래대금일수"] else "")
        print(f"  {code}  {_pad(m['종목명'] or '?', 16)} "
              f"시총 {_num(m['시가총액'], 11)}억  "
              f"FF {ff_txt}  유동시총 {_num(float_cap, 11)}억  "
              f"거래대금 {_num(m['거래대금'], 8)}억{short}  "
              f"자본잠식 {'?' if imp is None else imp}")

    out = pd.DataFrame(rows)[OUT_COLS]
    out.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"\n저장: {args.out}")
    print("→ 남은 수동 입력: 유형 · HBM노출도 · 메모리향비중 · HBM공정확인 · 위원회확인")
    print("   (채운 뒤 build_index.py --input 으로 바로 사용)")


if __name__ == "__main__":
    main()
