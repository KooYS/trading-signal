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

## 2. 핵심 엔드포인트 4개

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

## 3. 그 밖에 관측된 것 (미분석)

`/analytics` 탭에서 호출되는 것들. 전부 `wts-info-api`라 익명으로 열릴 가능성이 높다.

| 엔드포인트 | 추정 |
|---|---|
| `POST /v2/companies/A{code}/financial-statements/comprehensive` | 재무제표 |
| `POST /v2/companies/A{code}/financial-statement-records` | 재무 항목별 이력 |
| `POST /v2/stock-infos/revenue-and-net-profit/A{code}` | 매출·순이익 추이 |
| `POST /v2/stock-infos/operating-income/A{code}` | 영업이익 추이 |
| `POST /v2/companies/A{code}/financial/estimate/revenue` · `/eps` | 컨센서스 추정 |
| `GET /v1/stock-detail/ui/wts/A{code}/analyst-opinion` | 애널리스트 의견 |
| `GET /v1/stock-infos/dividend/A{code}/summary` · `/years` | 배당 이력 |
| `POST /v2/stock-infos/evaluation-comparison/A{code}` | 동종업계 밸류 비교 |
| `POST /v2/stock-infos/stability/A{code}` | 재무 안정성 |
| `GET /v1/c-chart/kr-s/A{code}/day:1?count=100` | 일봉 차트 ★ |

> **`c-chart`가 일별 시세다.** 손절 백테스트에 필요한 그 데이터일 가능성이 높다. `count`를 늘려 얼마나 소급되는지 확인할 것.

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
