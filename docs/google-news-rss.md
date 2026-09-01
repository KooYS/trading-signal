# Google News RSS 스펙

> 검증일: 2026-09-01 / 로컬(KR 가정용) + AWS 서울(`3.36.72.238`, AS16509) 양쪽에서 라이브 확인.
> **키 불필요, 정적 XML, 날짜 창으로 무제한 소급 가능.**

공식 문서가 없는 비공식 엔드포인트다. 아래는 전부 실측이며, 구글이 예고 없이 바꿀 수 있다.

---

## 1. 엔드포인트

```
GET https://news.google.com/rss/search
      ?q={검색어}
      &hl=ko          # UI 언어
      &gl=KR          # 국가
      &ceid=KR:ko     # 에디션 (국가:언어) — hl/gl 과 함께 셋 다 넣어야 한국 기사가 온다
```

- 인증 **없음**. API 키, 쿠키, Referer 전부 불필요.
- 응답 `application/xml` (RSS 2.0). **정적이다** — JS 렌더링 없이 본문이 그대로 온다.
- `User-Agent`만 브라우저 문자열로 넣어주면 된다.

> ⚠️ **`https://www.google.com/search?tbm=nws` 는 쓸 수 없다.** HTTP 200이 오지만
> 92KB 전부 JS 로더고 검색어조차 HTML에 없다(등장 횟수 0). 구글 검색 결과는 클라이언트
> 렌더링이라 헤드리스 브라우저가 필요하다. **RSS 경로만 정적으로 열려 있다.**

## 2. 응답 구조

```xml
<item>
  <title>지엔씨에너지, 창사 이래 최대 규모 수주계약 달성...KT에 755억원 - 전기신문</title>
  <link>https://news.google.com/rss/articles/CBMickFVX3lxTE9...</link>
  <guid isPermaLink="false">CBMickFVX3lxTE9NeWRyWWQyMURrS253...</guid>
  <pubDate>Wed, 05 Aug 2026 07:00:00 GMT</pubDate>
  <description>&lt;a href="https://news.google.com/rss/articles/CBMi..."&gt;</description>
  <source url="https://www.전기신문.com">전기신문</source>
</item>
```

| 필드 | 내용 | 비고 |
|---|---|---|
| `title` | 기사 제목 + ` - 언론사명` | 제목 끝에 언론사가 붙는다 |
| `pubDate` | **정확한 발행시각** (RFC 822, GMT) | 상대시각("3일 전") 아님 ★ |
| `guid` | 기사 고유 ID | 126~158자 가변. 100건 내 유니크 확인 |
| `link` | `news.google.com/rss/articles/...` | **원본 URL 아님.** 리다이렉트 |
| `source` | 언론사명 + `url` 속성 | 필터링에 유용 |
| `description` | **쓸모없음** | `<a href>` 태그만. 요약 텍스트 없음 |

**`description`에 본문 요약이 없다는 게 네이버 API와의 가장 큰 차이다.** 제목만으로 판단해야 한다.

## 3. 페이징 — 안 된다. 날짜 창으로 우회한다

```
기본 요청           → 100건 (하드캡)
&start=100          → 100건 (무시됨)
&num=200            → 100건 (무시됨)
&start=50           → 100건 (무시됨)
```

`start` / `num` 파라미터는 **전부 무시된다.** 100건이 상한이다.

대신 **`q`에 날짜 연산자를 넣으면 창이 좁혀진다** — 이게 소급 수집의 열쇠다.

| 연산자 | 예시 | 결과 (지엔씨에너지 기준) |
|---|---|---|
| `when:7d` | `지엔씨에너지 when:7d` | 32건, 최고참 2026-08-26 |
| `when:1y` | `지엔씨에너지 when:1y` | 100건 (캡에 걸림) |
| `after:` + `before:` | `지엔씨에너지 after:2024-03-01 before:2024-04-01` | 7건, 2024-03-19 ~ 03-24 |
| | `... after:2022-06-01 before:2022-07-01` | 7건, 2022-06-12 |
| | `... after:2019-01-01 before:2019-04-01` | 2건, 2019-03-04 ~ 03-05 |

**2019년 기사까지 확인됐다.** 월 단위로 창을 끊으면 종목당 10년치를 전부 받을 수 있다.

```python
q = f"{종목명} after:2024-03-01 before:2024-04-01"
```

