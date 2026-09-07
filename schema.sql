-- 라씨 매매신호 원장. 한 행 = 한 신호 이벤트(불변).
-- PK: 종목 + 날짜 + 매매구분. 시각은 PK가 아니다 —
-- TR_SIGNAL07(과거 이력)은 날짜만 주고 시각을 안 주기 때문에,
-- 시각을 PK에 넣으면 백필 행과 폴링 행이 중복된다.
create table if not exists signal (
  stock_code   text    not null,
  trade_date   date    not null,
  trade_flag   char(1) not null check (trade_flag in ('B','S')),
  stock_name   text    not null,
  trade_time   time,                 -- 당일 폴링에서만 확보. 백필 행은 null
  trade_price  integer,              -- B=매수가, S=매도가
  profit_rate  numeric(8,2),         -- S행만: 해당 B→S 라운드 실현수익률
  updated_at   timestamptz not null default now(),
  primary key (stock_code, trade_date, trade_flag)
);

create index if not exists signal_date_idx on signal (trade_date desc);

alter table signal enable row level security;
-- 정책 없음 = service_role 키만 접근. 수집기는 service_role로 붙는다.

-- 라운드(B→S 한 사이클) 뷰.
-- 날짜 순서로 짝지으면 안 된다: 같은 날 B와 S가 동시에 나는 경우가 20건 있고
-- 그 순서가 B→S(당일청산)와 S→B(청산 후 재진입)로 섞여 있다.
-- 대신 profit_rate로 매수가를 역산해 짝을 찾는다. 5167/5167 전건 매칭 확인.
create or replace view signal_round as
select s.stock_code,
       s.stock_name,
       b.trade_date  as buy_date,
       b.trade_price as buy_price,
       s.trade_date  as sell_date,
       s.trade_price as sell_price,
       s.profit_rate,
       s.trade_date - b.trade_date as holding_days
from signal s
cross join lateral (
  select b.trade_date, b.trade_price
  from signal b
  where b.stock_code = s.stock_code
    and b.trade_flag = 'B'
    and b.trade_date <= s.trade_date
    and abs(b.trade_price * (1 + s.profit_rate/100.0) - s.trade_price)
        <= greatest(1.0, s.trade_price * 0.0002)
  order by b.trade_date desc
  limit 1
) b
where s.trade_flag = 'S';

-- Google News RSS 수집 기사. 스펙: docs/google-news-rss.md
-- 같은 기사가 여러 종목 검색에 걸릴 수 있어(나열 기사) PK에 종목을 포함한다.
create table if not exists news (
  stock_code   text        not null,
  guid_hash    text        not null,          -- md5(guid). guid가 126~158자 가변이라
  published_at timestamptz not null,
  title        text        not null,
  source       text,                          -- 언론사명 (RSS <source>)
  url          text        not null,          -- news.google.com 리다이렉트 (원본 아님)
  src_api      text        not null default 'gnews',
  collected_at timestamptz not null default now(),
  primary key (stock_code, guid_hash)
);

create index if not exists news_code_time_idx on news (stock_code, published_at desc);
create index if not exists news_time_idx      on news (published_at desc);

alter table news enable row level security;

-- 종목 펀더멘탈 스냅샷 (토스증권). 스펙: docs/toss-invest-api.md
-- PER·PBR은 주가에 연동돼 매일 바뀌므로 날짜별로 쌓는다. 하루 1행.
create table if not exists fundamental (
  stock_code    text not null,
  as_of         date not null,
  per numeric(10,2), pbr numeric(10,2), psr numeric(10,2),
  roe numeric(10,2), eps numeric(14,2), bps numeric(14,2),
  div_yield     numeric(8,4),           -- 비율 그대로 (0.0169 = 1.69%)
  market_cap    bigint,
  close_price   integer, high_52w integer, low_52w integer,
  industry      text, ceo text, listed_on date, shares_out bigint,
  sales_mix     jsonb,                  -- [{business, ratio}]
  collected_at  timestamptz not null default now(),
  primary key (stock_code, as_of)
);
create index if not exists fundamental_code_idx on fundamental (stock_code, as_of desc);
alter table fundamental enable row level security;

create or replace view fundamental_latest as
select distinct on (stock_code) *,
       case when high_52w > low_52w
            then round(100.0 * (close_price - low_52w) / (high_52w - low_52w), 1) end as pos_52w
from fundamental order by stock_code, as_of desc;

