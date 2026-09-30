# 주식매매신호 (trading-signal)

씽크풀 **라씨 AI매매신호**(오늘의 매수·매도, 종목별 매수가·매매내역)를 인증 없이 순수 API 콜로 수집하기 위한 개인 프로젝트.

## 문서

- [`docs/thinkpool-signal-api.md`](docs/thinkpool-signal-api.md) — 엔드포인트·인증 모델·응답 스키마 역설계 스펙 (라이브 검증 완료)
- [`docs/google-news-rss.md`](docs/google-news-rss.md) — Google News RSS 스펙. 키 없이 정적 수집, 날짜 창으로 무제한 소급
- [`docs/toss-invest-api.md`](docs/toss-invest-api.md) — 토스증권 wts-info-api 스펙. PER/PBR/ROE·시총·52주·매출구성, 인증 불필요
- [`docs/backtest.md`](docs/backtest.md) — **보조지표 검증 결과.** 무엇이 통했고 무엇이 안 통했나

## 핵심

- 두 백엔드: `api.thinkpool.com`(REST) + `rassiapp.thinkpool.com:47700`(rassi_ext TR)
- 서버측 인증 게이트 없음 — rassi는 하드코딩 상수 `userId: "TP_WEB"` 하나면 익명 조회 가능
- "프리미엄" 마스킹은 프론트엔드에만 존재, API 직접 호출 시 실명 전량 반환
- `오늘의 매수/매도 → 매수가 → 매매내역/실현수익 → 통계` 까지 순수 API로 조합 가능

## 주의

개인 모니터링 용도로 한정. 무단 복제·재배포 금지 고지가 있으므로 데이터 재배포/상용 활용은 별도 판단 필요. private 유지.

## 수집

```
python3 collect.py check      # 네트워크 없이 변환 로직 검증
python3 collect.py poll       # 오늘 신호 (3 request)
python3 collect.py backfill   # 오늘 종목 매매이력 전량
python3 collect.py news       # 오늘 종목 최근 뉴스 (Google News RSS, 키 불필요)
python3 collect.py news_backfill 2026-08   # 월 단위 뉴스 소급
python3 collect.py fund       # 펀더멘탈 (토스). poll 이 자동으로 함께 채운다
python3 collect.py flow       # 외국인·기관 순매매 60일치 (토스)
python3 collect.py flow_backfill 25     # 수급 소급 (1페이지 ≈ 120거래일)
python3 collect.py price      # 일별 시세 1페이지(약 15개월)
python3 collect.py price_backfill 20   # 일별 시세를 20페이지까지 소급
python3 collect.py fin        # 분기 매출·순이익·영업이익 5년치
python3 collect.py dart_corp        # DART corp_code 대응표 (disclosure 전 1회)
python3 collect.py disclosure --all # DART 공시 (신호 전 종목, 2019~)
```

DART 는 `DART_KEY` 환경변수가 필요하다(opendart.fss.or.kr 무료 발급, 일 2만건).
키를 저장소에 커밋하지 않는다.

`price` 는 한 번에 다 안 온다. `count` 상한이 300~499 사이고 응답의
`nextDateTime` 을 `?from=` 으로 되돌려줘야 그 이전 구간이 온다. 1페이지가
약 300거래일(15개월)이라 `price_backfill 20` 이면 20년 남짓이다.

지표(`tech_daily`·`mkt_index`)는 **매일 08:30 KST 에 DB 안에서 스스로 갱신한다**
(`pg_cron` + `http` 확장으로 토스를 직접 호출). Lambda 가 죽어도 화면 점수는 유지된다.
반대로 `price` 를 손으로 채웠으면 `refresh materialized view` 를 꼭 같이 해야 한다.

Supabase 프로젝트 `trading-signal` (`fvwwxhdufcqpcyysfdgg`, ap-northeast-2).
테이블 `signal` — 스키마·설계 근거는 [`schema.sql`](schema.sql).
라운드(B→S 한 사이클) 분석은 `signal_round` 뷰를 쓴다. 같은 날 B/S가 동시에 나는
케이스가 20건 있고 순서가 섞여 있어서, 날짜로 lag() 짝짓기를 하면 틀린다.

## 배포 — AWS Lambda (ap-northeast-2)

**서울 리전이어야 한다.** thinkpool이 해외 IP를 막는다: GitHub Actions(미국) 러너에서
9회 중 4회 실패(30초 타임아웃)했고, 서울에서는 5/5 성공에 7~27ms다.

