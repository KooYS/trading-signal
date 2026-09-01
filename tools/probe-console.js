/* 토스 사이트 콘솔에 그대로 붙여넣으면 되는 판본.
 *
 * 파이썬도 저장소도 필요 없다. https://www.tossinvest.com 아무 페이지나 연 뒤
 * F12 -> Console 에 통째로 붙여넣고 엔터. 같은 오리진이라 CORS 도 안 걸리고,
 * 무엇보다 국내 IP 에서 나가므로 해외 러너가 막히는 경우와 무관하다.
 *
 * 끝나면 결과가 클립보드에 복사된다(안 되면 콘솔 출력을 긁으면 된다).
 */
(async () => {
  const CODE = "005930";                     // 다른 종목 보려면 여기만 바꾼다
  const B = "https://wts-info-api.tossinvest.com/api";
  const log = [];
  const say = (s = "") => { log.push(s); console.log(s); };

  const call = async (path, body) => {
    try {
      const r = await fetch(B + path, {
        method: body === undefined ? "GET" : "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const t = await r.text();
      try { return [r.status, JSON.parse(t)]; } catch { return [r.status, t.slice(0, 300)]; }
    } catch (e) { return [null, String(e)]; }
  };

  /* 응답 어디에 날짜가 박혀 있을지 몰라 통째로 훑는다 */
  const dates = (o, acc = []) => {
    if (Array.isArray(o)) o.forEach(v => dates(v, acc));
    else if (o && typeof o === "object") Object.values(o).forEach(v => dates(v, acc));
    else if (typeof o === "string" && /^[12]\d{3}[-/.]?\d{2}/.test(o)) acc.push(o.slice(0, 10));
    return acc;
  };

  const report = (label, st, pl, snip = 220) => {
    if (st !== 200) return say(`  X ${label} -> ${st} ${String(pl).slice(0, 140)}`);
    const res = pl && pl.result !== undefined ? pl.result : pl;
    const d = dates(res).sort();
    say(`  O ${label} -> 200${d.length ? `  기간 ${d[0]} ~ ${d[d.length - 1]} (날짜 ${d.length}개)` : ""}`);
    say(`      ${JSON.stringify(res).slice(0, snip)}`);
  };

  say(`=== 토스 wts-info-api 점검 (종목 ${CODE}) ===`);
  say();
  say("[1] 일봉 - 얼마나 소급되나  (밴드/소급검증의 핵심)");
  for (const n of [100, 1000, 3000, 10000]) {
    const [st, pl] = await call(`/v1/c-chart/kr-s/A${CODE}/day:1?count=${n}`);
    report(`count=${n}`, st, pl, 200);
  }

  say();
  say("[2] 분기 재무 - 밴드 재료 (POST, 본문 스키마 미상이라 빈 본문으로 타진)");
  for (const p of [
    `/v2/stock-infos/revenue-and-net-profit/A${CODE}`,
    `/v2/stock-infos/operating-income/A${CODE}`,
    `/v2/companies/A${CODE}/financial-statements/comprehensive`,
    `/v2/companies/A${CODE}/financial-statement-records`,
  ]) { const [st, pl] = await call(p, {}); report(p, st, pl); }

  say();
  say("[3] 회귀 확인 - 이미 쓰고 있는 것들");
  for (const p of [
    `/v1/stock-detail/ui/wts/A${CODE}/investment-indicators`,
    `/v2/stock-infos/A${CODE}/overview`,
    `/v1/stock-infos/trade/trend/trading-trend?productCode=A${CODE}&size=5`,
  ]) { const [st] = await call(p); say(`  ${st === 200 ? "O" : "X"} ${p} -> ${st}`); }

  const text = log.join("\n");
  try { copy(text); say("\n(클립보드에 복사됨)"); } catch { say("\n(콘솔 출력을 긁어서 복사하세요)"); }
})();