-- 투자자별 매매동향 (토스 trading-trend). 60일치.
-- 네이버 frgn 도 같은 데이터를 주지만 하루 늦고 20일치라 토스를 쓴다.
-- 당일치는 장마감 직후 잠정값이고 20시경 확정된다 → src_updated_at 로 판단.
create table if not exists flow (
  stock_code   text not null,
  trade_date   date not null,
  close_price  integer, change_rate numeric(8,2), volume bigint,
  indiv_net    bigint,            -- 개인 순매수
  inst_net     bigint,            -- 기관 순매수 (+매수 / -매도)
  foreign_net  bigint,            -- 외국인 순매수
  -- 기관 세부 7주체. 합 = inst_net (2,499행 전건 검증)
  fin_inv_net  bigint,            -- 금융투자(증권)
  insurance_net bigint,           -- 보험
  trust_net    bigint,            -- 투신
  pe_fund_net  bigint,            -- 사모
  bank_net     bigint,            -- 은행
  other_fin_net bigint,           -- 기타금융
  pension_net  bigint,            -- 연기금
  other_corp_net bigint,          -- 기타법인 (기관 합계 미포함)
  -- 외국인은 주체별 분해가 없다(단일 집계)
  foreign_buy  bigint, foreign_sell bigint,
  foreign_hold bigint, foreign_limit bigint, foreign_rate numeric(6,2),
  src_updated_at timestamptz,
  collected_at timestamptz not null default now(),
  primary key (stock_code, trade_date)
);
create index if not exists flow_code_date_idx on flow (stock_code, trade_date desc);
alter table flow enable row level security;

alter table fundamental add column if not exists market text;

-- ⚠️ buy_score 는 fundamental_latest 가 아니라 '신호 날짜 이하의 최근 스냅샷'을 조인해야 한다.
--    최신을 붙이면 내일 오늘 신호가 내일 지표로 점수 매겨져 과거 검증이 불가능해진다.
--    전체 정의는 Supabase 마이그레이션 fix_asof_join_and_add_flow_v2 참조.

-- 일별 시세 (토스 c-chart). 스펙: docs/toss-invest-api.md
-- flow 는 60일치뿐이라 소급 검증이 안 됐다. 이건 그 한계를 푸는 테이블이다.
-- ⚠️ 한 번에 다 안 온다. count 상한이 300~499 사이(300 OK, 500은 400)고,
--    응답의 nextDateTime 을 ?from= 으로 되돌려줘야 그 이전 구간이 온다.
create table if not exists price (
  stock_code   text not null,
  trade_date   date not null,
  open_price   integer, high_price integer, low_price integer, close_price integer,
  base_price   integer,               -- 기준가(전일 종가)
  volume       bigint,
  amount       bigint,                -- 거래대금(원)
  collected_at timestamptz not null default now(),
  primary key (stock_code, trade_date)
);
create index if not exists price_code_date_idx on price (stock_code, trade_date desc);
create index if not exists price_date_idx      on price (trade_date desc);
alter table price enable row level security;

-- 분기 실적 (토스). 본문 {"range": 5} 로 5년 20분기. 기본이 3년이라 반드시 실어야 한다.
-- 매수 밴드용이다. 지금 buy_ranked 의 밸류 축은 전 종목 공통 절대기준
-- (PBR<=0.5 → 25점)이라 철강주와 바이오를 같은 자로 잰다. 그래서 국면 따라
-- 부호가 뒤집혔다(6·7월 상관 +0.271 / 8월 +0.059). '이 종목의 자기 이력 대비
-- 지금 어디인가' 를 재려면 이 시계열이 있어야 한다.
create table if not exists financials (
  stock_code        text not null,
  period            text not null,     -- 분기말 'YYYY-MM'
  revenue           bigint,            -- 매출(원)
  net_profit        bigint,            -- 순이익(원)
  -- 증감률은 전분기가 0 근처면 임의로 커진다. 자릿수를 묶어두면 overflow 로 400 이 난다
  net_profit_ratio  numeric,           -- 순이익률(%)
  net_profit_growth numeric,           -- 순이익 증감률(%)
  operating_income  bigint,            -- 영업이익(원)
  collected_at      timestamptz not null default now(),
  primary key (stock_code, period)
);
create index if not exists financials_code_idx on financials (stock_code, period desc);
alter table financials enable row level security;