`collect.py`는 의존성이 없어서(stdlib만) 파일 하나 zip이면 배포 끝이다.

```
zip collect.zip collect.py
aws lambda update-function-code --function-name trading-signal-collect \
  --zip-file fileb://collect.zip
```

| 리소스 | 이름 |
|---|---|
| Lambda | `trading-signal-collect` (python3.13/arm64, 900s, 256MB) |
| 실행 역할 | `trading-signal-collect-role` |
| 스케줄러 역할 | `trading-signal-scheduler-role` (해당 함수만 invoke) |
| 스케줄 | `trading-signal-poll` — `cron(3,23,43 9-15 ? * MON-FRI *)` KST |
| 스케줄 | `trading-signal-backfill` — `cron(38 16 ? * MON-FRI *)` KST |
| 스케줄 | `trading-signal-news` — `cron(45 16 ? * MON-FRI *)` KST |
| 스케줄 | `trading-signal-disclosure` — `cron(15 20 ? * MON-FRI *)` KST, `{"days":7}` |
| 스케줄 | `trading-signal-flow` — `cron(30 20 ? * MON-FRI *)` KST |

키는 Lambda 환경변수 `SUPABASE_URL` / `SUPABASE_KEY`(service_role 또는 `sb_secret_`) /
`DART_KEY`(공시)에 있다. 저장소에는 넣지 않는다.

공시는 검증에서 살아남은 유일한 지표(IR)의 소스라 멈추면 화면의 가점 근거가
조용히 빈다. `--days 7` 증분으로 매일 20:15 에 돈다 — 전량(2019~)은 20페이지씩
긁어 매일 돌리기엔 무겁고 DART 일일 한도(2만건)도 있다. 실측 335종목 52초.
RLS가 켜져 있고 정책이 없어서 publishable 키로는 401이 난다.

수동 실행:
```
aws lambda invoke --function-name trading-signal-collect \
  --cli-binary-format raw-in-base64-out --payload '{"cmd":"backfill"}' /dev/stdout
```

