// 대시보드 데이터 프록시.
// service_role 키는 여기(서버)에만 있고 브라우저로 내려가지 않는다.
// Supabase 뷰는 security_invoker 라 RLS가 걸려 있어 공개 키로는 못 읽는다.
export default async function handler(req, res) {
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
    // 장중엔 20분마다 갱신되므로 CDN 캐시는 짧게, 갱신 중엔 이전 값 허용
    res.setHeader("Cache-Control", "s-maxage=60, stale-while-revalidate=300");
    return res.status(200).json(rows[0]?.data ?? null);
  } catch (e) {
    return res.status(502).json({ error: String(e).slice(0, 120) });
  }
}