-- 신호에 한 번이라도 등장한 종목. 오늘 목록(today_codes)과 달리 과거 검증용이다.
create or replace view signal_stock as
select stock_code, max(stock_name) as stock_name,
       min(trade_date) as first_date, max(trade_date) as last_date, count(*) as signals
from signal group by stock_code;

-- DART corp_code ↔ 종목코드. DART 는 6자리 종목코드로 조회가 안 되고
-- 자기 8자리 corp_code 만 받는다. 대응표가 corpCode.xml 인데 ZIP 으로 온다.
create table if not exists dart_corp (
  corp_code    text primary key,
  stock_code   text,
  corp_name    text,
  collected_at timestamptz not null default now()
);
create index if not exists dart_corp_stock_idx on dart_corp (stock_code);
alter table dart_corp enable row level security;

-- 공시. 구글뉴스로는 호재·악재가 같은 +1 로 세어져서 '공시 소재' 가설을
-- 잴 수 없었다. 공시는 유형이 제목에 박혀 있어 부호를 가를 수 있다.
-- ⚠️ report_nm 을 날것으로 둔다. 분류는 뷰에서 — 기준을 바꿀 때마다 재수집하지 않으려고.
create table if not exists disclosure (
  rcept_no     text primary key,     -- 접수번호. 공시 1건 1행
  stock_code   text not null,
  corp_code    text,
  rcept_dt     date not null,
  report_nm    text not null,        -- 공시 제목
  flr_nm       text,                 -- 제출인
  corp_cls     text,                 -- Y 유가 / K 코스닥 / N 코넥스 / E 기타
  rm           text,                 -- 비고(정정·첨부 등)
  collected_at timestamptz not null default now()
);
create index if not exists disclosure_code_dt_idx on disclosure (stock_code, rcept_dt desc);
create index if not exists disclosure_dt_idx      on disclosure (rcept_dt desc);
alter table disclosure enable row level security;

-- ── 검증용 파생 객체 ────────────────────────────────────────────────
-- 검증 결과와 방법은 docs/backtest.md 참조.
-- ⚠️ matview 는 price 를 채운 뒤 반드시 refresh 해야 한다. 안 하면 화면이
--    조용히 옛 지표로 점수를 매긴다.

-- 기술적 지표. ⚠️ close_price 가 integer 라 ::numeric 을 빼면 정수 나눗셈이 되어
-- 6900/7275 = 0 → -100% 가 나온다. 실제로 ret5·ret20·vs_hi60 이 그렇게 깨져 있었다.
create materialized view if not exists tech_daily as
with p as (
  select stock_code, trade_date, close_price c, volume v,
    avg(close_price) over w5 ma5, avg(close_price) over w20 ma20,
    avg(close_price) over w60 ma60, avg(volume) over w20 vol20,
    max(close_price) over w20 hi20, min(close_price) over w20 lo20,
    max(close_price) over w60 hi60,
    sum(close_price::numeric * volume) over w60 / nullif(sum(volume) over w60, 0) vwap60,
    lag(close_price, 5)  over (partition by stock_code order by trade_date) c5,
    lag(close_price, 20) over (partition by stock_code order by trade_date) c20,
    count(*) over w60 n60
  from price
  window w5  as (partition by stock_code order by trade_date rows between 4  preceding and current row),
         w20 as (partition by stock_code order by trade_date rows between 19 preceding and current row),
         w60 as (partition by stock_code order by trade_date rows between 59 preceding and current row)
)
select stock_code, trade_date, c close_price,
  round(100.0*(c::numeric/nullif(ma5,0)  - 1), 2) gap_ma5,
  round(100.0*(c::numeric/nullif(ma20,0) - 1), 2) gap_ma20,
  round(100.0*(c::numeric/nullif(ma60,0) - 1), 2) gap_ma60,
  (ma5 > ma20 and ma20 > ma60) aligned,
  round((v::numeric / nullif(vol20,0)), 2) vol_ratio,
  round(100.0*(c - lo20)::numeric / nullif(hi20 - lo20,0), 1) pos20,   -- 20일 밴드 내 위치
  round(100.0*(c::numeric/nullif(hi60,0) - 1), 2) vs_hi60,
  round(100.0*(c::numeric/nullif(vwap60,0) - 1), 2) vs_vwap60,          -- 매물대 대용
  round(100.0*(c::numeric/nullif(c5,0)  - 1), 2) ret5,
  round(100.0*(c::numeric/nullif(c20,0) - 1), 2) ret20
from p where n60 >= 60;
create index if not exists tech_idx on tech_daily (stock_code, trade_date desc);

