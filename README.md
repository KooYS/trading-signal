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
