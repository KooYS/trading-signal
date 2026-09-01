# 씽크풀 라씨매매신호 API 스펙

> 분석일: 2026-08-31 / 갱신: 2026-09-01 (§3-1 `W` 플래그, §3-6/3-7 스키마, §6 라운드 짝짓기 함정 추가)
> 대상: `https://www.thinkpool.com/signal` (Nuxt SPA)
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
| `POST /signal/getTradeDay` | 최근 거래일. **JSON 아님** — 평문 `2026.09.01` 반환 |
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

### 3-1. `TR_SIGNAL01` — 종목 현재 신호 + 체결가 ★

```jsonc
// body
{ "userId":"TP_WEB", "stockCode":"457190" }
```
```jsonc
// retData
{ "struct_Signal": {
    "stockCode":"457190", "stockName":"이수스페셜티케미컬",
    "tradeFlag":"B",                 // B=매수신호 / S=매도신호 / H=보유중 / W=관망(매도 후)
    "tradeDate":"20260831", "tradeTime":"142000",
    "tradePrice":"69450",            // ★ tradeFlag에 따라 의미가 다르다 — 아래 표
    "profitRate":"0.79", "profitSign":"+",
    "elapsedDays":"0",               // 보유 경과일
    "sigStatDesc":"...당일 69450원에 매수하여 현재 0.79% 보유수익률...",
    "stockViewable":"Y", "isForbidden":"N"
}}
```

> ⚠️ **`tradePrice`·`profitRate`는 `tradeFlag`에 따라 뜻이 뒤바뀐다.** 문서화된 `B/S/H` 외에 **`W`가 실제로 온다.**
>
> | tradeFlag | 상태 | `tradePrice` | `profitRate` |
> |---|---|---|---|
> | `B` / `H` | 매수신호 / 보유중 | **매수가** | 현재 **평가**수익률 (시세따라 실시간 변동) |
> | `S` / `W` | 매도신호 / 관망 | **매도가** | 그 라운드 **실현**수익률 (확정값) |
>
> 장중에 신호가 나면 `B`/`S`로 보이다가 이후 `H`/`W`로 전환된다. 즉 `todayItemList`의 매수 목록을 조회해도
> `TR_SIGNAL01`은 `H`를 돌려준다. `H`의 `profitRate`를 실현수익률로 착각해 저장하면 안 된다 — 매초 바뀌는 값이다.
>
> 검증: 인스피언(465480) `TR_SIGNAL01` = `W`/3455원/22.74% ↔ `TR_SIGNAL07`의 최상단 `{tf:S, td:20260831, tp:3455, pr:22.74}` 와 정확히 일치.

> **주의**: 이 TR은 그 종목의 **최신 신호 1건**만 준다. 과거 특정 신호의 가격을 알고 싶으면 `TR_SIGNAL07`(§3-3)을 써야 한다.
> 여러 종목을 한 번에 조회할 땐 종목당 호출하지 말고 **`TR_SIGNAL21`(§3-6)** 로 배열 조회하는 게 압도적으로 낫다.

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
```jsonc
// retData — 배열. TR_SIGNAL01의 struct_Signal과 같은 필드 구성
[{ "stockCode":"192410","stockName":"오늘이엔엠","tradeFlag":"W",
   "tradeDate":"20260831","tradeTime":"152000",
   "tradePrice":"5040","profitRate":"5.22",     // 부호가 값에 포함됨 ("-1.06")
   "elapsedDays":"1","signalTargetYn":"Y","signalIssueYn":"Y" }]
```
- **다건 조회의 정답.** 75종목을 넣어도 **1 request**로 전부 반환된다(실측). 종목당 `TR_SIGNAL01`을 도는 건 낭비.
- `TR_SIGNAL01`과 달리 **`profitSign` 필드가 없고** `profitRate`에 부호가 직접 들어있다 → §7의 이중부호 함정이 없다.
- `tradeFlag`·`tradePrice` 의미는 §3-1 표와 동일.

### 3-7. `TR_SIGNAL08` — 누적 시뮬레이션 손익