-- 등가중 시장지수. 초과수익(alpha) 계산의 기준선이다.
-- 액면분할·병합으로 튀는 값을 막으려고 일간수익률 ±35% 밖은 버린다.
create materialized view if not exists mkt_index as
with ret as (
  select stock_code, trade_date,
    close_price::numeric/nullif(lag(close_price) over (partition by stock_code order by trade_date),0)-1 r
  from price
), daily as (select trade_date, avg(r) mkt_r from ret where r between -0.35 and 0.35 group by 1)
select trade_date, exp(sum(ln(1+mkt_r)) over (order by trade_date))::numeric lvl
from daily where mkt_r > -1;
create index if not exists mkt_idx on mkt_index (trade_date);

-- 매일 08:30 KST(23:30 UTC, 일~목) 전일 시세를 채우고 지표를 다시 계산한다.
-- 09:03 첫 폴링 전에 끝난다. 안 하면 과열도가 조용히 옛 데이터로 매겨진다.
-- 신규 종목은 하루 0.05건(0.6%)이라 신호 목록 전체를 미리 받아둬도 거의 안 샌다.
--   create extension pg_cron;
--   select cron.schedule('daily-tech', '30 23 * * 0-4', $$select daily_tech_refresh()$$);
--
-- 신규 종목은 당일 지표가 빈다 — 크론은 08:30 인데 신호는 09:03 에 나오고,
-- 그때 처음 보는 종목이면 price 에 아무것도 없다(하루 0.05건, 전체의 0.6%).
-- 그래서 장중에도 구멍만 메운다. 보통 0종목이라 거의 공짜다.
--   select cron.schedule('intraday-fill', '0 0-6 * * 1-5', $$select fill_missing_tech()$$);
-- 수집은 DB 안에서 한다 — http 확장으로 토스를 직접 부른다(Supabase 도 서울이라
-- 지역 제한에 안 걸린다). Lambda 없이도 지표가 유지되게 하려는 것이다.

-- ⚠️ page_live 와 buy_today 는 tech_daily 에 의존한다. tech_daily 를
--    drop ... cascade 로 갈아끼우면 이 둘이 딸려 지워지고, 화면은 /api/data 404 를
--    받는다(실제로 겪었다). 재생성할 땐 두 뷰를 반드시 같이 다시 만들 것.

-- 화면용 단일 JSON: page_live. 정의는 Supabase 마이그레이션
-- page_live_add_closed_rounds_and_buy_context 참조.
--   buys/sells   = trade_date = current_date (하루만 산다)
--   open         = open_position 중 buy_date < current_date
--   closed       = signal_round 의 최근 30일 (매도 탭이 사라진 뒤 결과를 되짚는 곳)
-- ⚠️ 전부 current_date 기준인데 DB 타임존이 UTC다. 날짜가 넘어가는 순간이
--    09:00 KST = 장 시작이고, 00:00~09:00 KST 에는 전날로 뜬다.
-- ⚠️ /api/data 는 page_live 를 직접 읽지 않는다. 뷰를 요청마다 돌리면 warm 1.6s 에
--    버퍼 260,356 페이지(2.0GB, shared_buffers 의 9배)라 동시 요청 몇 개면 authenticator 의
--    statement_timeout 8s 를 넘겨 57014 → PostgREST 500 → 502 가 났다(10개 동시로 100% 재현).
--   page_cache (table)  key='live', data, updated_at   ← pg_cron 'page-live-refresh' 가 5분마다 update
--    matview 가 아니라 테이블인 건 통짜 refresh 의 AccessExclusiveLock 때문이다. 실측 7.98초였고
--    그동안 읽는 쪽이 막히면 같은 타임아웃에 다시 걸린다. update 는 읽기를 안 막는다(hold_band 와 같은 이유).
--    5분인 건 수집(20분)과 어긋나면 신선도가 40분까지 벌어져서다.

