# -*- coding: utf-8 -*-
"""
etf/make_daily_report.py — 일일 요약 리포트 (자동 실행 결과를 사람이 읽는 창구)
==============================================================================
`run_all.py`가 CSV 34개를 갱신하지만, "오늘 상태가 어떤가"를 보려면 그걸 다
열어야 했다. 이 스크립트가 핵심 수치만 모아 **HTML 한 장**으로 만든다.

설계 원칙
---------
- **자립형 HTML** — CSS 인라인, 외부 요청 0. 브라우저로 열면 끝이고
  오프라인·다른 PC에서도 그대로 열린다.
- **전일 대비 변화를 함께 낸다.** 절대값만 보면 "오늘 이게 정상인지"를
  알 수 없다. 그래서 `daily_history.csv`에 한 줄씩 누적하고 직전 행과 비교한다.
  (같은 날 재실행하면 그날 행을 덮어쓴다 — 중복 누적 방지)
- **읽을 수 없으면 비운다.** 산출 CSV가 없거나 스키마가 바뀌면 그 칸을 `—`로
  두고 계속한다. 리포트가 죽어서 아무것도 못 보는 것보다 낫다. 단, 무엇을
  못 읽었는지는 화면에 남긴다(조용한 실패 금지).
- **판정하지 않는다.** 경보·상장요건은 각 러너가 낸 결과를 옮길 뿐이다.

    .venv/Scripts/python.exe etf/make_daily_report.py
산출: etf/output/daily_report.html · etf/output/daily_history.csv
"""
from __future__ import annotations

import datetime as dt
import html
import os
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "etf" / "output"
HISTORY = OUT / "daily_history.csv"
REPORT = OUT / "daily_report.html"
INDEX_PARQUET = Path(r"D:/data/_index/JGHBM.parquet")

_missing: list[str] = []


def _safe(label: str, fn, default=None):
    """읽기 실패를 리포트 전체 실패로 만들지 않는다 — 무엇을 못 읽었는지는 남긴다."""
    try:
        v = fn()
        return default if v is None else v
    except Exception as e:                       # noqa: BLE001
        _missing.append(f"{label} ({type(e).__name__})")
        return default


