# 토스증권 wts-info-api 스펙

> 검증일: 2026-09-01 / 대상: `https://www.tossinvest.com/stocks/A{code}/analytics`
> 브라우저 네트워크 캡처 + 순수 curl(쿠키·로그인 없음) 라이브 호출로 검증.
> **인증 불필요.** 아래 엔드포인트는 전부 헤더 없이(또는 `User-Agent`만으로) 200을 준다.

공식 문서가 없는 내부 API다. 예고 없이 바뀔 수 있다.

---

## 1. 기본 규칙

```
BASE  https://wts-info-api.tossinvest.com/api
종목코드  "A" + 6자리   (디어유 376300 → A376300)
```

- 응답 봉투: `{"result": ...}` — 실제 데이터는 항상 `result` 안에.
- 인증 헤더·쿠키 불필요. `User-Agent`만 브라우저 문자열로 넣으면 된다.
- **호스트가 셋 있고 권한이 다르다.** 아래만 익명으로 열린다.

| 호스트 | 익명 접근 |
|---|---|
| `wts-info-api.tossinvest.com` | **✅ 열림** — 종목 정보·지표·시세 |
| `wts-api.tossinvest.com` | ❌ 401 (세션 필요) |
| `wts-cert-api.tossinvest.com` | ❌ 인증 필요 — 주문·보유·red-flags |

## 2. 핵심 엔드포인트 5개

### 2-1. 투자지표 (PER·PBR·ROE·배당) ★

```
GET /v1/stock-detail/ui/wts/A{code}/investment-indicators
```
```jsonc
{"indicatorSections":[
  {"sectionName":"가치평가","data":{"displayPer":"12.1배","displayPbr":"2.0배","displayPsr":"4.7배"}},
  {"sectionName":"수익","data":{"eps":1529.63,"bps":9214.52,"roe":"17.7%"}},
  {"sectionName":"배당","data":{"dividendYieldRatio":0.0169,"annualCash":316.0,
                                "exDate":"2026-03-12","lastYear":2025, ...}}
]}
```

> ⚠️ **섹션 배열이라 인덱스로 꺼내면 안 된다.** `sectionName`으로 찾을 것.
> 값이 `"12.1배"`, `"17.7%"` 처럼 **단위가 붙은 문자열**인 것과(`displayPer`, `roe`)
> 숫자 그대로인 것(`eps`, `bps`, `dividendYieldRatio`)이 섞여 있다.
> `dividendYieldRatio`는 비율(0.0169 = 1.69%)이지 퍼센트가 아니다.

### 2-2. 시세·시총·52주 (배치 조회) ★

```
GET /v3/stock-prices/details?productCodes=A376300,A010960,A119850
```
```jsonc
[{ "code":"A376300", "open":18530, "high":18810, "low":18360, "close":18630,
   "base":18560, "changeType":"UP", "volume":70794, "value":1314041865,
   "high52w":51500, "low52w":17680, "high1y":51700, "low1y":17680,
   "marketCap":442246503780, "tradingStrength":116.0,
   "upperLimit":24100, "lowerLimit":13000, "preDayVolume":308940 }]
```
- **콤마로 여러 종목을 한 번에.** 배치 상한은 미측정.
- `base`가 전일 종가라 `close/base - 1`로 등락률을 직접 계산할 수 있다.
- 단건은 `/v2/stock-prices/A{code}` 로도 된다(같은 필드).

### 2-3. 기업 개요

```
GET /v2/stock-infos/A{code}/overview
```
```jsonc
{ "market":{"code":"KSQ","displayName":"코스닥"},
  "company":{ "code":"376300","name":"디어유","fullEnglishName":"DEAR U Co.,Ltd.",
    "industry":{"code":"G502050","displayName":"양방향미디어와서비스"},
    "description":"동사는 2017년 모바일 노래방 서비스 사업을 위해 설립되었으며...",
    "establishDate":"2017-07-04","listDate":"2021-11-10","ceo":"안종오",
    "homepageUrl":"http://www.dear-u.co","sharesOutstanding":23738406,
    "marketValue":442721271900 }}
```

