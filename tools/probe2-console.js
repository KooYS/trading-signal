/* 2단계 타진. 1단계에서 나온 것들을 확정한다.
 *
 *   - 일봉 count 상한이 얼마인가
 *   - nextDateTime 을 어떤 파라미터로 돌려주면 다음 페이지가 오는가  ← 소급의 열쇠
 *   - 캔들 한 건의 전체 필드
 *   - 분기 재무 POST 에 5년을 어떻게 요청하는가
 *
 * 1단계와 같은 방법: tossinvest.com 콘솔에 붙여넣기.
 * (붙여넣기가 막히면 콘솔에 allow pasting 먼저 입력)
 */
(async () => {
  const CODE = "005930";
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
      try { return [r.status, JSON.parse(t)]; } catch { return [r.status, t.slice(0, 200)]; }
    } catch (e) { return [null, String(e)]; }
  };
  const res = p => (p && p.result !== undefined ? p.result : p);
  /* 캔들 배열이 어느 키에 있든 찾아낸다 */
  const candles = r => (r && (r.candles || r.chart || r.data)) || (Array.isArray(r) ? r : null);

  say(`=== 2단계 (종목 ${CODE}) ===`);

  say("\n[A] 일봉 count 상한");
  for (const n of [100, 200, 300, 500, 800, 1000]) {
    const [st, pl] = await call(`/v1/c-chart/kr-s/A${CODE}/day:1?count=${n}`);
    const c = st === 200 ? candles(res(pl)) : null;
    say(`  count=${n} -> ${st}${c ? `  실제 ${c.length}건, 가장 오래된 ${c[c.length - 1].dt}` : ""}`);
  }

  say("\n[B] 캔들 한 건의 전체 필드");
  {
    const [, pl] = await call(`/v1/c-chart/kr-s/A${CODE}/day:1?count=3`);
    const r = res(pl), c = candles(r);
    say(`  응답 최상위 키: ${JSON.stringify(Object.keys(r || {}))}`);
    say(`  nextDateTime  : ${JSON.stringify(r && r.nextDateTime)}`);
    say(`  캔들[0]       : ${JSON.stringify(c && c[0])}`);
  }

  say("\n[C] 다음 페이지 커서 — 파라미터 이름 찾기");
  {
    const [, first] = await call(`/v1/c-chart/kr-s/A${CODE}/day:1?count=100`);
    const r0 = res(first), cur = r0 && r0.nextDateTime;
    const oldest0 = candles(r0)[candles(r0).length - 1].dt;
    say(`  1페이지 가장 오래된 캔들 = ${oldest0} / nextDateTime = ${cur}`);
    const names = ["to", "before", "until", "endDateTime", "end", "dateTime",
                   "nextDateTime", "baseDateTime", "startDateTime", "cursor", "from"];
    for (const k of names) {
      const [st, pl] = await call(
        `/v1/c-chart/kr-s/A${CODE}/day:1?count=100&${k}=${encodeURIComponent(cur)}`);
      if (st !== 200) { say(`  X ${k} -> ${st}`); continue; }
      const c = candles(res(pl));
      const oldest = c && c.length ? c[c.length - 1].dt : null;
      const moved = oldest && oldest < oldest0;
      say(`  ${moved ? "★" : "-"} ${k} -> 200  ${c ? c.length : 0}건, 가장 오래된 ${oldest}${moved ? "  ← 넘어갔다" : ""}`);
    }
  }

  say("\n[D] 분기 재무 — 5년 요청 방법 찾기");
  {
    const path = `/v2/stock-infos/revenue-and-net-profit/A${CODE}`;
    const bodies = [{}, { rangeCode: 5 }, { range: 5 }, { code: 5 },
                    { selectedRange: { code: 5 } }, { rangeType: 5 }, { period: 5 }];
    for (const b of bodies) {
      const [st, pl] = await call(path, b);
      if (st !== 200) { say(`  X ${JSON.stringify(b)} -> ${st}`); continue; }
      const r = res(pl);
      const sel = r && r.selectedRange;
      const all = JSON.stringify(r);
      const ys = (all.match(/\b20\d{2}-\d{2}\b/g) || []).sort();
      say(`  ${JSON.stringify(b)} -> selectedRange=${sel && sel.displayName}  ${ys.length ? `${ys[0]} ~ ${ys[ys.length - 1]}` : ""}`);
    }
  }

  say("\n[E] 분기 재무 응답 구조 (기본 본문)");
  for (const p of [`/v2/stock-infos/revenue-and-net-profit/A${CODE}`,
                   `/v2/companies/A${CODE}/financial-statement-records`]) {
    const [, pl] = await call(p, {});
    const r = res(pl);
    say(`  ${p}`);
    say(`    최상위 키: ${JSON.stringify(Object.keys(r || {}))}`);
    for (const [k, v] of Object.entries(r || {})) {
      if (Array.isArray(v) && v.length) {
        say(`    ${k}[${v.length}] 첫 원소: ${JSON.stringify(v[0]).slice(0, 300)}`);
      }
    }
  }

  /* 콘솔 copy() 는 async 문맥에서 자주 실패한다. 파일로 떨군다. */
  const text = log.join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  a.download = `probe2-${CODE}.txt`;
  document.body.appendChild(a); a.click(); a.remove();
  console.log("%c▶ probe2-" + CODE + ".txt 로 저장했다 (다운로드 폴더)", "font-weight:bold");
  try { await navigator.clipboard.writeText(text); console.log("  클립보드에도 복사됨"); } catch {}
})();
