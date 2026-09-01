#!/usr/bin/env python3
"""토스 wts-info-api 미분석 엔드포인트 + DART 점검.

docs/toss-invest-api.md 3절에 관측만 해두고 분석 안 한 것들이 실제로 익명으로
열리는지, 일봉이 얼마나 소급되는지, 분기 재무가 몇 분기치 오는지 확인한다.

일봉 소급 기간이 핵심이다. 몇 년치가 나오면 현재 bps·shares_out 과 조합해
과거 PBR·시총을 역산할 수 있고, 그러면 점수 축을 3개월이 아니라 전 구간으로
검증할 수 있다. 3개월치뿐이면 소급 검증을 포기하고 오늘부터 쌓아야 한다.

의존성 없음(stdlib). collect.py 와 같은 제약을 따른다 — Lambda 에 그대로 올라간다.

    python3 tools/probe.py [종목코드]
    DART_KEY=... python3 tools/probe.py     # DART 까지 함께
"""
import json, os, sys, urllib.error, urllib.request

BASE = "https://wts-info-api.tossinvest.com/api"
HDRS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
CODE = (sys.argv[1] if len(sys.argv) > 1 else "005930").strip()

out = []                      # 사람이 읽는 줄
def say(line=""):
    print(line, flush=True)
    out.append(line)


def call(path, body=None, timeout=20):
    """(status, payload). 실패해도 예외 대신 상태를 돌려준다."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=HDRS,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400].decode("utf-8", "replace")
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def dates_in(obj, found):
    """응답 어디에 날짜가 박혀 있을지 몰라 통째로 훑는다."""
    if isinstance(obj, dict):
        for v in obj.values():
            dates_in(v, found)
    elif isinstance(obj, list):
        for v in obj:
            dates_in(v, found)
    elif isinstance(obj, str) and len(obj) >= 8 and obj[:4].isdigit() and obj[0] in "12":
        found.append(obj[:10])


def report(label, status, payload, snip=240):
    if status != 200:
        say("  X %s -> %s %s" % (label, status, str(payload)[:140]))
        return
    res = payload.get("result", payload) if isinstance(payload, dict) else payload
    found = []
    dates_in(res, found)
    span = ""
    if found:
        span = "  기간 %s ~ %s (날짜 %d개)" % (min(found), max(found), len(found))
    say("  O %s -> 200%s" % (label, span))
    say("      %s" % json.dumps(res, ensure_ascii=False)[:snip])


say("=== 토스 wts-info-api 점검 (종목 %s) ===" % CODE)
say()
say("[1] 일봉 - 얼마나 소급되나  (밴드/소급검증의 핵심)")
for cnt in (100, 1000, 3000, 10000):
    st, pl = call("/v1/c-chart/kr-s/A%s/day:1?count=%d" % (CODE, cnt))
    report("count=%d" % cnt, st, pl, snip=200)

say()
say("[2] 분기 재무 - 밴드 재료 (POST, 본문 스키마 미상이라 빈 본문으로 타진)")
for path in ("/v2/stock-infos/revenue-and-net-profit/A%s" % CODE,
             "/v2/stock-infos/operating-income/A%s" % CODE,
             "/v2/companies/A%s/financial-statements/comprehensive" % CODE,
             "/v2/companies/A%s/financial-statement-records" % CODE):
    st, pl = call(path, body={})
    report(path, st, pl)

say()
say("[3] 회귀 확인 - 이미 쓰고 있는 것들이 여전히 열리는지")
for path in ("/v1/stock-detail/ui/wts/A%s/investment-indicators" % CODE,
             "/v2/stock-infos/A%s/overview" % CODE,
             "/v1/stock-infos/trade/trend/trading-trend?productCode=A%s&size=5" % CODE):
    st, _ = call(path)
    say("  %s %s -> %s" % ("O" if st == 200 else "X", path, st))

say()
say("[4] DART 공시")
key = os.environ.get("DART_KEY", "").strip()
if not key:
    say("  - DART_KEY 없음. opendart.fss.or.kr 에서 무료 발급 후 넣으면 함께 확인한다.")
else:
    url = ("https://opendart.fss.or.kr/api/list.json?crtfc_key=%s"
           "&bgn_de=20260801&end_de=20260901&page_count=10" % key)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.loads(r.read().decode())
        say("  status=%s %s / 총 %s건" % (d.get("status"), d.get("message"), d.get("total_count")))
        for it in (d.get("list") or [])[:5]:
            say("    %s %s - %s" % (it.get("rcept_dt"), it.get("corp_name"), it.get("report_nm")))
    except Exception as e:
        say("  X %s: %s" % (type(e).__name__, e))

# GitHub Actions 에서 돌면 결과를 실행 요약에 그대로 띄운다 (로그 뒤질 필요 없게)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as fh:
        fh.write("## probe 결과 (%s)\n\n```\n%s\n```\n" % (CODE, "\n".join(out)))