```jsonc
// body: { "userId":"TP_WEB", "stockCode":"465480" }
// retData
{ "beginYear":"2026", "investAmt":"1000", "balanceAmt":"886" }
```
- 종목별 신호 추종 시 원금 대비 잔고. 단위 미확정(만원 추정). 위 예시는 1000 → 886.

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

## 5. 실전 스니펫 — 오늘 신호 전 종목 체결가 (익명, 3 request)

```python
import urllib.request, json

H = {"Origin":"https://www.thinkpool.com", "User-Agent":"Mozilla/5.0",
     "Content-Type":"application/json", "Accept":"application/json"}

def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30))

def tr(code, **body):
    req = urllib.request.Request(
        f"https://rassiapp.thinkpool.com:47700/rassi_ext/{code}",
        data=json.dumps({"userId": "TP_WEB", **body}).encode(), headers=H)
    return json.load(urllib.request.urlopen(req, timeout=30))["retData"]

# 1~2) 오늘의 매수/매도 목록 (2 request)
items = [(f, x) for f in "BS"
         for x in get(f"https://api.thinkpool.com/signal/{f}/todayItemList")]

# 3) 전 종목 체결가를 한 방에 (TR_SIGNAL21 — 종목당 호출하지 말 것)
codes = sorted({x["stockCode"] for _, x in items})
live = {d["stockCode"]: d for d in tr("TR_SIGNAL21", list_Stock=codes)}

for flag, x in items:
    d = live[x["stockCode"]]
    # ⚠️ TR_SIGNAL21은 '최신' 신호만 준다. 목록 행과 시각이 다르면 다른 신호의 가격이다
    if d["tradeDate"] + d["tradeTime"] != x["tradeDttm"][:14]:
        continue
    print(flag, x["stockName"], f'{int(d["tradePrice"]):,}원', d["profitRate"] + "%")
```

- 매매 이력(라운드별 실현수익)은 종목당 `TR_SIGNAL07` 페이지네이션(`totalPageSize`)으로 전량 수집.
  **폴링으로 며칠 모을 필요 없다** — 종목당 첫 백필 한 번에 10년치가 들어온다(실측 84종목 → 10,354행, 2014년~).
- 이 레포의 구현: [`collect.py`](../collect.py) (`poll` / `backfill` / `check`).

---

---

## 6. 라운드 짝짓기 함정 ★ (조용히 틀리는 버그)

수집한 신호를 원장에 쌓은 뒤 "이 신호 따라 매매했으면 얼마?"를 계산하려면 매도행마다 **짝이 되는 매수행**을 찾아야 한다(= 라운드).
날짜순 `lag()`로 짝지으면 **에러 없이 틀린 숫자가 나온다.**

### 원인: 같은 날 B와 S가 동시에 나고, 그 순서가 케이스마다 다르다

`TR_SIGNAL07`은 **날짜(`td`)만 주고 시각을 안 준다.** 그래서 같은 날 두 신호의 선후를 데이터로 알 수 없는데,
실제 순서는 두 종류가 섞여 있다. (84종목 10,354행 중 같은 날 B+S가 **20건**)

**한탑(002680) — 같은 날 `B → S` (당일 사서 당일 청산)**
```
2021-09-30  B  1,370
2021-09-30  S  1,395   +1.82%      ← 1370 × 1.0182 = 1395. 같은 날 B가 짝
```

**씨티케이(260930) — 같은 날 `S → B` (청산 후 같은 날 재진입)**
```
2022-07-13  B  6,790               ← S(08-17)의 진짜 짝
2022-08-17  B  7,590
2022-08-17  S  7,490  +10.31%      ← 7490 ÷ 1.1031 = 6790. 같은 날 B가 아니다
2022-09-06  S  8,020   +5.67%      ← B(08-17)의 짝 (8020 ÷ 1.0567 = 7590)
```

어떤 tie-break를 써도 한쪽이 깨진다 (실측):