# ── 수집 ────────────────────────────────────────────────────────────────
def collect() -> dict:
    d: dict = {"기준일": None}

    def _idx():
        px = pd.read_parquet(INDEX_PARQUET)
        d["기준일"] = str(px.index[-1].date())
        ret = float(px["Close"].iloc[-1] / px["Close"].iloc[-2] - 1) * 100
        mdd = float((px["Close"] / px["Close"].cummax() - 1).min()) * 100
        return {"지수": round(float(px["Close"].iloc[-1]), 1),
                "일간(%)": round(ret, 2), "MDD(%)": round(mdd, 1)}
    d.update(_safe("JGHBM.parquet", _idx, {}) or {})

    def _long():
        raw = (OUT / "final_long.csv").read_text(encoding="utf-8-sig")
        out = {}
        for ln in raw.splitlines():
            p = ln.split(",")
            if ln.startswith("실측 갭"):
                out["갭12.5y(bp)"] = round(float(p[1]), 1)
            elif ln.startswith("정규장 기준"):
                out["용량(억)"] = round(float(p[1]))
            elif ln.startswith("100.0,"):
                out["복제100bp(만원)"] = round(float(p[1]))
        return out
    d.update(_safe("final_long.csv", _long, {}) or {})

    def _cu():
        g = pd.read_csv(OUT / "cu_grid.csv")
        f = g[g["강건"]] if "강건" in g.columns else g[g["충족"]]
        if not len(f):
            return {}
        return {"CU(억)": int(f.iloc[0]["CU금액(억)"]),
                "CU괴리(bp)": round(float(f.iloc[0]["총괴리(bp)"]), 1)}
    d.update(_safe("cu_grid.csv", _cu, {}) or {})

    d["순도(%)"] = _safe("benchmark_report.csv", lambda: round(float(
        pd.read_csv(OUT / "benchmark_report.csv").iloc[0]["순도 하한(%)"]), 2))

    def _comp():
        c = pd.read_csv(OUT / "compliance_report.csv")
        return {"상장요건": " · ".join(
            f"{a[:4]} {b}" for a, b in zip(c["항목"], c["판정"]))}
    d.update(_safe("compliance_report.csv", _comp, {}) or {})

    def _health():
        h = pd.read_csv(OUT / "health_report.csv")
        bad = h[h["경보"].str.contains("⛔", na=False)]
        unk = h[h["경보"].str.contains("❔", na=False)]
        return {"경보": int(len(bad)), "미검사": int(len(unk)),
                "_경보목록": bad[["종목명", "구분", "경보"]].values.tolist(),
                "_미검사목록": unk["종목명"].tolist()}
    d.update(_safe("health_report.csv", _health, {}) or {})

    def _reb():
        cands = sorted(OUT.glob("rebalance_proposal_*_diff.csv"))
        if not cands:
            return {}
        f = pd.read_csv(cands[-1])
        ch = f[f["구분"] != "유지"]
        return {"리밸제안": int(len(ch)), "_리밸파일": cands[-1].name}
    d.update(_safe("rebalance_proposal", _reb, {}) or {})

    d["생성"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 데이터 신선도 — 자동 실행 체인이 끊기면 이 리포트는 조용히 어제 숫자를
    # 계속 보여준다. 사람이 매일 들여다보지 않아도 알아채도록 크게 표시한다.
    # (D:\data\_live는 JVS_Daily 20:00이 갱신하고 이 레포는 21:00에 읽는다.
    #  JVS가 주중만 돌므로 주말·공휴일에 뒤처지는 것은 정상이다.)
    d["_신선도"] = _freshness(d.get("기준일"))
    return d


def _freshness(basis: str | None) -> dict:
    """기준일이 오늘로부터 며칠 전인지 + 그게 정상인지 판정."""
    if not basis:
        return {"등급": "unknown", "말": "데이터 기준일을 읽지 못했다"}
    b = dt.date.fromisoformat(basis)
    today = dt.date.today()
    gap = (today - b).days
    # 그 사이의 영업일 수(주말 제외 근사 — 공휴일은 세지 않으므로 보수적)
    bdays = sum(1 for i in range(1, gap + 1)
                if (b + dt.timedelta(days=i)).weekday() < 5)
    if bdays <= 1:
        return {"등급": "ok", "말": f"최신 ({gap}일 전 종가)"}
    if bdays == 2:
        return {"등급": "warn",
                "말": f"{gap}일 전 데이터 — 갱신이 하루 밀렸을 수 있다"}
    return {"등급": "bad",
            "말": f"{gap}일 전 데이터 (영업일 {bdays}일 경과) — "
                  "자동 갱신이 멈췄을 가능성이 높다. JVS_Daily 20:00 실행 여부 확인"}


# ── 이력 (전일 대비용) ──────────────────────────────────────────────────
COLS = ["기준일", "지수", "일간(%)", "MDD(%)", "갭12.5y(bp)", "용량(억)",
        "CU(억)", "CU괴리(bp)", "순도(%)", "복제100bp(만원)", "경보", "미검사"]


def update_history(d: dict) -> pd.DataFrame:
    """기준일 기준으로 한 줄 누적. 같은 날 재실행이면 덮어쓴다."""
    row = {c: d.get(c) for c in COLS}
    if HISTORY.exists():
        h = pd.read_csv(HISTORY, encoding="utf-8-sig")
        for c in COLS:                      # 스키마가 늘어나도 깨지지 않게
            if c not in h.columns:
                h[c] = None
        h = h[h["기준일"] != row["기준일"]]
    else:
        h = pd.DataFrame(columns=COLS)
    new = pd.DataFrame([row])
    # 빈 이력과 concat하면 dtype 추론 경고가 난다 — 첫 행은 그대로 쓴다
    h = new if h.empty else pd.concat([h[COLS], new], ignore_index=True)
    h = h.sort_values("기준일").reset_index(drop=True)
    h.to_csv(HISTORY, index=False, encoding="utf-8-sig")
    return h


def delta(h: pd.DataFrame, col: str) -> str:
    """전일 대비 변화 문자열. 비교 불가면 빈 문자열."""
    if len(h) < 2 or col not in h.columns:
        return ""
    try:
        cur, prev = float(h[col].iloc[-1]), float(h[col].iloc[-2])
    except (TypeError, ValueError):
        return ""
    if pd.isna(cur) or pd.isna(prev) or cur == prev:
        return '<span class="flat">—</span>'
    diff = cur - prev
    cls = "up" if diff > 0 else "down"
    arrow = "▲" if diff > 0 else "▼"
    fmt = f"{abs(diff):,.1f}" if abs(diff) < 100 else f"{abs(diff):,.0f}"
    return f'<span class="{cls}">{arrow} {fmt}</span>'


# ── HTML ────────────────────────────────────────────────────────────────
CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1a1a;--dim:#666;--line:#e3e7ee;
      --navy:#12213f;--red:#b3261e;--green:#1e7b45;--amber:#b4530a}
@media(prefers-color-scheme:dark){:root{--bg:#14161a;--card:#1c1f26;--ink:#e8eaed;
      --dim:#9aa0a6;--line:#2c313a;--navy:#8fa8d8}}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--ink);
     font-family:"Malgun Gothic","Segoe UI",system-ui,sans-serif;line-height:1.6}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px;color:var(--navy)}
.sub{color:var(--dim);font-size:13px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
      padding:16px 18px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .lab{font-size:12px;color:var(--dim)}
.kpi .val{font-size:21px;font-weight:700;margin-top:2px}
.kpi .dlt{font-size:12px;margin-top:2px}
.up{color:var(--green)}.down{color:var(--red)}.flat{color:var(--dim)}
h2{font-size:14px;margin:0 0 10px;color:var(--navy)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--dim);font-weight:600;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;font-weight:600}
.ok{background:rgba(30,123,69,.14);color:var(--green)}
.warn{background:rgba(180,83,10,.14);color:var(--amber)}
.bad{background:rgba(179,38,30,.14);color:var(--red)}
.note{font-size:12px;color:var(--dim);margin-top:10px}
.scroll{overflow-x:auto}
"""


def kpi(lab: str, val, dlt: str = "", unit: str = "") -> str:
    v = "—" if val is None or (isinstance(val, float) and pd.isna(val)) \
        else f"{val:,}{unit}" if isinstance(val, (int, float)) else str(val)
    return (f'<div class="kpi"><div class="lab">{html.escape(lab)}</div>'
            f'<div class="val">{v}</div><div class="dlt">{dlt}</div></div>')


def build_html(d: dict, h: pd.DataFrame) -> str:
    n_bad, n_unk = d.get("경보"), d.get("미검사")
    if n_bad is None:
        status = '<span class="badge warn">건강 리포트 없음</span>'
    elif n_bad:
        status = f'<span class="badge bad">경보 {n_bad}건</span>'
    else:
        status = '<span class="badge ok">이상 없음</span>'
    if n_unk:
        status += f' <span class="badge warn">미검사 {n_unk}</span>'

    fr = d.get("_신선도") or {"등급": "unknown", "말": ""}
    fcls = {"ok": "ok", "warn": "warn"}.get(fr["등급"], "bad")
    fresh = f'<span class="badge {fcls}">{html.escape(fr["말"])}</span>'
    stale_banner = "" if fr["등급"] == "ok" else (
        f'<div class="card" style="border-color:var(--amber)">'
        f'<h2>⚠ 데이터 신선도</h2><div>{html.escape(fr["말"])}</div>'
        f'<div class="note">아래 숫자는 <b>{html.escape(str(d.get("기준일")))}</b> '
        "종가 기준이다. 자동 갱신 순서: JVS_Daily 20:00이 D:\\data\\_live를 "
        "갱신하고 이 리포트는 21:00에 읽는다(주말·공휴일에 뒤처지는 것은 정상).</div>"
        "</div>")

    kpis = "".join([
        kpi("지수", d.get("지수"), delta(h, "지수")),
        kpi("일간", d.get("일간(%)"), "", "%"),
        kpi("최대낙폭", d.get("MDD(%)"), "", "%"),
        kpi("HBM 순도", d.get("순도(%)"), delta(h, "순도(%)"), "%"),
        kpi("용량(정규장)", d.get("용량(억)"), delta(h, "용량(억)"), "억"),
        kpi("추적오차 12.5y", d.get("갭12.5y(bp)"), delta(h, "갭12.5y(bp)"), "bp"),
        kpi("권장 CU", d.get("CU(억)"), delta(h, "CU(억)"), "억"),
        kpi("개인복제 100bp", d.get("복제100bp(만원)"),
            delta(h, "복제100bp(만원)"), "만원"),
    ])

    rows = ""
    for name, role, alert in d.get("_경보목록", []):
        rows += (f"<tr><td>{html.escape(str(name))}</td>"
                 f"<td>{html.escape(str(role))}</td>"
                 f"<td>{html.escape(str(alert))}</td></tr>")
    alerts_tbl = (f"<table><tr><th>종목</th><th>구분</th><th>경보</th></tr>{rows}</table>"
                  if rows else '<div class="note">경보 없음</div>')
    unk = d.get("_미검사목록") or []
    if unk:
        alerts_tbl += (f'<div class="note">❔ 미검사: {html.escape(", ".join(map(str, unk)))}'
                       " — 해외 편입분은 국내 재무·가격 패널 밖이라 검사 자체가 안 된다."
                       " '이상 없음'이 아니다.</div>")

    hist = h.tail(10).iloc[::-1]
    hcols = ["기준일", "지수", "일간(%)", "순도(%)", "용량(억)", "CU(억)", "경보"]
    hh = "".join(f"<th>{html.escape(c)}</th>" for c in hcols)
    hr = ""
    for _, r in hist.iterrows():
        tds = ""
        for c in hcols:
            v = r.get(c)
            txt = "—" if pd.isna(v) else (f"{v:,.1f}" if isinstance(v, float)
                                          else str(v))
            cls = ' class="num"' if c != "기준일" else ""
            tds += f"<td{cls}>{html.escape(txt)}</td>"
        hr += f"<tr>{tds}</tr>"

    reb = d.get("리밸제안")
    reb_html = ""
    if reb is not None:
        cls = "warn" if reb else "ok"
        txt = f"변경 제안 {reb}건" if reb else "변경 제안 없음 (현행 유지)"
        reb_html = (f'<div class="card"><h2>리밸런싱 제안</h2>'
                    f'<span class="badge {cls}">{txt}</span>'
                    f'<div class="note">제안일 뿐 정본이 아니다 — 승인해야 반영된다.'
                    f' 파일: {html.escape(str(d.get("_리밸파일", "")))}</div></div>')

    miss = (f'<div class="card"><h2>읽지 못한 항목</h2><div class="note">'
            + html.escape(" · ".join(_missing))
            + "</div></div>") if _missing else ""

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JGHBM 일일 리포트 {d.get('기준일') or ''}</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>정가 HBM ETF — 일일 리포트</h1>
<div class="sub">데이터 기준일 <b>{d.get('기준일') or '—'}</b> {fresh} ·
 생성 {d.get('생성')} · {status}</div>
{stale_banner}
<div class="grid">{kpis}</div>
<div class="card"><h2>상장요건</h2>
 <div>{html.escape(str(d.get('상장요건') or '—'))}</div></div>
<div class="card"><h2>재무 건강 경보</h2>{alerts_tbl}</div>
{reb_html}
<div class="card"><h2>최근 10일 추이</h2><div class="scroll">
 <table><tr>{hh}</tr>{hr}</table></div>
 <div class="note">변화 화살표는 전일 대비다. CU·복제금액은 정수 주 격자라
 가격이 조금만 움직여도 답이 튄다 — 자릿수로 읽을 것.</div></div>
<div class="note">수익률은 성과 주장에 쓰지 않는다(소급 구성이라 look-ahead 존재).
 믿을 수 있는 것은 낙폭·용량·드래그다. 상세는 etf/output/*.csv 참조.</div>
</div></body></html>"""


def main() -> int:
    if not OUT.exists():
        print(f"산출 폴더 없음: {OUT} — run_all.py를 먼저 실행하십시오")
        return 1
    d = collect()
    h = update_history(d)
    REPORT.write_text(build_html(d, h), encoding="utf-8")
    print(f"일일 리포트 → {REPORT}")
    print(f"  기준일 {d.get('기준일')} · 경보 {d.get('경보')}건 · "
          f"이력 {len(h)}일치 ({HISTORY.name})")
    if _missing:
        print(f"  ⚠ 읽지 못한 항목: {' · '.join(_missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
