#!/usr/bin/env python3
"""씽크풀 라씨 매매신호 → Supabase 수집기.

  poll                       오늘의 매수/매도 신호 (3 request). 20분마다.
  backfill [code…]           TR_SIGNAL07 매매이력 전량. 코드 생략 시 오늘 목록.
  news [code…]               오늘 신호 종목의 최근 뉴스 (Google News RSS).
  news_backfill YYYY-MM…     해당 월의 신호 종목 뉴스를 월 단위로 소급 수집.
  fund [code…]               오늘 신호 종목의 펀더멘탈 (토스증권). 하루 1행 스냅샷.
  flow [code…]               개인·외국인·기관 순매매 120일치 (토스증권).
  flow_backfill [N] [code…]  수급을 N페이지까지 소급. 1페이지 ≈ 120거래일.
  price [code…]              일별 시세 1페이지(약 15개월). 토스 c-chart.
  price_backfill [N] [code…] 일별 시세를 N페이지까지 소급. 1페이지 ≈ 300거래일.
  fin [code…]                분기 매출·순이익·영업이익 5년치 (토스증권).
  check                      네트워크 없이 행 변환 로직 자체검증.
"""
import hashlib, json, os, re, ssl, sys, time, urllib.error, urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

try:                                    # ponytail: macOS 시스템 파이썬은 루트 CA가 없다
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

API = "https://api.thinkpool.com"
GNEWS = "https://news.google.com/rss/search"
TOSS = "https://wts-info-api.tossinvest.com/api"
RASSI = "https://rassiapp.thinkpool.com:47700/rassi_ext"
H = {"Origin": "https://www.thinkpool.com", "User-Agent": "Mozilla/5.0",
     "Content-Type": "application/json", "Accept": "application/json"}


def req(url, body=None, headers=H, tries=3, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, data=data, headers=headers),
                    timeout=30, context=CTX) as f:
                body_bytes = f.read()
            if raw:                                        # RSS(XML) 등 비-JSON 응답
                return body_bytes
            return json.loads(body_bytes) if body_bytes else None  # rassi는 content-type이 text/html이라 무조건 JSON 파싱
        except urllib.error.HTTPError as e:          # 4xx/5xx는 재시도해도 같다
            # PostgREST 는 본문에 message/details/hint 를 적어 보낸다. 그걸 버리면
            # "HTTP Error 400: Bad Request" 만 남아 원인을 못 찾는다.
            try:
                detail = e.read()[:800].decode("utf-8", "replace")
            except Exception:
                detail = ""
            raise urllib.error.HTTPError(
                e.url, e.code, f"{e.reason} — {detail}", e.headers, None) from None
        except (urllib.error.URLError, TimeoutError):
            # thinkpool이 해외(GitHub 러너) 접속에서 간헐 타임아웃을 낸다
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def tr(code, **body):
    r = req(f"{RASSI}/{code}", {"userId": "TP_WEB", **body})
    if r["retCode"] != "0000":
        raise RuntimeError(f'{code}: {r["retCode"]} {r["retMsg"]}')
    return r["retData"]


def _sb_headers(**extra):
    key = os.environ["SUPABASE_KEY"]
    h = {"Content-Type": "application/json", "apikey": key, **extra}
    if key.startswith("eyJ"):
        # 레거시 service_role은 JWT라 Bearer로도 보낸다. 신형 sb_secret_ 키는
        # Bearer에 실으면 JWT 파싱을 시도하다 Invalid JWT로 거절당한다.
        h["Authorization"] = f"Bearer {key}"
    return h


def sb_get(path):
    return req(f'{os.environ["SUPABASE_URL"].rstrip("/")}/rest/v1/{path}', headers=_sb_headers())


def _finite(rows):
    """NaN/Infinity 를 지운다.

    json.loads 는 NaN·Infinity 리터럴을 float 로 받아들이고 json.dumps 는 그걸
    그대로 내보내는데, 표준 JSON 이 아니라서 PostgREST 가 400 을 낸다.
    실적 증감률처럼 전분기가 0 근처면 API 가 이런 값을 준다."""
    for r in rows:
        for k, v in r.items():
            if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                r[k] = None
    return rows