| `lag()` tie-break | 한탑 | 씨티케이 | 결과 |
|---|---|---|---|
| B 먼저 | ✅ | ❌ -1.32% (정답 +10.31%) | 오답 1건 |
| S 먼저 | ❌ 앞에 B가 없어 라운드 누락 | ✅ | 누락 19건 (5,167 → 5,148) |

### 해결: 순서를 추측하지 말고 `profit_rate`로 역산

```
매수가 = 매도가 ÷ (1 + 실현수익률/100)
```
이 값과 일치하는 `B` 행을 찾으면 순서 가정이 아예 필요 없다. **5,167/5,167 전건 매칭 확인.**

```sql
-- signal_round 뷰의 핵심부 (schema.sql)
cross join lateral (
  select b.trade_date, b.trade_price from signal b
  where b.stock_code = s.stock_code and b.trade_flag = 'B'
    and b.trade_date <= s.trade_date
    and abs(b.trade_price * (1 + s.profit_rate/100.0) - s.trade_price)
        <= greatest(1.0, s.trade_price * 0.0002)   -- pr이 소수 2자리라 반올림 허용오차
  order by b.trade_date desc limit 1
) b
```

> **이게 위험한 이유**: 예외가 안 나고 그럴듯한 숫자가 나온다. 5,167건 중 1건만 어긋나서 눈으로도 안 잡힌다.
> 원장에서 라운드를 뽑을 땐 반드시 `signal_round` 뷰를 쓸 것.

### 원장 검증 결과 (2026-09-01 기준, 84종목)

| 검사 | 결과 |
|---|---|
| 적재 | 10,354행 / 84종목 / 2014-10-17 ~ 2026-09-01 |
| B/S 균형 | 5,187B vs 5,167S → 차이 20 = 현재 보유중 20종목 |
| 가격 결측·0원 / 이름 결측 / 미래날짜 | 0건 |
| B행에 평가수익률 오염 | 0건 |
| **저장가격으로 수익률 재계산 대조** | **5,167/5,167 일치, 최대오차 0.00** |

---

## 7. 주의 / 미해결

- `todayItemList.tradePrice`는 항상 0 → 매수가는 반드시 `TR_SIGNAL01`/`TR_SIGNAL07` 병행.
- `TR_SIGNAL01.profitRate`가 음수일 때 `profitSign:"-"` 와 값의 `-`가 겹쳐 표기됨(문자열 조합 시 `--0.21` → 실제 -0.21%). 부호는 `profitSign` 또는 값 하나만 사용.
- rassi 포트 `47700` 고정. 응답 `Content-Type`이 `text/html`이라 파서는 무조건 JSON 파싱할 것.
- `userId:"TP_WEB"` 상수는 웹 클라이언트 고정값이라 언제든 서버에서 바뀔 수 있음(그때 재캡처 필요). 하지만 현재 인증 게이트 자체가 없어 대체 UA/토큰 준비는 불필요.
- `TR_SIGNAL08`(§3-7)·`getTradeDay`(§2-5) 스키마 분석 완료. `TR_SIGNAL08`의 금액 단위만 미확정.
- `todayItemList`는 "오늘"이 아니라 **최근 거래일** 기준이다. 당일 신호 발생 전(장 초반)에는 **전 거래일 목록**이 그대로 온다.
  `TR_SIGNAL09`의 `noticeCode:"TIME_OPEN"` + `remainTime` 으로 아직 미발생 상태인지 구분 가능.
- 신호 발생 시각은 **20분 그리드**에 고정된다(`09:20, 09:40, … 15:20`). 폴링 주기를 20분으로 잡으면 딱 맞고,
  발생 직후를 잡으려면 몇 분 오프셋을 두는 게 낫다.
- 해외 IP(GitHub Actions 러너)에서 `api.thinkpool.com`이 **간헐적으로 타임아웃**난다. 재시도 필요.
- 무단 복제·재배포 금지 고지(사이트 하단)가 있으므로 **개인 모니터링 용도로 한정**. 데이터 재배포/상용 활용은 별도 판단 필요.