-- 외국인·기관 매집 분포. 1년, 하루 순매수·순매도량을 그날 저가~고가에 균등 분산해
-- 현재가 기준 2.5% 격자(k=-12..11)에 배분. 산 것·판 것을 따로 둔다 — 대부분 산 만큼 팔았다.
-- ⚠️ 점수 아님 — 네 방식 전부 t<2 또는 단조성 없음(docs/backtest.md §3).
--   accum_band  (matview)  bucket(k), price_lo/hi, buy_f/buy_i/sell_f/sell_i, tot_* (1년 합계)
-- 남은 물량의 가격대 구성 — "외국인이 어디에 물려 있고 어디에 들고 있나".
-- 1년 창 안의 순매수를 그날 저가~고가 칸에 로트로 쌓고, 순매도한 날은 들고 있던 로트 전체를
-- 같은 비율로 깎는다(평균단가 모델). 창 이전 보유분은 단가를 모른다. -13 = 창 아래, 12 = 창 위(물림).
-- matview 가 아니라 테이블이다 — 날짜순 상태 추적이라 plpgsql 루프(hold_band_refresh)로 채운다.
-- ⚠️ 생존계수를 numeric 으로 9만 번 곱하면 자릿수가 폭발해 타임아웃. float8 로 한다.
--   hold_band  (table)  bucket(k), hold_f, hold_i   ← daily_tech_refresh 끝에서 갱신
--   hold_test  (table)  검정용 스냅샷. 2019-04 부터 연속 재생, 매수 신호 직전 위/아래 잔량 + ±10% 안쪽 잔량 (hold_test_run)
--   round_path (matview) 검정용. 라운드 안 최저가/최고가(낙폭·상승폭), 매수 전 60일 평균 거래량. 분석 전용, 일일 갱신 아님
--   feat_round (matview) 검정용 피처 26,317 라운드. 매수일 이전 데이터만(모멘텀·변동성·거래량·지수 국면·종목 이력). 분석 전용
-- 1년·120일·60일 수익률(최근 종가 / N거래일 전 종가). '1년 -40%↓' 배지의 근거. daily_tech_refresh 에서 갱신.
--   mom250 (matview)  ret60, ret120, ret250
-- 종목 하나의 상세. 진행중·청산 행을 탭하면 /api/data?part=stock&code= 로 이 뷰를 한 종목만 읽는다.
-- page_live 에 그 행들의 뉴스·매집·매물대를 싣지 않는 이유는 페이로드다. 과열도는 여기 없다(그날 후보 순위).
--   stock_detail (view)  stock_code, data
-- 수급 데이터 신뢰도. 1년 외인 순매수 합계(%p)와 보유율 변화가 2%p 넘게 어긋나면 차트에 경고.
-- 상장주식수는 시총÷종가 (fundamental.shares_out 은 17종목이 낡았다). 보유율 0 은 결측으로 본다.
--   flow_check (view)  shares, frate, gap_pp
-- 수급 국면. '기관만 매도'가 유일한 후보 (+1.56%p t2.37).
--   flow_regime (matview)  f_sell, i_sell, regime
-- 둘 다 daily_tech_refresh() 에서 concurrently 갱신한다.

-- 수급 이력이 얕은 종목. 일일 backfill 이 이 목록을 40개씩 메운다.
-- flow 수집 창이 120일이라 신규 편입 종목은 밴드가 짧게 그려진다.
-- ⚠️ '덜 받은 것'과 '원래 없는 것'을 구분한다 — price 거래일수 대비 부족분으로
--    판정하므로 신규 상장 종목(상장 이후 전부 있음)은 제외된다. 안 그러면
--    매일 40개 슬롯을 이들이 차지하고 헛돈다.
--   shallow_flow (view)  stock_code, days, available

-- 청산 이력은 본 응답의 41%(71KB)인데 탭을 열 때만 쓴다. 별도 뷰로 뺐다.
-- page_live 에는 배지용 closedCount 만 남긴다. /api/data?part=closed 로 받는다.
--   page_closed (view)  최근 30일 라운드

-- 총거래량 매물대(1년, 현재가 기준 2.5% 격자 24칸 = -26%~+34%)와 거기서 뽑은 지지·저항.
-- accum_band(외국인·기관)와 달리 '누가 샀든' 전체 거래량이라 매물대에 가깝다.
-- 격자가 현재가 기준이라 칸 경계는 클라이언트가 px 와 k 로 되살린다(칸 폭 항상 2.5%).
-- 지지·저항 = 그 쪽 평균의 1.5배(1%~2.5% 로 가둠) 넘는 가장 가까운 칸 위아래 2개.
-- ⚠️ 예측 지표가 아니라 사실 기술이다. 점수에 넣지 않는다. 근거는 docs/backtest.md §5-3.
--   vol_profile (matview)  bucket(k), price_lo/hi, vol, share, days
--   sr_level    (matview)  now_price(px), support, resistance, below_share, out_below, out_above
--                          ← vol_profile 뒤에 갱신
