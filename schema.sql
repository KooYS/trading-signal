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

-- 투자자별 매매동향 (네이버 금융 frgn). 일별 20행씩 받아 누적.
create table if not exists flow (
  stock_code   text not null,
  trade_date   date not null,
  close_price  integer, change_rate numeric(8,2), volume bigint,
  inst_net     bigint,            -- 기관 순매매량 (+매수 / -매도)
  foreign_net  bigint,            -- 외국인 순매매량
  foreign_hold bigint, foreign_rate numeric(6,2),
  collected_at timestamptz not null default now(),
  primary key (stock_code, trade_date)
);
create index if not exists flow_code_date_idx on flow (stock_code, trade_date desc);
alter table flow enable row level security;

alter table fundamental add column if not exists market text;

-- ⚠️ buy_score 는 fundamental_latest 가 아니라 '신호 날짜 이하의 최근 스냅샷'을 조인해야 한다.
--    최신을 붙이면 내일 오늘 신호가 내일 지표로 점수 매겨져 과거 검증이 불가능해진다.
--    전체 정의는 Supabase 마이그레이션 fix_asof_join_and_add_flow_v2 참조.