날짜는 `YYYY-MM-DD`. `after`는 미포함, `before`도 미포함으로 동작하는 것으로 보이나
경계일 1~2건 차이는 신경 쓰지 말고 **창을 겹치게 잡는 게 안전하다**(upsert라 중복 무해).

## 4. 차단 / 레이트리밋

AWS 서울(`3.36.72.238`, AS16509 Amazon) 에서 **6종목 연속 요청 전부 200**:

```
지엔씨에너지  200  100건  100,889 bytes  1,038ms
디어유        200  100건  101,211 bytes    508ms
삼호개발      200  100건   98,408 bytes    468ms
인스피언      200  100건  102,290 bytes    541ms
닷밀          200  100건  103,176 bytes    491ms
덴티스        200  100건   91,229 bytes    459ms
```

- 데이터센터 IP에서도 **CAPTCHA·429 없음**. `google.com/search`와 정반대다.
- 응답 500ms 내외, 요청당 ~100KB.
- 상한을 찔러보진 않았다. 실사용은 **요청 사이 0.3초 슬립**을 넣어 ~3 req/s 이하로 유지 중.

> 장기 대량 수집 시 429가 뜰 가능성은 남아 있다. 재시도/백오프는 필수.

## 5. 종목명만 쓰면 안 된다 ★ (동명이인 사고)

**검색어는 `"{종목명} {종목코드}"` 로 고정한다.** 종목명만 쓰면 전혀 다른 대상이 들어온다.

실제로 겪은 사고 — `서연`(007860)으로 수집했더니 **아이돌 "튜이드 서연" 기사 100건**이 통째로
저장됐고, 대시보드에서 "근거 있는 신호"로 표시됐다.

```
서연            → 튜이드 서연(아이돌), 공서연(사건) …  회사 기사 0건
"서연" 주가      → 서연이화 · 서연탑메탈  ← 같은 그룹의 다른 상장사. 더 위험하다
서연 코스피 자동차 → 거의 전부 서연이화
서연 007860     → 전부 서연(007860) 본인 ✅
```

그룹 계열사가 섞이는 게 아이돌보다 위험하다. 그럴듯해서 안 걸러진다.

### 코드를 붙이면 기사를 잃지 않나?

**잃는 게 아니라 다르게 고른다.** RSS는 100건 캡이고, 구글은 코드를 AND 조건이 아니라
**랭킹 힌트**로 쓴다. 그래서 이름이 명확한 종목은 거의 안 깎이고, 모호할 때만 강하게 작동한다.

| 종목 | 이름만 | 코드 병기 | 제목 교집합 |
|---|---|---|---|
| SK텔레콤 (017670) | 97 | **95** | 9 |
| 디어유 (376300) | 95 | **88** | 36 |
| 카카오게임즈 (293490) | 97 | **92** | 15 |
| 삼호개발 (010960) | 98 | **23** | 20 |
| 서연 (007860) | 97 | **17** | **0** |

교집합이 낮은 건 두 쿼리가 **수천 건 풀에서 서로 다른 100건씩**을 가져오기 때문이다.
SK텔레콤은 코드 병기로도 "SKT 에어 20만명 돌파", "SKT AI로 통신망 훑는다" 같은
핵심 기사가 그대로 나온다. 종목당 17~95건이면 신호 근거 판단엔 충분하다.

## 6. 노이즈 — 세 종류

실측에서 관측된 패턴이다. **원문을 그대로 저장하고 필터는 나중에** 하는 게 맞다(재수집 불필요).

```
❌ 나열 기사   "8월 31일 주식시장 주요공시"      ← 수십 종목이 한 기사에
               "[52주] 최고가 9개, 최저가 47개"
               "[EBN 데이터센터] 8일 상승 종목 30選"
❌ 오매칭      "영암군 삼호읍 삼포리 개발행위"    ← '삼호'+'개발'이 따로 매칭
               "HD현대삼호"                      ← 부분 문자열
❌ 시세 봇     "삼호개발 주가, 7월 8일 4,460원 6.44% 상승 마감"  ← 자동생성, 정보량 0
✅ 진짜 이벤트 "삼호개발, 두산에너빌리티와 276억 고속도로 계약"
               "[특징주] 삼호개발, 호남 800조 반도체 메가프로젝트 기대감에 급등"
```

