# 씽크풀 라씨매매신호 API 스펙

> 분석일: 2026-08-31 / 대상: `https://www.thinkpool.com/signal` (Nuxt SPA)
> 백엔드 2개: `api.thinkpool.com`(REST) + `rassiapp.thinkpool.com:47700`(rassi_ext TR)
> 목적: "라씨 AI매매신호(오늘의 매수·매도, 종목별 매수가·매매내역)를 인증 없이 자동 수집 → 현금흐름/모니터링 자동화" 를 위한 API 역설계.
> 브라우저(claude-lens 네트워크 캡처) + 순수 python(쿠키·로그인 없음) 라이브 호출로 **인증·응답 구조·익명 접근까지 검증 완료.**

---

## 1. 인증 모델 (가장 중요)

**결론: 신호 데이터에는 서버측 인증 게이트가 사실상 없다. 아무나 익명으로 전부 조회 가능하다.**

- **REST(`api.thinkpool.com`)** — 쿠키·토큰·Authorization 헤더 전부 불필요. 브라우저·curl·python 무관하게 200 + 실데이터.
- **rassi_ext(`rassiapp.thinkpool.com:47700`)** — 필수 필드가 인증 토큰이 아니라 **하드코딩 상수 `userId: "TP_WEB"`** 하나뿐이다. 이 문자열만 넣으면 익명으로 전부 열린다.
  ```
  POST /rassi_ext/TR_SIGNAL01
  Content-Type: application/json
  {"userId":"TP_WEB","stockCode":"457190"}
  → retCode 0000, 매수가 69,450원
  ```
  - `userId` 누락 시 `0205 필수 입력 필드값 누락`, 잘못된 파라미터면 `0203`. **인증오류(401 류)는 존재하지 않음** → 인증이 아니라 필드 검증만 함.
- **CORS는 브라우저 전용 방어일 뿐.** 응답 헤더 `Access-Control-Allow-Origin: https://www.thinkpool.com` 로 남의 사이트의 브라우저 fetch만 막는다. 서버-투-서버(python/axios) 직접 호출은 CORS와 무관하게 정상 응답.
- **"프리미엄" 마스킹은 100% 프론트엔드에만 있다.** UI에서 "오늘 거래된 종목"을 `*******` 로 가리고 "프리미엄 사용시 볼 수 있습니다" 로 막지만, API(`signal/S/todayItemList`)를 직접 부르면 **종목명까지 마스킹 없이 전량 반환**된다.
- **세션이 필요한 곳은 개인화(`myItem/*`)뿐.** 익명이면 사용자 관심종목 대신 기본 목록이 온다. 신호 데이터 수집엔 무관.

---

## 2. REST API — `https://api.thinkpool.com`

전부 `GET`(별도 표기 제외), 인증 불필요. 응답 `application/json`.

### 2-1. 오늘의 매매신호 목록 (핵심)

```
GET /signal/B/todayItemList     # 오늘의 매수 전체
GET /signal/S/todayItemList     # 오늘의 매도 전체
```
- 경로의 `B`/`S` = 매수/매도 플래그. 로그인·프리미엄 없이 **전체 종목 실명** 반환.

```jsonc
[
  { "stockCode":"464580", "stockName":"닷밀", "tradeDttm":"20260831152000",
    "tradeFlag":"B", "elapsedTmTx":"15:20",
    "timeFlag":"Y",        // Y = 방금(최근) 발생 신규
    "tradePrice":0,        // ⚠️ 이 목록에선 항상 0 → 매수가는 §3-1 TR_SIGNAL01로 조회
    "profitRate":0.0 }
]
```
> **주의**: `todayItemList`의 `tradePrice`는 0으로 고정. **실제 매수/체결가는 rassi `TR_SIGNAL01`(§3-1) 또는 `TR_SIGNAL07`(§3-3)** 에서 가져와야 한다.

### 2-2. 인기 종목 신호

```
GET /signal/popularList
```
```jsonc
[{ "stockCode":"002990","stockName":"금호건설","tradeFlag":"S",
   "tradeDate":"20260828","tradePrice":18450,"price":16460,
   "fluctuationRate":-3.29,"fluctuationAmt":-560,"elapsedDays":1 }]
```

### 2-3. 종목 분석 요약 (성과 카피)