로컬이 없으면 **Actions → lambda → Run workflow** 로 배포·실행한다.
Secrets 에 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` 가 필요하다
(`lambda:UpdateFunctionCode` 와 `lambda:InvokeFunction` 만 있으면 된다).

**`price_backfill` 은 한 번에 안 끝난다.** 189종목 × 20페이지 ≈ 3,780요청 ≈ 19분인데
람다 하드 상한이 15분이다. `batches` 를 10 정도로 주면 워크플로가 조각내어
여러 번 부른다. 조각은 연속 구간이 아니라 stride 로 나뉘어 크기가 고르다.

```
{"cmd":"price_backfill","batches":10,"batch":3,"pages":20}
{"cmd":"fin","codes":["005930","000660"]}
```

## 화면

- 아티팩트(개인용): 뷰어의 Supabase 커넥터로 읽어 매일 자동 갱신
- Vercel: https://trading-signal-wine.vercel.app/

`web/` 이 Vercel 프로젝트다. `web/api/data.js` 가 service_role 키를 서버에만 두고
`page_live` 뷰를 프록시한다. 브라우저는 키를 못 본다.
`?part=closed` 는 청산 이력(`page_closed`)만 돌려준다 — 본 응답의 41%라 탭 열 때만 받는다.
`?part=stock&code=` 는 종목 하나의 상세(`stock_detail`)다 — 진행중·청산 행을 탭할 때 받는다.

매수 목록은 **과열도 낮은 순**이다. 4축 진입 점수(수익성·밸류·타이밍·규모)는
6,369 라운드에서 무효로 확인돼 걷어냈다 — 국면 따라 부호가 뒤집힌다. 대신 728일
일내 랭킹 검정에서 살아남은 것만 점수로 쓴다: **IR 공시 가점**(+3.11%p, 8년 연속
양수), **1년 최저권 가점**(+1.4~2.5%p, 두 표본 일치), **저가주 가점**(5천 미만, +1.70%p,
13년 중 12년), **1년 −40%↓ 가점**(+2.38%p), **과열도 감점**(20일 밴드위치·20일선 이격·
매물대 대비). 검증된 조건이 셋 이상 겹치면 **검증 3/4** 배지(+2.97%p, 승률 72%). 수급·펀더멘탈·공급계약·뉴스·거래량은 회색 정보 배지로만 남긴다. 근거는 [`docs/backtest.md`](docs/backtest.md).

탭은 신호의 일생 순서다 — **오늘 매수 → 진행중 → 오늘 매도 → 청산**. 오늘 매수·매도는
`trade_date = current_date` 라 하루만 살고, 진행중은 "마지막 신호가 B인 종목"의 현재
상태(한 종목 한 행), 청산은 `signal_round` 의 최근 30일 종료 라운드다. 매도 결과를
되짚는 창구가 청산 탭이다.

화면은 모바일 우선이다. 매수 행 하나에는 결정에 필요한 것만 둔다 — 이름·현재가·
신호가 괴리·과열도·검증 배지·지지/저항 — 행을 탭하면 상세 시트(3축·재무·수급·
매집 분포·매물대·공시·뉴스)가 뜬다. 용어 설명은 `?` 툴팁 대신 헤더의 `?` 로 여는
**사전**(`<dialog>`)에 모았고, 상세의 점선 밑줄 라벨을 누르면 그 항목으로 간다.
검증 통계(승률·기대값·시장대비)도 사전 맨 위에 있다. 설계 기록은
[`docs/superpowers/specs/2026-09-03-mobile-redesign-design.md`](docs/superpowers/specs/2026-09-03-mobile-redesign-design.md).

폭 680px 아래에서는 표가 한 줄씩 카드로 접힌다. 칸이 10~11개라 가로 스크롤로는
못 읽어서, 각 값에 칸 이름을 붙이고(`td::before` + `data-label`) 종목·코드·시장을
카드 제목 줄로 올린다. 코드·시장 칸은 그때 숨는다. 검색창은 16px 이다 — iOS 는
그 아래면 포커스 때 화면을 확대한다. 한글과 한 줄에 놓이는 숫자는 Mono 를 쓰지 않는다:
Plex Mono 숫자는 대문자 높이만 차지하고 한글은 em 박스를 채워서 숫자가 떠 보인다.

★ 관심 종목은 브라우저 `localStorage` 에만 있다(`fav.codes`, 알림 확인은 `fav.seen`).
서버에 사용자 개념이 없어서 폰과 PC 가 따로 논다. 공유하려면 테이블이 하나 더 필요하다.
관심 종목이 매도되면 페이지 맨 위에 알림이 뜨고, × 를 누를 때까지 남는다.

`page_live` 는 전부 `current_date` 기준인데 DB 타임존이 UTC다. 그래서 날짜가 넘어가는
시점이 09:00 KST(장 시작)이고, 첫 폴링 09:03 까지 3분간은 오늘 매수가 0건이다.
00:00~09:00 KST 에는 아직 전날 날짜로 뜬다.

토큰 게이트는 껐다. 토큰을 URL 에 두면 페이지의 뉴스 링크를 클릭할 때
`Referer` 로 그 주소가 언론사 서버에 넘어가 의미가 없다. 대신
`Referrer-Policy: no-referrer` 로 주소 자체가 안 새게 했다.
다시 켜려면 `vercel env add ACCESS_TOKEN` 후 `?k=` 로 접속하면 된다.

**Supabase 뷰는 전부 `security_invoker = on`.** 끄면 뷰가 소유자 권한으로 돌아
하위 테이블의 RLS를 우회하고, publishable(공개) 키로 데이터가 통째로 읽힌다.
실제로 그 상태였고 이 커밋에서 막았다.

### 배포 — Vercel Git 연동

`main` 에 푸시되면 Vercel 이 알아서 올린다. 저장소에 워크플로 파일은 없다 —
Vercel 대시보드에서 `KooYS/trading-signal` 을 붙여둔 것이고, 설정은 거기에만 있다.

| 설정 | 값 |
|---|---|
| Root Directory | `web` — 저장소 루트엔 `index.html` 이 없다 |
| Production Branch | `main` |
| 프로젝트 | `trading-signal` (팀 AMP) |

**연동만으로는 배포가 안 뜬다.** 붙인 시점의 HEAD 를 소급해서 올리지 않고
다음 푸시부터 돈다. 지금 당장 올리려면 아무 커밋이나 `main` 에 넣거나
CLI 를 쓴다.

```
vercel deploy --prod        # web/ 에서
```

`.vercel/` 은 커밋하지 않는다(로컬 링크 정보).