### 2-4. 매출 구성

```
GET /v1/companies/{code}/sales-compositions        ← 여기는 "A" 접두 없음 ⚠️
```
```jsonc
{ "code":"376300","fiscalYear":2025,"endDate":"2025-12-31",
  "compositions":[{"business":"DearU bubble","ratio":98.21},{"business":"기타","ratio":1.79}],
  "dataSource":"출처: FnGuide 및 기업 IR자료" }
```
> **이 엔드포인트만 종목코드에 `A` 접두를 안 붙인다.** ETF·신규상장은 없을 수 있어 실패를 흡수할 것.

### 2-5. 투자자별 매매동향 (개인·외국인·기관) ★

```
GET /v1/stock-infos/trade/trend/trading-trend?productCode=A{code}&size=120
```
```jsonc
// result.body[] — 최근일부터 내림차순
[{ "baseDate":"2026-09-01", "close":5860, "base":5740,
   "netIndividualsBuyVolume":-5980, "netForeignerBuyVolume":-62119,
   "netInstitutionBuyVolume":67863,
   // 기관 세부 7주체 — 합이 netInstitutionBuyVolume 과 정확히 일치 (2,499행 전건 검증)
   "netFinancialInvestmentBuyVolume":-9535,   // 금융투자(증권)
   "netInsuranceBuyVolume":0, "netTrustBuyVolume":47535,
   "netPrivateEquityFundBuyVolume":29863, "netBankBuyVolume":0,
   "netOtherFinancialInstitutionsBuyVolume":0, "netPensionFundBuyVolume":0,
   "netOtherCorporationBuyVolume":852,        // 기타법인 — 기관 합계에 미포함
   "foreignerBuyVolume":415313, "foreignerSellVolume":477432,
   "foreignerHoldingVolume":14006797, "foreignerLimitVolume":70283330,
   "foreignerRatio":19.93,
   "inMarketTime":false, "updatedAt":"2026-09-01T15:37:15.000+09:00" }]
```

> ⚠️ **`/analytics` 탭의 `section-orders` 에는 이 섹션이 없다.** 주문 탭에서 호출된다.
> analytics 목록만 보고 "토스엔 수급 없음"이라 판단하면 틀린다(실제로 한 번 틀렸다).

- **당일치가 나온다.** 네이버 금융(`finance.naver.com/item/frgn.naver`)도 같은 데이터를 주지만
  **하루 늦고**(17:23에도 전일이 최신) 20일치뿐이며 euc-kr HTML 파싱이 필요하다. 토스가 전 항목 우위.
- **당일 값은 잠정치다.** 장마감 직후 `updatedAt`이 15:37로 찍히고 20시경 확정값으로 갱신된다
  (전일 행의 `updatedAt`은 20:19). 그래서 수집을 낮(poll)과 20:30 두 번 돌린다.
- **외국인은 주체별 분해가 없다.** 매수/매도/보유/한도/비율만 주는 단일 집계. 기관만 7주체로 쪼개진다.
- `size`로 일수 지정(60 확인).

> 연속 순매수 일수만 세면 규모를 놓친다. 실측 예:
> `뷰웍스 기관 12일 연속 +579주`(노이즈) vs `지니언스 기관 3일 연속 +11만주`(실매수).
> 일수와 수량을 함께 볼 것.

**`size` 상한은 121~299 사이다**(120 OK, 300부터 400 — 실측). 120이면 약 5.7개월치.

**페이지네이션이 있다.** 응답 `result` 가 `{pagingParam, body, lastPage}` 이고,
`pagingParam` 을 **평평하게** 쿼리에 되돌려주면 그 이전 구간이 온다.

```
1페이지: ?productCode=A005930&size=120        → 2026-03-10 까지, lastPage=false
          pagingParam = {"number":2,"size":120,"key":"2026-03-09"}
2페이지: ?productCode=A005930&number=2&size=120&key=2026-03-09  → 2025-09-05 까지
```

⚠️ JSON 통째로 넣거나(`pagingParam={...}`) 점 표기(`pagingParam.key=`)는 무시당한다.
`page`·`pageNumber` 도 안 먹는다. 키를 평평하게 펴는 것만 된다. `lastPage` 로 끝을 판단한다.