```
GET /signal/{code}/anlzInfo
```
- `anlzType`(최대수익률/누적수익률/매매횟수) + `empValue` + HTML 문구(`achieveText`).

### 2-4. 3개월 신호 차트 (시세 + 매매 마커)

```
GET /signal/{code}/signal3mChart?{random}
```
```jsonc
{
  "series":     { "data":[/* 종가 */] },
  "seriesBar":  { "data":[/* 거래량 */] },
  "categories": { "data":["2026-06-01", ...] },   // 거래일
  "annotation": [
    { "x":"2026-08-31","y":70000,"real":69450,"arrow":"up",     // up=매수
      "image":{"path":".../arrow_up.png"} },
    { "x":"2026-08-18","y":64600,"real":65100,"arrow":"down" }   // down=매도
  ]
}
```
- `annotation[].real` = 해당일 매수/매도 체결가. 차트 없이 매매 지점만 뽑을 때 유용.

### 2-5. 보조 엔드포인트

| 엔드포인트 | 용도 |
|---|---|
| `GET /signal/{code}/itemInfo` | 종목 기본 정보 |
| `GET /signal/{code}/etnFlag` | ETN 여부 |
| `POST /signal/getTradeDay` | 최근 거래일 |
| `GET /common/codename/{code}` | 코드 → 종목명 |
| `GET /common/itemSise/{code}` | 현재 시세 |
| `GET /item/analysis/topCompSise?code={code}` | 동종 비교시세 |
| `GET /item/issue/keywordList?code={code}` | 종목 이슈 키워드 |
| `GET /myItem/myItemCodeList` | **개인 관심종목(세션 의존)** — 익명이면 기본 목록 |

---

## 3. rassi_ext TR API — `https://rassiapp.thinkpool.com:47700`

전부 `POST`, `Content-Type: application/json`, 공통 필드 `userId: "TP_WEB"`.
응답 `Content-Type`은 `text/html` 이지만 **본문은 JSON**. 봉투 구조 공통:

```jsonc
{ "trCode":"TR_SIGNAL01", "retCode":"0000", "retMsg":"success", "retData": { ... } }
```

### 3-1. `TR_SIGNAL01` — 종목 현재 신호 + 매수가 ★

```jsonc
// body
{ "userId":"TP_WEB", "stockCode":"457190" }
```
```jsonc
// retData
{ "struct_Signal": {
    "stockCode":"457190", "stockName":"이수스페셜티케미컬",
    "tradeFlag":"B",                 // B=매수 / S=매도 / H=보유중
    "tradeDate":"20260831", "tradeTime":"142000",
    "tradePrice":"69450",            // ★ 매수(체결)가
    "profitRate":"0.79", "profitSign":"+",
    "elapsedDays":"0",               // 보유 경과일
    "sigStatDesc":"...당일 69450원에 매수하여 현재 0.79% 보유수익률...",
    "stockViewable":"Y", "isForbidden":"N"
}}
```
> **"얼마에 샀는지"의 정답 엔드포인트.** 종목코드만 바꿔 오늘 매수 전 종목 매수가를 익명으로 수집 가능(§5).

### 3-2. `TR_SIGNAL02` — 종목 성과 통계

```jsonc
// body: { "userId":"TP_WEB", "stockCode":"457190" }
// retData.list_SignalAnal[]: 적중률/최대수익률/누적수익률 (analTarget S=종목, R=전종목평균)
```

### 3-3. `TR_SIGNAL07` — 매매내역 (체결 이력, 페이지네이션) ★

```jsonc
// body
{ "userId":"TP_WEB", "stockCode":"457190", "pageNo":0, "pageItemSize":10 }
```
```jsonc
// retData
{ "stockCode":"457190","stockName":"이수스페셜티케미컬",
  "tradeCount":"29","winCount":"19","holdingDays":"10",
  "list_SigChart":[
    { "tf":"B","td":"20260831","tp":"69450" },              // 매수(현재 보유)
    { "tf":"S","td":"20260818","tp":"65100","pr":"25.43" }, // 매도(+수익률)
    { "tf":"B","td":"20260731","tp":"51900" },
    { "tf":"S","td":"20260608","tp":"80000","pr":"-18.37" }
    // ... totalItemSize:"59", totalPageSize:"6"
  ]}
```
- 필드 약어: `tf`=매매구분, `td`=일자, `tp`=체결가, `pr`=수익률(**매도행만**, B→S 라운드 실현수익).

