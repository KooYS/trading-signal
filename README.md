# 주식매매신호 (trading-signal)

씽크풀 **라씨 AI매매신호**(오늘의 매수·매도, 종목별 매수가·매매내역)를 인증 없이 순수 API 콜로 수집하기 위한 개인 프로젝트.

## 문서

- [`docs/thinkpool-signal-api.md`](docs/thinkpool-signal-api.md) — 엔드포인트·인증 모델·응답 스키마 역설계 스펙 (라이브 검증 완료)

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
python3 collect.py backfill   # 오늘 종목 최근 이력 (--full 로 전 페이지)
```

Supabase 프로젝트 `trading-signal` (`fvwwxhdufcqpcyysfdgg`, ap-northeast-2).
테이블 `signal` — 스키마·설계 근거는 [`schema.sql`](schema.sql).

RLS 켜져 있고 정책이 없다 = **service_role 키만 쓴다.** 레포 Settings → Secrets에 등록:

- `SUPABASE_URL` = `https://fvwwxhdufcqpcyysfdgg.supabase.co`
- `SUPABASE_KEY` = service_role 키 (대시보드 Settings → API Keys)

GitHub Actions가 평일 20분마다 `poll`, KST 16:35에 `backfill` 을 돈다.

라운드(B→S 한 사이클) 분석은 `signal_round` 뷰를 쓴다. 같은 날 B/S가 동시에 나는
케이스가 20건 있고 순서가 섞여 있어서, 날짜로 lag() 짝짓기를 하면 틀린다.
