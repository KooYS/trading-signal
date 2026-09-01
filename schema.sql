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

-- 화면용 단일 JSON: page_live. 정의는 Supabase 마이그레이션
-- page_live_add_closed_rounds_and_buy_context 참조.
--   buys/sells   = trade_date = current_date (하루만 산다)
--   open         = open_position 중 buy_date < current_date
--   closed       = signal_round 의 최근 30일 (매도 탭이 사라진 뒤 결과를 되짚는 곳)
-- ⚠️ 전부 current_date 기준인데 DB 타임존이 UTC다. 날짜가 넘어가는 순간이
--    09:00 KST = 장 시작이고, 00:00~09:00 KST 에는 전날로 뜬다.