### 3-4. `TR_SIGNAL09` — 오늘의 AI매매신호 현황

```jsonc
// body: { "userId":"TP_WEB" }
// retData: buyCount / sellCount + list_Signal[] (상위 종목 tradeFlag·profitRate·holdingDays)
//          updateDttm, noticeText(장 상태 문구) 포함
```

### 3-5. `TR_TODAY01` — 오늘의 매매신호 위젯(섹션별)

```jsonc
// body: { "userId":"TP_WEB" }
// retData[]: { stockDiv, title("최근 매도 종목" 등), stockCode, stockName,
//              tradeDate, tradeTime, tradeFlag, tradePrice, profitRate }
```

### 3-6. `TR_SIGNAL21` — 관심종목 현황(배열 조회)

```jsonc
// body
{ "userId":"TP_WEB", "list_Stock":["457190","161890","087010"] }
```
- 여러 종목의 현재 신호 상태(`tradeFlag` B/S/H/W, `tradePrice`, `profitRate`)를 한 번에.

### (관측·미검증) `TR_SIGNAL08`

- 종목 신호 페이지 진입 시 `{ "userId":"TP_WEB","stockCode":... }` 로 호출됨. 응답 스키마 미분석.

---

## 4. 응답 코드 (rassi_ext)

| retCode | 의미 |
|---|---|
| `0000` | 정상 |
| `0203` | 파라미터 항목이 맞지 않음 |
| `0205` | 필수 입력 필드값 누락 (예: `userId` 없음) |
| `0999` | 정의되지 않은 오류 (예: content-type 불일치·form 전송) |

**어떤 코드에도 "인증 실패"가 없다** = 서버는 인증을 검사하지 않는다.

---

## 5. 실전 스니펫 — 오늘 매수 전 종목 매수가 (익명)

```python
import urllib.request, json

H = {"Origin":"https://www.thinkpool.com", "User-Agent":"Mozilla/5.0",
     "Content-Type":"application/json", "Accept":"application/json"}

def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=15))

def tr(code, body):
    req = urllib.request.Request(
        f"https://rassiapp.thinkpool.com:47700/rassi_ext/{code}",
        data=json.dumps(body).encode(), headers=H)
    return json.load(urllib.request.urlopen(req, timeout=15))

# 1) 오늘의 매수 목록
buys = get("https://api.thinkpool.com/signal/B/todayItemList")

# 2) 종목별 매수가 (TR_SIGNAL01)
for x in buys:
    d = tr("TR_SIGNAL01", {"userId":"TP_WEB", "stockCode":x["stockCode"]})["retData"]["struct_Signal"]
    print(x["stockName"], x["elapsedTmTx"], f'{int(d["tradePrice"]):,}원',
          d["profitSign"] + d["profitRate"] + "%")
```

- 매도는 `signal/S/todayItemList` 로 동일.
- 매매 이력(라운드별 수익)은 종목당 `TR_SIGNAL07` 페이지네이션(`totalPageSize`)으로 전량 수집.

---

## 6. 주의 / 미해결

- `todayItemList.tradePrice`는 항상 0 → 매수가는 반드시 `TR_SIGNAL01`/`TR_SIGNAL07` 병행.
- `TR_SIGNAL01.profitRate`가 음수일 때 `profitSign:"-"` 와 값의 `-`가 겹쳐 표기됨(문자열 조합 시 `--0.21` → 실제 -0.21%). 부호는 `profitSign` 또는 값 하나만 사용.
- rassi 포트 `47700` 고정. 응답 `Content-Type`이 `text/html`이라 파서는 무조건 JSON 파싱할 것.
- `userId:"TP_WEB"` 상수는 웹 클라이언트 고정값이라 언제든 서버에서 바뀔 수 있음(그때 재캡처 필요). 하지만 현재 인증 게이트 자체가 없어 대체 UA/토큰 준비는 불필요.
- `TR_SIGNAL08`, `getTradeDay` 응답 스키마는 미분석.
- 무단 복제·재배포 금지 고지(사이트 하단)가 있으므로 **개인 모니터링 용도로 한정**. 데이터 재배포/상용 활용은 별도 판단 필요.
