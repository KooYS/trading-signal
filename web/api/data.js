// 대시보드 데이터 프록시.
// service_role 키는 여기(서버)에만 있고 브라우저로 내려가지 않는다.
// Supabase 뷰는 security_invoker 라 RLS가 걸려 있어 공개 키로는 못 읽는다.
export default async function handler(req, res) {
  // ACCESS_TOKEN 을 설정하면 ?k= 로 게이트를 건다. 없으면 열어둔다.
  // 토큰을 URL 에 두면 외부 링크 클릭 시 Referer 로 새므로,
  // 그걸 막는 Referrer-Policy: no-referrer 를 vercel.json 에 함께 건다.
  const secret = process.env.ACCESS_TOKEN;
  if (secret && req.query.k !== secret) {
    return res.status(401).json({ error: "unauthorized" });
  }
  const url = `${process.env.SUPABASE_URL}/rest/v1/page_live?select=data`;
  const key = process.env.SUPABASE_KEY;
  try {
    const r = await fetch(url, { headers: { apikey: key, Authorization: `Bearer ${key}` } });
    if (!r.ok) return res.status(502).json({ error: "supabase", status: r.status });
    const rows = await r.json();
    // 신호는 20분마다 갱신된다. 브라우저에도 60초를 주면 탭 전환·새로고침이
    // 네트워크 없이 즉시 뜬다. CDN 은 60초 신선 + 5분간 stale 허용.
    res.setHeader("Cache-Control", "public, max-age=60, s-maxage=60, stale-while-revalidate=300");
    return res.status(200).json(rows[0]?.data ?? null);
  } catch (e) {
    return res.status(502).json({ error: String(e).slice(0, 120) });
  }
}