## 3. 그 밖에 관측된 것 (미분석)

`/analytics` 탭에서 호출되는 것들. 전부 `wts-info-api`라 익명으로 열릴 가능성이 높다.

| 엔드포인트 | 추정 |
|---|---|
| `POST /v2/companies/A{code}/financial-statements/comprehensive` | 재무제표 **✅ 확인** |
| `POST /v2/companies/A{code}/financial-statement-records` | 재무 항목별 이력 **✅ 확인** |
| `POST /v2/stock-infos/revenue-and-net-profit/A{code}` | 매출·순이익 추이 **✅ 확인** |
| `POST /v2/stock-infos/operating-income/A{code}` | 영업이익 추이 **✅ 확인** |
| `POST /v2/companies/A{code}/financial/estimate/revenue` · `/eps` | 컨센서스 추정 |
| `GET /v1/stock-detail/ui/wts/A{code}/analyst-opinion` | 애널리스트 의견 |
| `GET /v1/stock-infos/dividend/A{code}/summary` · `/years` | 배당 이력 |
| `POST /v2/stock-infos/evaluation-comparison/A{code}` | 동종업계 밸류 비교 |
| `POST /v2/stock-infos/stability/A{code}` | 재무 안정성 |
| `GET /v1/c-chart/kr-s/A{code}/day:1?count=100` | 일봉 차트 ★ |
| `GET /v1/stock-infos/A{code}/wts-badges` · `header/A{code}` | 뱃지·헤더 |

> **`c-chart`가 일별 시세다.** 손절 백테스트에 필요한 그 데이터일 가능성이 높다.

### 1단계 타진 결과 (2026-09-01, A005930)

**분기 재무 4개 전부 익명으로 열린다.** POST 본문을 빈 `{}` 로 보내도 200이 온다.

- `revenue-and-net-profit`, `operating-income` — 본문 **`{"range": 5}`** 라야 5년이다.
  빈 본문이면 3년만 온다. `rangeCode`·`code`·`period`·`selectedRange` 등 다른 이름은
  전부 무시되고 3년이 온다(2단계 실측).
  **⚠️ `table[]` 은 range 와 무관하게 12개로 잘린다.** 5년치는 `graph[]` 에 있다.
  대신 `table` 에만 `netProfitGrowthRatio` 가 있어서 둘을 period 로 합쳐야 전량이 나온다.
  (`table` 만 읽었다가 97종목 전부 12분기 이하로 들어와서 발견)
  ETF·리츠는 재무제표가 없어 404다 — 오늘 신호 119종목 중 22개가 ETF라 건너뛴다.
- `financial-statements/comprehensive` — `selectedFactor: LIABILITY_RATIO`,
  `selectableFactors` 에 부채비율·유동비율 등. 지표를 골라 받는 구조다.
- `financial-statement-records` — `selectedFactor: BAL(재무상태표)`,
  `selectableFactors` 에 `INC(손익계산서)` 등.

**일봉은 한 번에 다 못 받는다. 페이지네이션이다.**

```
count=100   → 200, 캔들 101건 (2026-04-06 ~ 2026-09-01)
count=1000  → 400 Bad Request
count=3000  → 400
count=10000 → 400
```

상한이 있다. 그런데 응답 최상위에 **`nextDateTime: "2026-04-06T00:00:00+09:00"`** 이
들어 있다 — 다음 페이지 커서다. 캔들은 `candles[]` 이고 한 건이
`{dt, base, open, high, low, ...}` 다.

**즉 소급은 되고, 커서를 돌려야 한다.** 파라미터 이름과 count 상한은 2단계에서 확정한다.

### 타진 방법

`tools/probe.py` 가 1단계, `tools/probe2-console.js` 가 2단계다. 셋 중 편한 걸로:

