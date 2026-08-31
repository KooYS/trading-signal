#!/usr/bin/env python3
"""docs/thinkpool-signal-api.md 의 주장을 라이브 호출로 검증한다.

의존성 없음(표준 라이브러리만). 네트워크가 열린 환경에서 실행할 것.

    python3 tools/verify_api.py                      # 전체
    python3 tools/verify_api.py --code 457190        # 기준 종목 지정
    python3 tools/verify_api.py --report out.json    # 원본 응답까지 저장
    python3 tools/verify_api.py --delay 0.8          # 호출 간격(기본 0.4s)
"""
import argparse, json, math, ssl, sys, time, urllib.error, urllib.request

API   = "https://api.thinkpool.com"
MAPI  = "https://m.thinkpool.com"
RASSI = "https://rassiapp.thinkpool.com:47700/rassi_ext"
UA    = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

DELAY = 0.4
CTX = None                    # --insecure 시 검증 생략 컨텍스트
REPORT = {"checks": [], "samples": {}}


# ---------- HTTP ----------------------------------------------------------

def http(url, body=None, headers=None, method=None):
    """(status, content_type, raw_text, error) 반환. 예외를 던지지 않는다."""
    h = {"User-Agent": UA, "Accept": "application/json",
         "Origin": "https://www.thinkpool.com"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    time.sleep(DELAY)
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode("utf-8", "replace"), None
    except Exception as e:
        return None, "", "", f"{type(e).__name__}: {e}"


def get_json(url):
    st, ct, raw, err = http(url)
    if err:
        return None, err, st, ct
    try:
        return json.loads(raw), None, st, ct
    except Exception as e:
        return None, f"JSON 파싱 실패: {e} / 본문 앞부분: {raw[:200]!r}", st, ct


def tr(code, body):
    """rassi_ext TR 호출. (envelope, err, status, content_type)"""
    st, ct, raw, err = http(f"{RASSI}/{code}", body=body)
    if err:
        return None, err, st, ct
    try:
        return json.loads(raw), None, st, ct
    except Exception as e:
        return None, f"JSON 파싱 실패: {e} / 본문 앞부분: {raw[:200]!r}", st, ct


# ---------- 결과 수집 ------------------------------------------------------

def record(name, ok, detail):
    tag = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
    print(f"[{tag}] {name}")
    for line in str(detail).splitlines():
        print(f"       {line}")
    REPORT["checks"].append({"name": name, "result": tag, "detail": str(detail)})


# ---------- 개별 검증 ------------------------------------------------------

def c_rest_anonymous():
    """§1: REST는 쿠키·토큰 없이 200 + 실데이터."""
    data, err, st, ct = get_json(f"{API}/signal/B/todayItemList")
    if err:
        return record("§1 REST 익명 접근 (B/todayItemList)", False, f"status={st} {err}")
    REPORT["samples"]["todayItemList_B"] = data[:5] if isinstance(data, list) else data
    ok = st == 200 and isinstance(data, list)
    record("§1 REST 익명 접근 (B/todayItemList)", ok,
           f"status={st} content-type={ct} 타입={type(data).__name__} 건수={len(data) if isinstance(data, list) else 'n/a'}")
    return data if isinstance(data, list) else None


def c_no_masking():
    """§1: 프리미엄 마스킹은 프론트엔드에만 → API는 실명 반환."""
    data, err, st, _ = get_json(f"{API}/signal/S/todayItemList")
    if err or not isinstance(data, list):
        return record("§1 매도 목록 마스킹 없음", False, f"status={st} {err}")
    REPORT["samples"]["todayItemList_S"] = data[:5]
    masked = [x.get("stockName") for x in data if "*" in str(x.get("stockName", ""))]
    record("§1 매도 목록 마스킹 없음", not masked,
           f"{len(data)}건 중 마스킹 {len(masked)}건" + (f" 예: {masked[:3]}" if masked else ""))


def c_trade_price_zero(buys):
    """§2-1 + §6: todayItemList.tradePrice 는 항상 0."""
    if not buys:
        return record("§2-1 todayItemList.tradePrice == 0", None, "매수 목록 없음(장 시작 전/휴장?)")
    nonzero = [(x.get("stockName"), x.get("tradePrice")) for x in buys if x.get("tradePrice")]
    record("§2-1 todayItemList.tradePrice == 0", not nonzero,
           f"{len(buys)}건 중 0이 아닌 건 {len(nonzero)}" + (f" 예: {nonzero[:3]}" if nonzero else ""))


def c_field_drift(buys):
    """문서에 적힌 필드 집합과 실제 응답 필드가 어긋나는지(문서 드리프트) 확인."""
    if not buys:
        return record("§2-1 필드 스키마 드리프트", None, "샘플 없음")
    documented = {"stockCode", "stockName", "tradeDttm", "tradeFlag",
                  "elapsedTmTx", "timeFlag", "tradePrice", "profitRate"}
    actual = set()
    for x in buys:
        actual |= set(x.keys())
    extra, missing = actual - documented, documented - actual
    record("§2-1 필드 스키마 드리프트", not (extra or missing),
           f"문서에 없는 필드={sorted(extra) or '없음'} / 문서에만 있는 필드={sorted(missing) or '없음'}")


def c_signal01(code):
    """§3-1: TR_SIGNAL01 이 매수가의 정답 엔드포인트."""
    env, err, st, ct = tr("TR_SIGNAL01", {"userId": "TP_WEB", "stockCode": code})
    if err:
        return record(f"§3-1 TR_SIGNAL01 ({code})", False, f"status={st} {err}"), None
    REPORT["samples"]["TR_SIGNAL01"] = env
    sig = (env.get("retData") or {}).get("struct_Signal") or {}
    ok = env.get("retCode") == "0000" and sig.get("tradePrice") not in (None, "", "0")
    record(f"§3-1 TR_SIGNAL01 ({code})", ok,
           f"retCode={env.get('retCode')} content-type={ct}\n"
           f"stockName={sig.get('stockName')} tradeFlag={sig.get('tradeFlag')} "
           f"tradePrice={sig.get('tradePrice')} profitSign={sig.get('profitSign')!r} "
           f"profitRate={sig.get('profitRate')!r} elapsedDays={sig.get('elapsedDays')}")
    return None, sig


def c_content_type_html():
    """§3 서두 + §6: rassi 응답 Content-Type 은 text/html 인데 본문은 JSON."""
    st, ct, raw, err = http(f"{RASSI}/TR_SIGNAL09", body={"userId": "TP_WEB"})
    if err:
        return record("§3 rassi Content-Type=text/html, 본문=JSON", False, f"{err}")
    parses = True
    try:
        json.loads(raw)
    except Exception:
        parses = False
    record("§3 rassi Content-Type=text/html, 본문=JSON", parses,
           f"status={st} content-type={ct!r} JSON파싱={'성공' if parses else '실패'}")


def c_error_codes():
    """§4 + §1: 인증 실패 코드는 없고 필드 검증만 한다."""
    cases = [
        ("userId 누락 → 0205", {"stockCode": "005930"}, "0205", None),
        ("잘못된 파라미터 → 0203", {"userId": "TP_WEB", "bogusField": "x"}, "0203", None),
    ]
    for label, body, expect, _ in cases:
        env, err, st, _ = tr("TR_SIGNAL01", body)
        if err:
            record(f"§4 {label}", False, f"status={st} {err}")
            continue
        got = env.get("retCode")
        record(f"§4 {label}", got == expect,
               f"HTTP={st} retCode={got} retMsg={env.get('retMsg')!r} (기대 {expect})")

    # form 전송 → 0999
    st, ct, raw, err = http(f"{RASSI}/TR_SIGNAL01",
                            body=b"userId=TP_WEB&stockCode=005930",
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
    detail = f"HTTP={st} 본문={raw[:160]!r}" if not err else str(err)
    got = None
    try:
        got = json.loads(raw).get("retCode")
    except Exception:
        pass
    record("§4 form 전송 → 0999", got == "0999", f"retCode={got} / {detail}")

    # 인증 실패(401/403)가 존재하지 않는다는 주장
    env, err, st, _ = tr("TR_SIGNAL01", {"userId": "NOT_TP_WEB", "stockCode": "005930"})
    if err:
        record("§1 임의 userId 도 통과(인증 게이트 없음)", False, str(err))
    else:
        record("§1 임의 userId 도 통과(인증 게이트 없음)", st not in (401, 403),
               f"HTTP={st} retCode={env.get('retCode')} retMsg={env.get('retMsg')!r} "
               f"→ {'인증검사 없음' if st not in (401,403) else '인증검사 존재!'}")


def c_signal07(code):
    """§3-3: 페이지네이션 산식, pr 은 매도행만, pr 값이 직전 매수가 대비 정확한가."""
    env, err, st, _ = tr("TR_SIGNAL07",
                         {"userId": "TP_WEB", "stockCode": code, "pageNo": 0, "pageItemSize": 10})
    if err:
        return record(f"§3-3 TR_SIGNAL07 ({code})", False, f"status={st} {err}")
    REPORT["samples"]["TR_SIGNAL07"] = env
    d = env.get("retData") or {}
    rows = d.get("list_SigChart") or []
    total, psize = d.get("totalItemSize"), d.get("totalPageSize")

    try:
        expect_pages = math.ceil(int(total) / 10)
        record("§3-3 totalPageSize = ceil(totalItemSize / pageItemSize)",
               int(psize) == expect_pages,
               f"totalItemSize={total} pageItemSize=10 totalPageSize={psize} (기대 {expect_pages})")
    except Exception as e:
        record("§3-3 totalPageSize 산식", False, f"계산 불가: total={total} psize={psize} ({e})")

    stray = [r for r in rows if r.get("tf") == "B" and r.get("pr") not in (None, "")]
    record("§3-3 pr 은 매도행에만 존재", not stray,
           f"매수행인데 pr 이 있는 건 {len(stray)}" + (f" 예: {stray[:2]}" if stray else ""))

    bad = []
    for i, r in enumerate(rows):
        if r.get("tf") != "S" or r.get("pr") in (None, ""):
            continue
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if not nxt or nxt.get("tf") != "B":
            continue
        try:
            calc = (float(r["tp"]) / float(nxt["tp"]) - 1) * 100
            if abs(calc - float(r["pr"])) > 0.05:
                bad.append(f"{nxt['td']}@{nxt['tp']} → {r['td']}@{r['tp']}: 응답 {r['pr']}% vs 계산 {calc:.2f}%")
        except Exception:
            pass
    record("§3-3 pr = 직전 매수가 대비 실현수익률", not bad,
           "\n".join(bad) if bad else "검사한 매도행 전부 일치")

    # tradeCount 와 totalItemSize 의 관계(문서엔 없음 — 관측치 기록)
    record("§3-3 tradeCount vs totalItemSize (관측)", None,
           f"tradeCount={d.get('tradeCount')} winCount={d.get('winCount')} "
           f"holdingDays={d.get('holdingDays')} totalItemSize={total} "
           f"→ 2*tradeCount+1={2*int(d['tradeCount'])+1 if str(d.get('tradeCount','')).isdigit() else '?'}")


def c_tradeflag_census():
    """§2/§3-1/§3-6 에서 tradeFlag 값 집합이 다름(B/S vs B/S/H vs B/S/H/W). 실제 값을 모은다."""
    seen = {}

    def add(src, flag):
        if flag:
            seen.setdefault(str(flag), set()).add(src)

    env, err, _, _ = tr("TR_SIGNAL09", {"userId": "TP_WEB"})
    if not err:
        REPORT["samples"]["TR_SIGNAL09"] = env
        for x in (env.get("retData") or {}).get("list_Signal") or []:
            add("TR_SIGNAL09", x.get("tradeFlag"))

    env, err, _, _ = tr("TR_TODAY01", {"userId": "TP_WEB"})
    if not err:
        REPORT["samples"]["TR_TODAY01"] = env
        rd = env.get("retData")
        for x in (rd if isinstance(rd, list) else []):
            add("TR_TODAY01", x.get("tradeFlag"))

    codes = [x.get("stockCode") for x in (REPORT["samples"].get("todayItemList_B") or [])][:5]
    if codes:
        env, err, _, _ = tr("TR_SIGNAL21", {"userId": "TP_WEB", "list_Stock": codes})
        if not err:
            REPORT["samples"]["TR_SIGNAL21"] = env
            rd = env.get("retData") or {}
            for key in rd:
                if isinstance(rd[key], list):
                    for x in rd[key]:
                        if isinstance(x, dict):
                            add("TR_SIGNAL21", x.get("tradeFlag"))

    documented = {"B", "S", "H", "W"}
    unknown = set(seen) - documented
    record("tradeFlag 실측 값 집합", not unknown,
           "\n".join(f"{k}: {sorted(v)}" for k, v in sorted(seen.items()))
           + (f"\n문서에 정의 없는 값: {sorted(unknown)}" if unknown else "")
           + "\n(참고: 문서는 W 의 의미를 정의하지 않음)")


def c_profit_sign_bug(buys):
    """§6: profitRate 가 음수일 때 profitSign 과 겹쳐 '--0.21' 이 되는 문제."""
    doubled, samples = [], []
    for x in (buys or [])[:12]:
        env, err, _, _ = tr("TR_SIGNAL01", {"userId": "TP_WEB", "stockCode": x.get("stockCode")})
        if err:
            continue
        s = (env.get("retData") or {}).get("struct_Signal") or {}
        sign, rate = s.get("profitSign"), str(s.get("profitRate", ""))
        samples.append(f"{s.get('stockName')}: profitSign={sign!r} profitRate={rate!r} → 단순연결 {sign}{rate}")
        if sign == "-" and rate.startswith("-"):
            doubled.append(samples[-1])
    if not samples:
        return record("§6 profitSign 이중 부호", None, "음수 사례를 찾을 표본 없음")
    record("§6 profitSign 이중 부호 재현", bool(doubled),
           ("재현됨:\n" + "\n".join(doubled)) if doubled
           else "이 표본에선 음수/이중부호 사례 없음. 관측치:\n" + "\n".join(samples[:6]))


def c_chart_vs_history(code):
    """§2-4 annotation.real 과 §3-3 TR_SIGNAL07 체결가가 일치하는가(두 소스 교차검증)."""
    data, err, st, _ = get_json(f"{API}/signal/{code}/signal3mChart?{int(time.time()*1000)}")
    if err:
        return record("§2-4 ↔ §3-3 체결가 교차검증", False, f"chart status={st} {err}")
    REPORT["samples"]["signal3mChart"] = {"annotation": (data.get("annotation") or [])[:10]}
    ann = {a.get("x", "").replace("-", ""): a for a in (data.get("annotation") or [])}
    hist = REPORT["samples"].get("TR_SIGNAL07")
    if not hist:
        return record("§2-4 ↔ §3-3 체결가 교차검증", None, "TR_SIGNAL07 표본 없음")
    mismatch, matched = [], 0
    for r in ((hist.get("retData") or {}).get("list_SigChart") or []):
        a = ann.get(r.get("td"))
        if not a:
            continue
        if str(a.get("real")) == str(r.get("tp")):
            matched += 1
        else:
            mismatch.append(f"{r['td']}: chart.real={a.get('real')} vs SIGNAL07.tp={r.get('tp')}")
        want = "up" if r.get("tf") == "B" else "down"
        if a.get("arrow") != want:
            mismatch.append(f"{r['td']}: arrow={a.get('arrow')} 인데 tf={r.get('tf')} (기대 {want})")
    record("§2-4 ↔ §3-3 체결가 교차검증", not mismatch,
           f"일치 {matched}건" + ("\n" + "\n".join(mismatch) if mismatch else ""))


def c_mobile_host(code):
    """사용자 제보: API 는 m.thinkpool.com 에 있다. m / api / www 의 라우팅을 비교한다."""
    paths = ["/signal/B/todayItemList", f"/signal/{code}/itemInfo"]
    lines, any_ok = [], False
    for base in (MAPI, API, "https://www.thinkpool.com"):
        for p in paths:
            st, ct, raw, err = http(base + p)
            body = (raw or "")[:60].replace("\n", " ")
            lines.append(f"{base+p} → status={st} ct={ct.split(';')[0]!r} 앞부분={body!r}"
                         if not err else f"{base+p} → {err}")
            if base == MAPI and st == 200 and raw.lstrip().startswith(("[", "{")):
                any_ok = True
    record("m.thinkpool.com 에서 동일 REST 경로가 열리는가", any_ok if any_ok else None,
           "\n".join(lines) + "\n(m/www/api 는 DNS상 동일 IP 121.254.150.242)")


def c_undocumented(code):
    """§6 미해결: TR_SIGNAL08 / getTradeDay 스키마 덤프."""
    env, err, st, _ = tr("TR_SIGNAL08", {"userId": "TP_WEB", "stockCode": code})
    if err:
        record("§6 TR_SIGNAL08 스키마", False, f"status={st} {err}")
    else:
        REPORT["samples"]["TR_SIGNAL08"] = env
        rd = env.get("retData") or {}
        record("§6 TR_SIGNAL08 스키마 확보", env.get("retCode") == "0000",
               f"retCode={env.get('retCode')} retData 키={list(rd)[:20]}\n"
               f"{json.dumps(env, ensure_ascii=False)[:600]}")

    st, ct, raw, err = http(f"{API}/signal/getTradeDay", body={})
    if err:
        record("§6 getTradeDay 스키마", False, str(err))
    else:
        REPORT["samples"]["getTradeDay"] = raw[:500]
        record("§6 getTradeDay 스키마 확보", st == 200,
               f"status={st} ct={ct} 본문={raw[:300]!r}")


def c_rate_limit():
    """문서에 없는 항목: 연속 호출 시 차단/스로틀이 걸리는가."""
    global DELAY
    saved, DELAY = DELAY, 0.0
    codes = [x.get("stockCode") for x in (REPORT["samples"].get("todayItemList_B") or [])][:8]
    if not codes:
        DELAY = saved
        return record("레이트리밋 프로브", None, "표본 종목 없음")
    lines, blocked = [], False
    for c in codes:
        t0 = time.time()
        env, err, st, _ = tr("TR_SIGNAL01", {"userId": "TP_WEB", "stockCode": c})
        dt = (time.time() - t0) * 1000
        rc = env.get("retCode") if env else None
        lines.append(f"{c}: HTTP={st} retCode={rc} {dt:.0f}ms" + (f" {err}" if err else ""))
        if err or st in (429, 403, 503):
            blocked = True
    DELAY = saved
    record("레이트리밋 프로브 (딜레이 0, 연속 8회)", not blocked,
           "\n".join(lines) + ("\n→ 차단/오류 발생: 수집기에 딜레이 필요" if blocked
                               else "\n→ 8회 연속 무차단. 그래도 운영 시 딜레이 권장"))


# ---------- main ----------------------------------------------------------

def main():
    global DELAY, CTX
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default=None, help="기준 종목코드(기본: 오늘 매수 1번 종목)")
    ap.add_argument("--delay", type=float, default=0.4, help="호출 간격(초)")
    ap.add_argument("--report", default=None, help="원본 응답 JSON 저장 경로")
    ap.add_argument("--insecure", action="store_true", help="TLS 검증 생략(포트 47700 인증서 문제 시)")
    a = ap.parse_args()
    DELAY = a.delay
    if a.insecure:
        CTX = ssl._create_unverified_context()

    print(f"검증 시각: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n" + "=" * 72)

    buys = c_rest_anonymous()
    c_no_masking()
    c_trade_price_zero(buys)
    c_field_drift(buys)

    code = a.code or (buys[0]["stockCode"] if buys else "005930")
    print(f"\n기준 종목: {code}\n" + "-" * 72)

    c_content_type_html()
    c_signal01(code)
    c_error_codes()
    c_signal07(code)
    c_chart_vs_history(code)
    c_tradeflag_census()
    c_profit_sign_bug(buys)
    c_mobile_host(code)
    c_undocumented(code)
    c_rate_limit()

    print("\n" + "=" * 72)
    n = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for c in REPORT["checks"]:
        n[c["result"]] += 1
    print(f"PASS {n['PASS']} / FAIL {n['FAIL']} / SKIP {n['SKIP']}")
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(REPORT, f, ensure_ascii=False, indent=2)
        print(f"원본 응답 저장: {a.report}")
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