def upsert(rows, table="signal", on_conflict="stock_code,trade_date,trade_flag"):
    """PostgREST merge-duplicates는 payload에 있는 컬럼만 갱신한다.
    그래서 backfill이 trade_time 키를 빼면 폴링이 넣어둔 시각이 보존된다."""
    if not rows:
        return 0
    rows = _finite(rows)
    h = _sb_headers(Prefer="resolution=merge-duplicates,return=minimal")
    total = 0
    for i in range(0, len(rows), 500):
        req(f'{os.environ["SUPABASE_URL"].rstrip("/")}/rest/v1/{table}'
            f'?on_conflict={on_conflict}', rows[i:i + 500], h)
        total += len(rows[i:i + 500])
    return total


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


def hist_row(code, name, r):
    """TR_SIGNAL07 list_SigChart 항목 → 원장 행. trade_time 키 없음(보존)."""
    return {"stock_code": code, "stock_name": name,
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
        return {"signals": 0, "fundamentals": 0}
    codes = sorted({x["stockCode"] for _, x in items})
    # TR_SIGNAL21은 배열 100개가 상한이다. 넘기면 retCode 0206으로 통째로 실패한다
    live = {}
    for i in range(0, len(codes), 100):
        live.update({d["stockCode"]: d
                     for d in tr("TR_SIGNAL21", list_Stock=codes[i:i + 100])})
    n = upsert([live_row(f, x, live) for f, x in items])
    # 미청산 보유 종목도 포함한다. 오늘 신호에 없다고 빼면 어제 산 종목의
    # 현재가·수급이 비어 추적 화면이 깨진다.
    try:
        codes = sorted(set(codes) | {r["stock_code"] for r in
                       sb_get("open_position?select=stock_code&limit=2000")})
    except Exception as e:
        print(f"open_position skipped: {e}", file=sys.stderr)
    # 펀더멘탈·수급은 하루 1행이면 충분하다. 아직 없는 종목만 채우면
    # 그날 첫 폴링이 전부 긁고 이후엔 신규 편입분만 몇 건 붙는다.
    out = {"signals": n}
    for name, fn, missing in (("fundamentals", fund, missing_today("fundamental", "as_of")),
                              ("flows", flow, missing_today("flow", "trade_date"))):
        try:
            out[name] = fn([c for c in codes if c in missing])
        except Exception as e:
            out[name] = 0        # 신호 적재가 우선. 토스 장애로 폴링이 죽으면 안 된다
            print(f"{name} skipped: {e}", file=sys.stderr)
    return out


def missing_today(table, date_col):
    """오늘자 행이 이미 있는 종목 집합의 여집합을 위해, 있는 쪽을 돌려준다."""
    day = time.strftime("%Y-%m-%d")
    have = {r["stock_code"] for r in
            sb_get(f"{table}?select=stock_code&{date_col}=eq.{day}&limit=5000")}
    return _NotIn(have)


class _NotIn:
    """`c in missing` 이 '아직 없다'는 뜻이 되도록 뒤집는 얇은 래퍼."""
    def __init__(self, have):
        self.have = have

    def __contains__(self, code):
        return code not in self.have


def backfill(codes):
    """종목별 매매이력 전량. 페이지 0만 받으면 새 종목의 진입 매수가 잘려
    라운드 짝짓기가 깨진다(§6). 서울 리전에선 전 페이지도 수십 초라 항상 전량."""
    rows = []
    for c in codes:
        page, name = 0, None
        while True:
            head = tr("TR_SIGNAL07", stockCode=c, pageNo=page, pageItemSize=50)
            chart = head.get("list_SigChart") or []
            # 일부 종목(예: 0117P0)은 TR_SIGNAL07에 stockName이 없다 → REST로 보충
            name = name or head.get("stockName") \
                or req(f"{API}/common/codename/{c}")["stockName"]
            rows += [hist_row(c, name, r) for r in chart]
            if not chart or page + 1 >= int(chart[0]["totalPageSize"]):
                break
            page += 1
    return upsert(rows)


def news_rows(code, name, xml):
    """Google News RSS → news 행. 요약 텍스트는 RSS가 안 준다(제목만)."""
    rows = []
    for it in ET.fromstring(xml).findall(".//item"):
        guid, title = it.findtext("guid"), it.findtext("title")
        pub = it.findtext("pubDate")
        if not (guid and title and pub):
            continue
        src = it.find("source")
        rows.append({
            "stock_code": code, "guid_hash": hashlib.md5(guid.encode()).hexdigest(),
            # RFC 822 (예: "Tue, 01 Sep 2026 01:37:34 GMT")
            "published_at": datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z")
                            .replace(tzinfo=timezone.utc).isoformat(),
            "title": title, "source": src.text if src is not None else None,
            "url": it.findtext("link") or "",
        })
    return rows


def fetch_news(name, code, window=None):
    """window = (after, before) 'YYYY-MM-DD'. 없으면 최신 100건.
    RSS는 100건 하드캡이고 start/num을 무시한다 → 날짜창을 쪼개서 소급한다.

    종목코드를 반드시 함께 넣는다. 종목명만 쓰면 동명이인이 섞인다 —
    '서연'(007860)으로 검색하면 아이돌 기사 100건이 통째로 들어왔다.
    재현율은 줄지만(삼호개발 100→24건) 틀린 근거보다 적은 근거가 낫다."""
    q = f"{name} {code}"
    if window:
        q += f" after:{window[0]} before:{window[1]}"
    url = f"{GNEWS}?q={urllib.parse.quote(q)}&hl=ko&gl=KR&ceid=KR:ko"
    return req(url, headers={"User-Agent": H["User-Agent"]}, raw=True)


def news(codes_names):
    rows = []
    for code, name in codes_names:
        rows += news_rows(code, name, fetch_news(name, code))
        time.sleep(0.3)                      # ponytail: 구글에 대한 최소한의 예의
    return upsert(rows, "news", "stock_code,guid_hash")


def news_backfill(codes_names, months):
    """월 단위 창으로 소급. RSS 100건 캡을 날짜로 우회한다."""
    rows = []
    for ym in months:
        y, m = map(int, ym.split("-"))
        after = f"{y}-{m:02d}-01"
        before = f"{y + (m == 12)}-{(m % 12) + 1:02d}-01"
        for code, name in codes_names:
            rows += news_rows(code, name, fetch_news(name, code, (after, before)))
            time.sleep(0.3)
    return upsert(rows, "news", "stock_code,guid_hash")


def _dig(sections, name, key):
    for sec in sections:
        if sec.get("sectionName") == name:
            return (sec.get("data") or {}).get(key)
    return None


def _num(v):
    """'12.1배' / '17.7%' / 12.1 → float. 값이 없으면 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = v.replace("배", "").replace("%", "").replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def fund_row(code, today):
    """토스 3개 엔드포인트 → fundamental 한 행. 종목코드는 'A' 접두."""
    a = "A" + code
    ind = req(f"{TOSS}/v1/stock-detail/ui/wts/{a}/investment-indicators",
              headers={"User-Agent": H["User-Agent"]})["result"]["indicatorSections"]
    ov = req(f"{TOSS}/v2/stock-infos/{a}/overview",
             headers={"User-Agent": H["User-Agent"]})["result"]
    pr = req(f"{TOSS}/v3/stock-prices/details?productCodes={a}",
             headers={"User-Agent": H["User-Agent"]})["result"][0]
    try:
        mix = req(f"{TOSS}/v1/companies/{code}/sales-compositions",
                  headers={"User-Agent": H["User-Agent"]})["result"]["compositions"]
        mix = [{"business": m.get("business"), "ratio": m.get("ratio")} for m in mix]
    except Exception:
        mix = None                       # ETF 등 매출 구성이 없는 종목
    co = ov.get("company") or {}
    return {
        "stock_code": code, "as_of": today,
        "per": _num(_dig(ind, "가치평가", "displayPer")),
        "pbr": _num(_dig(ind, "가치평가", "displayPbr")),
        "psr": _num(_dig(ind, "가치평가", "displayPsr")),
        "roe": _num(_dig(ind, "수익", "roe")),
        "eps": _num(_dig(ind, "수익", "eps")),
        "bps": _num(_dig(ind, "수익", "bps")),
        "div_yield": _num(_dig(ind, "배당", "dividendYieldRatio")),
        "market_cap": pr.get("marketCap"), "close_price": pr.get("close"),
        "high_52w": pr.get("high52w"), "low_52w": pr.get("low52w"),
        "market": ((ov.get("market") or {}).get("displayName")),
        "industry": (co.get("industry") or {}).get("displayName"),
        "ceo": co.get("ceo"), "listed_on": co.get("listDate"),
        "shares_out": co.get("sharesOutstanding"), "sales_mix": mix,
    }


def fund(codes):
    today = time.strftime("%Y-%m-%d")
    rows, fail = [], []
    for c in codes:
        try:
            rows.append(fund_row(c, today))
        except Exception as e:
            fail.append((c, str(e)[:60]))   # 신규상장·ETF는 지표가 없을 수 있다
        time.sleep(0.2)
    if fail:
        print(f"  건너뜀 {len(fail)}종목: {fail[:3]}", file=sys.stderr)
    return upsert(rows, "fundamental", "stock_code,as_of")


def flow_rows(code, body):
    """토스 trading-trend → flow 행.
    네이버(frgn)도 같은 데이터를 주지만 하루 늦고 20일치뿐이라 토스를 쓴다.
    당일치는 장마감 직후 잠정값이고 20시경 확정된다 → src_updated_at 로 판단."""
    out = []
    for x in body:
        base, close = x.get("base"), x.get("close")
        out.append({
            "stock_code": code, "trade_date": x["baseDate"],
            "close_price": close,
            "change_rate": round(100.0 * (close - base) / base, 2) if base and close else None,
            "volume": (x.get("individualsBuyVolume") or 0) + (x.get("foreignerBuyVolume") or 0)
                      + (x.get("institutionBuyVolume") or 0),
            "indiv_net": x.get("netIndividualsBuyVolume"),
            "foreign_net": x.get("netForeignerBuyVolume"),
            "inst_net": x.get("netInstitutionBuyVolume"),
            # 기관 세부 7주체. 금융투자+투신+사모+보험+은행+기타금융+연기금 = inst_net (실측 일치)
            "fin_inv_net": x.get("netFinancialInvestmentBuyVolume"),
            "insurance_net": x.get("netInsuranceBuyVolume"),
            "trust_net": x.get("netTrustBuyVolume"),
            "pe_fund_net": x.get("netPrivateEquityFundBuyVolume"),
            "bank_net": x.get("netBankBuyVolume"),
            "other_fin_net": x.get("netOtherFinancialInstitutionsBuyVolume"),
            "pension_net": x.get("netPensionFundBuyVolume"),
            "other_corp_net": x.get("netOtherCorporationBuyVolume"),   # 기관 합계엔 미포함
            "foreign_buy": x.get("foreignerBuyVolume"),
            "foreign_sell": x.get("foreignerSellVolume"),
            "foreign_hold": x.get("foreignerHoldingVolume"),
            "foreign_limit": x.get("foreignerLimitVolume"),
            "foreign_rate": x.get("foreignerRatio"),
            "src_updated_at": x.get("updatedAt"),
        })
    return out


def flow(codes, size=120, pages=1):
    """투자자별 매매동향. size 상한은 121~299 사이다(120 OK, 300부터 400 — 실측).

    한 번에 다 안 온다. 응답의 pagingParam 을 **평평하게** 쿼리에 되돌려주면
    그 이전 구간이 온다. {"number":2,"size":120,"key":"2026-03-09"} 를
    number=2&size=120&key=2026-03-09 로 붙이는 식이다. JSON 통째로나
    pagingParam.key 같은 점 표기는 무시당한다. lastPage 로 끝을 판단한다.
    1페이지 ≈ 120거래일 ≈ 5.7개월."""
    rows, fail = [], []
    for c in codes:
        q = f"productCode=A{c}&size={size}"
        try:
            for _ in range(pages):
                r = req(f"{TOSS}/v1/stock-infos/trade/trend/trading-trend?{q}",
                        headers={"User-Agent": H["User-Agent"]})["result"]
                body = r.get("body") or []
                rows += flow_rows(c, body)
                pp = r.get("pagingParam")
                if not body or r.get("lastPage") or not pp:
                    break
                q = f"productCode=A{c}&" + urllib.parse.urlencode(pp)
                time.sleep(0.2)
        except Exception as e:
            fail.append((c, str(e)[:50]))
        time.sleep(0.2)
    if fail:
        print(f"  건너뜀 {len(fail)}: {fail[:3]}", file=sys.stderr)
    return upsert(rows, "flow", "stock_code,trade_date")


def price_rows(code, candles):
    """c-chart 캔들 → price 행. 한 건이
    {dt, base, open, high, low, close, volume, amount} 로 온다(실측)."""
    return [{"stock_code": code, "trade_date": c["dt"][:10],
             "open_price": c.get("open"), "high_price": c.get("high"),
             "low_price": c.get("low"), "close_price": c.get("close"),
             "base_price": c.get("base"),          # 기준가(전일 종가)
             "volume": c.get("volume"), "amount": c.get("amount")}
            for c in candles if c.get("dt")]


def price(codes, pages=1, count=300):
    """일별 시세. 한 번에 다 안 온다 — count 상한이 300~499 사이고(300 OK, 500은 400),
    응답의 nextDateTime 을 ?from= 으로 되돌려줘야 그 이전 구간이 온다.
    pages 만큼 커서를 돌린다. 1페이지 ≈ 300거래일 ≈ 15개월."""
    rows, fail = [], []
    for c in codes:
        cur = None
        try:
            for _ in range(pages):
                q = f"count={count}"
                if cur:
                    q += "&from=" + urllib.parse.quote(cur)
                r = req(f"{TOSS}/v1/c-chart/kr-s/A{c}/day:1?{q}",
                        headers={"User-Agent": H["User-Agent"]})["result"]
                got = r.get("candles") or []
                rows += price_rows(c, got)
                cur = r.get("nextDateTime")
                if not got or not cur:            # 상장 시점까지 내려갔다
                    break
                time.sleep(0.2)
        except Exception as e:
            fail.append((c, str(e)[:50]))
        time.sleep(0.2)
    if fail:
        print(f"  건너뜀 {len(fail)}: {fail[:3]}", file=sys.stderr)
    return upsert(rows, "price", "stock_code,trade_date")


_OPI_KEYS_SEEN = []


def _operating(x):
    """영업이익 값. revenue-and-net-profit 은 필드명을 실측했지만
    operating-income 쪽은 아직 못 했다. 아는 이름을 먼저 보고, 없으면
    operating 이 들어간 숫자 필드를 집되 비율·성장률·환산액은 뺀다.
    처음 한 번 관측된 키를 찍어두면 다음 커밋에서 못 박을 수 있다."""
    for n in ("operatingIncome", "operatingProfit"):
        if isinstance(x.get(n), (int, float)):
            return x[n]
    if not _OPI_KEYS_SEEN:
        _OPI_KEYS_SEEN.append(sorted(x))
        print(f"  operating-income 키 미실측: {sorted(x)}", file=sys.stderr)
    for k, v in x.items():
        kl = k.lower()
        if (isinstance(v, (int, float)) and "operating" in kl
                and not any(a in kl for a in ("ratio", "growth", "krw", "jpy"))):
            return v
    return None


def _won(v):
    """금액 컬럼은 bigint 다. API 가 실수로 주면 캐스팅에서 400 이 난다."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    return int(v)


def _series(r):
    """분기 시계열. graph 와 table 을 period 로 합친다.

    ⚠️ table[] 은 range 와 무관하게 12개로 잘린다. {"range":5} 를 보내도
    table 은 12분기고 5년치는 graph[] 에 있다(실측: 97종목 전부 12분기 이하).
    대신 table 에만 netProfitGrowthRatio 가 있어서 둘 다 봐야 한다."""
    merged = {}
    for key in ("graph", "table"):
        for x in (r or {}).get(key) or []:
            p = x.get("period")
            if p:
                merged.setdefault(p, {}).update(x)
    return merged


def fin_rows(code, rev, opi):
    """분기 실적 → financials 행. period 로 합친다."""
    out = {}
    for p, x in _series(rev).items():
        out[p] = {"stock_code": code, "period": p,
                  "revenue": _won(x.get("revenue")),
                  "net_profit": _won(x.get("netProfit")),
                  "net_profit_ratio": x.get("netProfitRatio"),
                  "net_profit_growth": x.get("netProfitGrowthRatio")}
    for p, x in _series(opi).items():
        out.setdefault(p, {"stock_code": code, "period": p})
        out[p]["operating_income"] = _won(_operating(x))
    return list(out.values())


def fin(codes, years=5):
    """분기 매출·순이익·영업이익. 본문 {"range": 5} 로 5년(20분기)까지 온다.
    기본은 3년이라 반드시 실어 보내야 한다(실측)."""
    body = {"range": years}
    rows, fail = [], []
    hdr = {"User-Agent": H["User-Agent"], "Content-Type": "application/json"}
    for c in codes:
        try:
            rev = req(f"{TOSS}/v2/stock-infos/revenue-and-net-profit/A{c}",
                      body, headers=hdr)["result"]
            time.sleep(0.2)
            opi = req(f"{TOSS}/v2/stock-infos/operating-income/A{c}",
                      body, headers=hdr)["result"]
            rows += fin_rows(c, rev, opi)
        except Exception as e:
            fail.append((c, str(e)[:50]))
        time.sleep(0.2)
    if fail:
        print(f"  건너뜀 {len(fail)}: {fail[:3]}", file=sys.stderr)
    return upsert(rows, "financials", "stock_code,period")


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
    h = hist_row("465480", "인스피언",
                 {"tf": "S", "td": "20260831", "tp": "3455", "pr": "22.74"})
    assert "trade_time" not in h and h["profit_rate"] == 22.74, h
    assert hist_row("1", "x", {"tf": "B", "td": "20260731", "tp": "2815"})["profit_rate"] is None
    # TR_SIGNAL07이 stockName을 안 주는 종목이 있다(0117P0). 이름은 호출자가 넣는다
    assert hist_row("0117P0", "피스피스스튜디오",
                    {"tf": "S", "td": "20260901", "tp": "5570", "pr": "2.96"}
                    )["stock_name"] == "피스피스스튜디오"
    # 일별 시세 — 실측한 캔들 한 건 그대로
    pr = price_rows("005930", [{"dt": "2026-09-01T00:00:00+09:00", "base": 260000,
                                "open": 259500, "high": 262500, "low": 254000,
                                "close": 255000, "volume": 23436082,
                                "amount": 6069687118000}])[0]
    assert pr["trade_date"] == "2026-09-01" and pr["close_price"] == 255000, pr
    assert pr["base_price"] == 260000 and pr["amount"] == 6069687118000, pr
    assert not price_rows("x", [{"close": 1}])          # dt 없는 건 버린다
    # 분기 실적 — 매출·순이익은 실측 필드, 영업이익은 이름을 집어낸다
    # graph 가 길고(5년) table 이 12개뿐이며 성장률을 보탠다 — 합쳐야 전량이 나온다
    f = fin_rows("005930",
                 {"graph": [{"period": "2021-09", "revenue": 1, "netProfit": 2},
                            {"period": "2023-09", "revenue": 67404652000000,
                             "netProfit": 5844171000000, "netProfitRatio": 8.67}],
                  "table": [{"period": "2023-09", "revenue": 67404652000000,
                             "netProfit": 5844171000000, "netProfitRatio": 8.67,
                             "netProfitGrowthRatio": 239.07}]},
                 {"graph": [{"period": "2023-09", "operatingIncome": 2433500000000,
                             "operatingIncomeRatio": 3.61}]})
    by = {r["period"]: r for r in f}
    assert len(f) == 2 and by["2021-09"]["revenue"] == 1, f      # graph 만 있는 분기도 살린다
    assert by["2023-09"]["net_profit_growth"] == 239.07, f       # table 이 성장률을 보탠다
    assert by["2023-09"]["operating_income"] == 2433500000000, f  # 비율을 집으면 안 된다
    g = fin_rows("x", {"table": [{"period": "2024-03", "revenue": 1}]},
                 {"table": [{"period": "2024-03", "operatingIncomeKrw": 9,
                             "someOperatingValue": 7}]})     # 이름 미상 → 환산액은 제외
    assert g[0]["operating_income"] == 7, g
    # 금액은 bigint 다. 실수로 와도 정수로 눕히고, 못 쓸 값은 버린다
    assert _won(5844171000000.0) == 5844171000000 and _won(None) is None
    assert _won(float("nan")) is None and _won(True) is None and _won("1") is None
    nan, inf = float("nan"), float("inf")
    fx = _finite([{"a": nan, "b": inf, "c": -inf, "d": 1.5, "e": None, "f": "x"}])[0]
    assert fx == {"a": None, "b": None, "c": None, "d": 1.5, "e": None, "f": "x"}, fx
    print("check ok")


def event_codes(event):
    """람다 페이로드에서 대상 종목을 고른다.

    price_backfill 은 189종목 × 20페이지 ≈ 3,780요청 ≈ 19분이라 람다 하드
    상한(15분)을 넘는다. batches/batch 로 쪼개 여러 번 부른다. 균등하게
    나뉘도록 연속 구간이 아니라 stride 로 자른다.

      {"cmd":"price_backfill","batches":10,"batch":3,"pages":20}
      {"cmd":"fin","codes":["005930","000660"]}
    """
    ev = event or {}
    codes = sorted({x["stockCode"] for _, x in today_codes()})
    if ev.get("codes"):
        want = set(ev["codes"])
        return [c for c in codes if c in want]
    n = int(ev.get("batches", 1))
    return codes[int(ev.get("batch", 0)) % n::n] if n > 1 else codes


def lambda_handler(event, _context):
    # thinkpool이 해외 IP를 막아서 서울(ap-northeast-2)에서 돈다. §7 참고
    ev = event or {}
    cmd = ev.get("cmd", "poll")
    if cmd in ("backfill", "flow", "flow_backfill", "fund",
               "price", "price_backfill", "fin"):
        codes = event_codes(ev)
        if cmd == "flow_backfill":
            return {"cmd": cmd, "codes": len(codes),
                    "upserted": flow(codes, pages=int(ev.get("pages", 25)))}
        fn = {"backfill": backfill, "flow": flow, "fund": fund, "fin": fin}.get(cmd)
        if fn:
            return {"cmd": cmd, "codes": len(codes), "upserted": fn(codes)}
        pages = int(ev.get("pages", 20)) if cmd == "price_backfill" else 1
        return {"cmd": cmd, "codes": len(codes), "upserted": price(codes, pages=pages)}
    if cmd == "news":
        want = set(event_codes(ev))
        return {"cmd": cmd, "upserted": news(
            sorted({(x["stockCode"], x["stockName"]) for _, x in today_codes()
                    if x["stockCode"] in want}))}
    return {"cmd": cmd, **poll()}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "poll"
    args = sys.argv[2:]
    if cmd == "check":
        check()
    elif cmd == "poll":
        print("upserted", poll())
    elif cmd == "backfill":
        codes = [a for a in args if not a.startswith("--")]
        print("upserted", backfill(codes or sorted({x["stockCode"] for _, x in today_codes()})))
    elif cmd == "flow":
        codes = sorted({x["stockCode"] for _, x in today_codes()})
        print("upserted", flow([c for c in codes if not args or c in args]))
    elif cmd == "fund":
        codes = sorted({x["stockCode"] for _, x in today_codes()})
        print("upserted", fund([c for c in codes if not args or c in args]))
    elif cmd == "news":
        pairs = sorted({(x["stockCode"], x["stockName"]) for _, x in today_codes()})
        print("upserted", news([p for p in pairs if not args or p[0] in args]))
    elif cmd == "flow_backfill":
        pages = int(args[0]) if args and args[0].isdigit() else 25
        rest = [a for a in args[1:] if not a.startswith("--")]
        codes = sorted({x["stockCode"] for _, x in today_codes()})
        print("upserted", flow(rest or codes, pages=pages))
    elif cmd == "price":
        codes = sorted({x["stockCode"] for _, x in today_codes()})
        print("upserted", price([c for c in codes if not args or c in args]))
    elif cmd == "price_backfill":
        pages = int(args[0]) if args and args[0].isdigit() else 20
        rest = [a for a in args[1:] if not a.startswith("--")]
        codes = sorted({x["stockCode"] for _, x in today_codes()})
        print("upserted", price(rest or codes, pages=pages))
    elif cmd == "fin":
        codes = sorted({x["stockCode"] for _, x in today_codes()})
        print("upserted", fin([c for c in codes if not args or c in args]))
    elif cmd == "news_backfill":
        pairs = sorted({(x["stockCode"], x["stockName"]) for _, x in today_codes()})
        print("upserted", news_backfill(pairs, args or [time.strftime("%Y-%m")]))
    else:
        sys.exit(__doc__)