| 방법 | 명령 | 비고 |
|---|---|---|
| 브라우저 | `tools/probe-console.js` / `probe2-console.js` 를 tossinvest.com 콘솔에 붙여넣기 | **국내 IP·같은 오리진이라 가장 확실.** 1단계는 이걸로 성공했다 |
| 로컬 | `python3 tools/probe.py [종목코드]` | 의존성 없음 |
| GitHub Actions | Actions → probe → Run workflow | 로컬 불필요. 결과가 실행 요약에 뜬다. 러너가 미국이라 막힐 수 있다 |

붙여넣기가 막히면 콘솔에 `allow pasting` 을 먼저 입력한다.
`DART_KEY` 를 주면(환경변수 또는 저장소 Secret) DART 공시까지 함께 확인한다.

### 타진 방법

`tools/probe.py` 가 위 후보들을 한 번에 두드린다. 셋 중 편한 걸로:

| 방법 | 명령 | 비고 |
|---|---|---|
| 로컬 | `python3 tools/probe.py [종목코드]` | 의존성 없음 |
| GitHub Actions | Actions → probe → Run workflow | 로컬 불필요. 결과가 실행 요약에 뜬다. **러너가 미국이라 막힐 수 있다** |
| 브라우저 | `tools/probe-console.js` 를 tossinvest.com 콘솔에 붙여넣기 | 국내 IP·같은 오리진이라 가장 확실 |

`DART_KEY` 를 주면(환경변수 또는 저장소 Secret) DART 공시까지 함께 확인한다.

**일봉 소급 기간이 관건이다.** 몇 년치가 나오면 현재 `bps`·`shares_out` 과 조합해
과거 PBR·시총을 역산할 수 있고, 점수 축을 3개월이 아니라 전 구간에서 검증할 수 있다.
3개월치뿐이면 소급은 포기하고 오늘부터 일별로 쌓아야 한다.

## 4. 우리 구현

`collect.py`:

```
python3 collect.py fund          # 오늘 신호 종목 펀더멘탈
python3 collect.py poll          # 신호 + 스냅샷 없는 종목의 펀더멘탈을 함께
```

`poll`이 신호를 적재한 뒤 **오늘 스냅샷이 없는 종목만** 골라 펀더멘탈을 채운다
(`missing_fund`). 그날 첫 폴링이 전부 긁고 이후 20분 폴링은 신규 편입분만 붙어
빠른 경로가 유지된다. 실측: 이미 채워진 상태 2.7초 / 2종목 보충 4.6초.

토스가 죽어도 신호 적재는 계속되도록 `fund` 실패는 흡수한다.

테이블 `fundamental` — PK `(stock_code, as_of)`. PER·PBR은 주가에 연동돼 매일 바뀌므로
날짜별 스냅샷으로 쌓는다. 뷰 `fundamental_latest`가 종목별 최신 행 + `pos_52w`(52주 내 위치 %)를 준다.

## 5. 최소 예제

```python
import json, urllib.request
B = "https://wts-info-api.tossinvest.com/api"
H = {"User-Agent": "Mozilla/5.0"}

def get(path):
    r = urllib.request.Request(B + path, headers=H)
    return json.load(urllib.request.urlopen(r, timeout=20))["result"]

def indicators(code):
    secs = get(f"/v1/stock-detail/ui/wts/A{code}/investment-indicators")["indicatorSections"]
    return {s["sectionName"]: s["data"] for s in secs}

indicators("376300")["가치평가"]        # {'displayPer': '12.1배', ...}
get("/v3/stock-prices/details?productCodes=A376300,A010960")   # 배치 시세
get("/v2/stock-infos/A376300/overview")["company"]["industry"]
get("/v1/companies/376300/sales-compositions")["compositions"]  # A 접두 없음
```

## 6. 주의

- **`A` 접두 규칙이 엔드포인트마다 다르다.** `sales-compositions`만 예외.
- 지표 값의 타입이 섞여 있다(`"12.1배"` 문자열 vs `1529.63` 숫자). 파서에서 단위 제거 필요.
- ETF·리츠·신규상장은 지표가 비거나 404다. 종목 단위로 실패를 흡수할 것.
- `wts-cert-api` / `wts-api` 는 인증이 필요하다. 익명 수집은 `wts-info-api` 안에서만.
- 개인 모니터링 용도로 한정. 재배포하지 않는다.
