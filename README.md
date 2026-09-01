# 주식매매신호 (trading-signal)

씽크풀 **라씨 AI매매신호**(오늘의 매수·매도, 종목별 매수가·매매내역)를 인증 없이 순수 API 콜로 수집하기 위한 개인 프로젝트.

## 문서

- [`docs/thinkpool-signal-api.md`](docs/thinkpool-signal-api.md) — 엔드포인트·인증 모델·응답 스키마 역설계 스펙 (라이브 검증 완료)
- [`docs/google-news-rss.md`](docs/google-news-rss.md) — Google News RSS 스펙. 키 없이 정적 수집, 날짜 창으로 무제한 소급
- [`docs/toss-invest-api.md`](docs/toss-invest-api.md) — 토스증권 wts-info-api 스펙. PER/PBR/ROE·시총·52주·매출구성, 인증 불필요

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
python3 collect.py flow       # 외국인·기관 순매매 20일치 (네이버 금융)
```

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
| Lambda | `trading-signal-collect` (python3.13/arm64, 300s, 256MB) |
| 실행 역할 | `trading-signal-collect-role` |
| 스케줄러 역할 | `trading-signal-scheduler-role` (해당 함수만 invoke) |
| 스케줄 | `trading-signal-poll` — `cron(3,23,43 9-15 ? * MON-FRI *)` KST |
| 스케줄 | `trading-signal-backfill` — `cron(38 16 ? * MON-FRI *)` KST |

키는 Lambda 환경변수 `SUPABASE_URL` / `SUPABASE_KEY`(service_role 또는 `sb_secret_`)에 있다.
RLS가 켜져 있고 정책이 없어서 publishable 키로는 401이 난다.

수동 실행:
```
aws lambda invoke --function-name trading-signal-collect \
  --cli-binary-format raw-in-base64-out --payload '{"cmd":"backfill"}' /dev/stdout
```

## 화면

- 아티팩트(개인용): 뷰어의 Supabase 커넥터로 읽어 매일 자동 갱신
- Vercel: https://trading-signal-wine.vercel.app/

`web/` 이 Vercel 프로젝트다. `web/api/data.js` 가 service_role 키를 서버에만 두고
`page_live` 뷰를 프록시한다. 브라우저는 키를 못 본다.

탭은 신호의 일생 순서다 — **오늘 매수 → 진행중 → 오늘 매도 → 청산**. 오늘 매수·매도는
`trade_date = current_date` 라 하루만 살고, 진행중은 "마지막 신호가 B인 종목"의 현재
상태(한 종목 한 행), 청산은 `signal_round` 의 최근 30일 종료 라운드다. 매도 결과를
되짚는 창구가 청산 탭이다.

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

```
vercel deploy --prod        # web/ 에서
```