거르는 실마리:
- **오매칭** → `q`에 따옴표로 정확일치(`"삼호개발"`)를 걸면 줄어든다.
- **시세 봇** → `source`가 톱스타뉴스·중앙이코노미뉴스 등으로 몰린다. 제목에 `주가,`·`상승 마감` 패턴.
- **나열 기사** → 제목에 날짜+`주요공시`, `종목`, `選`, `[52주]` 등. 본문이 없어 판별은 제목 의존.

## 7. 우리 구현

`collect.py`:

```
python3 collect.py news                      # 오늘 신호 종목 최근 100건 (코드 병기)
python3 collect.py news_backfill 2026-08     # 해당 월 창으로 소급
python3 collect.py news_backfill 2026-06 2026-07 2026-08
```

핵심 함수:

| 함수 | 역할 |
|---|---|
| `fetch_news(name, code, window=None)` | RSS 원문(bytes). 검색어는 `"{name} {code}"` |
| `news_rows(code, name, xml)` | XML → DB 행. `pubDate` RFC822 파싱, `guid` md5 |
| `news(codes_names)` | 최신 수집 → upsert |
| `news_backfill(codes_names, months)` | 월 창 반복 → upsert |

테이블 `news` (스키마는 [`../schema.sql`](../schema.sql)):

```sql
primary key (stock_code, guid_hash)   -- 같은 기사가 여러 종목에 걸릴 수 있다(나열 기사)
guid_hash    md5(guid)                -- guid가 126~158자 가변이라 고정폭으로
published_at timestamptz              -- pubDate를 UTC로
src_api      'gnews'                  -- 나중에 네이버를 섞을 때 구분
```

## 8. 다른 곳에서 쓸 때 — 최소 예제

의존성 없는 순수 stdlib:

```python
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

def gnews(name, code, after=None, before=None):
    q = f"{name} {code}"                     # 코드 병기 필수 — §5 동명이인 사고
    if after:
        q += f" after:{after} before:{before}"
    url = ("https://news.google.com/rss/search"
           f"?q={urllib.parse.quote(q)}&hl=ko&gl=KR&ceid=KR:ko")
    r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    xml = urllib.request.urlopen(r, timeout=30).read()
    out = []
    for it in ET.fromstring(xml).findall(".//item"):
        src = it.find("source")
        out.append({
            "title": it.findtext("title"),
            "published_at": datetime.strptime(
                it.findtext("pubDate"), "%a, %d %b %Y %H:%M:%S %Z"
            ).replace(tzinfo=timezone.utc),
            "source": src.text if src is not None else None,
            "url": it.findtext("link"),
            "guid": it.findtext("guid"),
        })
    return out

# 최신 100건
gnews("지엔씨에너지", "119850")
# 2024년 3월치만
gnews("지엔씨에너지", "119850", "2024-03-01", "2024-04-01")
```

주의 네 가지만 기억하면 된다:

1. **검색어에 종목코드를 반드시 붙일 것** — 종목명만 쓰면 동명이인·계열사가 섞인다 (§5)
2. **100건 캡** — 넘기려면 `after`/`before`로 창을 쪼갤 것
3. **`link`는 원본 URL이 아니다** — `news.google.com` 리다이렉트. 원본이 필요하면 따라가야 함
4. **요약 텍스트 없음** — `description`은 빈 껍데기. 제목이 전부

## 9. 네이버 검색 API와 비교

둘 다 쓸 수 있고 서로를 보완한다. 우리는 소급 범위 때문에 gnews를 택했다.

| | Google News RSS | 네이버 검색 API |
|---|---|---|
| 인증 | **불필요** | Client ID + Secret (무료, 즉시 발급) |
| 한도 | 미상 (차단 관측 안 됨) | 25,000회/일 |
| 1회 최대 | 100건 | 100건 |
| 소급 | **날짜 창으로 사실상 무제한** (2019년 확인) | 최근 1,000건까지 페이징 |
| 발행시각 | 정확 (RFC 822) | 정확 (RFC 822) |
| 본문 요약 | **없음** | **있음** (~200자) |
| 원본 URL | 리다이렉트 | `originallink`로 직접 |
| 언론사명 | `<source>` 제공 | 없음 (도메인에서 파싱) |
| 안정성 | 비공식, 예고 없이 변경 가능 | 공식 API |

요약 텍스트나 원본 URL이 필요해지면 네이버를 얹고 `src_api`로 구분하면 된다.
네이버 엔드포인트: `GET https://openapi.naver.com/v1/search/news.json?query=&display=100&sort=date`
헤더 `X-Naver-Client-Id`, `X-Naver-Client-Secret`.
