#!/usr/bin/env python3
"""씽크풀 라씨 매매신호 → Supabase 수집기.

  poll                       오늘의 매수/매도 신호 (3 request). 20분마다.
  backfill [--full] [code…]  TR_SIGNAL07 매매이력. 코드 생략 시 오늘 목록.
  check                      네트워크 없이 행 변환 로직 자체검증.
"""
import json, os, ssl, sys, urllib.request

try:                                    # ponytail: macOS 시스템 파이썬은 루트 CA가 없다
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

API = "https://api.thinkpool.com"
RASSI = "https://rassiapp.thinkpool.com:47700/rassi_ext"
H = {"Origin": "https://www.thinkpool.com", "User-Agent": "Mozilla/5.0",
     "Content-Type": "application/json", "Accept": "application/json"}


def req(url, body=None, headers=H):
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers=headers),
            timeout=30, context=CTX) as f:
        raw = f.read()
    return json.loads(raw) if raw else None      # rassi는 content-type이 text/html이라 무조건 JSON 파싱


def tr(code, **body):
    r = req(f"{RASSI}/{code}", {"userId": "TP_WEB", **body})
    if r["retCode"] != "0000":
        raise RuntimeError(f'{code}: {r["retCode"]} {r["retMsg"]}')
    return r["retData"]


def upsert(rows):
    """PostgREST merge-duplicates는 payload에 있는 컬럼만 갱신한다.
    그래서 backfill이 trade_time 키를 빼면 폴링이 넣어둔 시각이 보존된다."""
    if not rows:
        return 0
    key = os.environ["SUPABASE_KEY"]
    req(f'{os.environ["SUPABASE_URL"].rstrip("/")}/rest/v1/signal'
        f'?on_conflict=stock_code,trade_date,trade_flag', rows,
        {"Content-Type": "application/json", "apikey": key,
         "Authorization": f"Bearer {key}",
         "Prefer": "resolution=merge-duplicates,return=minimal"})
    return len(rows)


def _d(yyyymmdd):
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def live_row(flag, item, live):
    """todayItemList 항목 + TR_SIGNAL21 현재상태 → 원장 행."""
    dt = item["tradeDttm"]                       # yyyymmddHHMMSS
    d = live.get(item["stockCode"], {})
    # TR_SIGNAL21은 그 종목의 '최신' 신호만 준다. 이 행과 시각이 다르면
    # 다른 신호의 가격이므로 쓰지 않고 backfill이 채우게 둔다.
    ok = d.get("tradeDate", "") + d.get("tradeTime", "") == dt[:14]
    return {"stock_code": item["stockCode"], "stock_name": item["stockName"],
            "trade_date": _d(dt), "trade_flag": flag,
            "trade_time": f"{dt[8:10]}:{dt[10:12]}:{dt[12:14]}",
            "trade_price": int(d["tradePrice"]) if ok else None,
            "profit_rate": float(d["profitRate"]) if ok and flag == "S" else None}


def hist_row(head, r):
    """TR_SIGNAL07 list_SigChart 항목 → 원장 행. trade_time 키 없음(보존)."""
    return {"stock_code": head["stockCode"], "stock_name": head["stockName"],
            "trade_date": _d(r["td"]), "trade_flag": r["tf"],
            "trade_price": int(r["tp"]),
            "profit_rate": float(r["pr"]) if r.get("pr") else None}


def today_codes():
    out = []
    for flag in "BS":
        out += [(flag, x) for x in req(f"{API}/signal/{flag}/todayItemList")]
    return out


def poll():
    items = today_codes()
    if not items:
        return 0
    codes = sorted({x["stockCode"] for _, x in items})
    live = {d["stockCode"]: d for d in tr("TR_SIGNAL21", list_Stock=codes)}
    return upsert([live_row(f, x, live) for f, x in items])


def backfill(codes, full=False):
    rows = []
    for c in codes:
        page = 0
        while True:
            head = tr("TR_SIGNAL07", stockCode=c, pageNo=page, pageItemSize=50)
            chart = head.get("list_SigChart") or []
            rows += [hist_row(head, r) for r in chart]
            if not full or not chart or page + 1 >= int(chart[0]["totalPageSize"]):
                break
            page += 1
    return upsert(rows)


def check():
    live = {"457190": {"stockCode": "457190", "tradeDate": "20260831",
                       "tradeTime": "142000", "tradePrice": "69450", "profitRate": "-0.79"}}
    item = {"stockCode": "457190", "stockName": "이수스페셜티케미컬", "tradeDttm": "20260831142000"}
    r = live_row("B", item, live)
    assert r["trade_date"] == "2026-08-31" and r["trade_time"] == "14:20:00", r
    assert r["trade_price"] == 69450 and r["profit_rate"] is None, r   # B행에 평가수익률 금지
    assert live_row("S", item, live)["profit_rate"] == -0.79           # S행만 실현수익률
    stale = dict(item, tradeDttm="20260830093000")                     # 시각 불일치 → 가격 폐기
    assert live_row("B", stale, live)["trade_price"] is None
    h = hist_row({"stockCode": "465480", "stockName": "인스피언"},
                 {"tf": "S", "td": "20260831", "tp": "3455", "pr": "22.74"})
    assert "trade_time" not in h and h["profit_rate"] == 22.74, h
    assert hist_row({"stockCode": "1", "stockName": "x"},
                    {"tf": "B", "td": "20260731", "tp": "2815"})["profit_rate"] is None
    print("check ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "poll"
    args = sys.argv[2:]
    if cmd == "check":
        check()
    elif cmd == "poll":
        print("upserted", poll())
    elif cmd == "backfill":
        codes = [a for a in args if not a.startswith("--")]
        print("upserted", backfill(codes or sorted({x["stockCode"] for _, x in today_codes()}),
                                   full="--full" in args))
    else:
        sys.exit(__doc__)
