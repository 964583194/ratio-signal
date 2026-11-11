// 交易系统共用图表（从 index.html 抽出来，给独立页面用）
function niceStep(span){const raw=span/5,m=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/m;return (f<1.5?1:f<3?2:f<7?5:10)*m}
// 双纵轴折线图：左轴若干条（同一刻度），右轴一条；按住看当天数值
function DualChart(svg, o) {
  if (!o.big) svg.__opt = o;          // 留给“横屏看大图”用
  const W = o.W || 720, H = o.H || 260, pt = 14, lw = o.big ? 1.5 : 1;
  const wrap = svg.parentNode, tip = wrap.querySelector(".tip");
  const D = o.dates, n = D.length;
  const ly = o.left.flatMap(s => s.v.filter(v => v != null)), ry = o.right.v.filter(v => v != null);
  const [l0, l1] = o.leftRange || [Math.min(...ly), Math.max(...ly)];
  const rpad = (Math.max(...ry) - Math.min(...ry)) * .06, r0 = Math.min(...ry) - rpad, r1 = Math.max(...ry) + rpad;
  const cw = svg.clientWidth || W, fs = Math.min(o.big ? 34 : 22, Math.max(11, (o.big ? 11.5 : 10.5) * W / cw));
  svg.style.setProperty("--fs", fs + "px");
  const pb = Math.round(fs * 1.9), pl = o.leftTicks.length ? Math.round(Math.max(...o.leftTicks.map(v => String(o.leftFmt(v)).length)) * fs * .62 + fs * .9) : Math.round(fs * .6), pr = Math.round(fs * 2.9);
  const X = i => pl + i / (n - 1) * (W - pl - pr);
  const YL = v => pt + (1 - (v - l0) / (l1 - l0)) * (H - pt - pb), YR = v => pt + (1 - (v - r0) / (r1 - r0)) * (H - pt - pb);
  let s = "";
  if (o.bg) { let j0 = 0; for (let i = 1; i <= n; i++) if (i === n || o.bg[i] !== o.bg[j0]) { if (o.bg[j0]) s += `<rect x="${X(Math.max(0, j0 - .5))}" y="${pt}" width="${Math.max(1, X(Math.min(n - 1, i - .5)) - X(Math.max(0, j0 - .5)))}" height="${H - pt - pb}" fill="${o.bg[j0]}"/>`; j0 = i } }
  (o.bands || []).forEach(b => { const y1 = YL(b.to), y2 = YL(b.from); s += `<rect x="${pl}" y="${y1}" width="${W - pl - pr}" height="${y2 - y1}" fill="${b.fill}"/>` });
  (o.leftTicks).forEach(v => { s += `<line x1="${pl}" x2="${W - pr}" y1="${YL(v)}" y2="${YL(v)}" stroke="var(--line)"/><text x="${pl - 6}" y="${YL(v) + fs * .36}" text-anchor="end" style="fill:${o.leftColor || "var(--muted)"}">${o.leftFmt(v)}</text>` });
  const rt = []; const st = niceStep((r1 - r0) * 0.8); for (let v = Math.ceil(r0 / st) * st; v <= r1; v += st) rt.push(v);
  rt.forEach(v => { s += `<text x="${W - pr + 6}" y="${YR(v) + fs * .36}" text-anchor="start" style="fill:${o.right.c}">${Math.round(v)}</text>` });
  // 横轴按月：每个月一个小刻度；标签每 1/2/3/6/12 个月一个，按图的宽度自动选，保证不挤
  const ms = []; let last = "";
  D.forEach((d, i) => { const k = d.slice(0, 7); if (k !== last) { if (last) ms.push(i); last = k } });
  // 地方够就每月标“3月”这种短标签（1 月标年份），不够就每 3/6/12 个月标“2026/3”
  const perM = (W - pl - pr) / Math.max(1, ms.length + 1), shortW = fs * 2.6, longW = fs * 4.8;
  const yrW = fs * 3.2, stepM = perM >= shortW ? 1 : 2 * perM >= shortW ? 2 : ([3, 6].find(k => k * perM >= longW) || [12, 24, 36, 60].find(k => k * perM >= yrW) || 120);
  ms.forEach(i => { const d = D[i], m = +d.slice(5, 7);
    s += `<line x1="${X(i)}" x2="${X(i)}" y1="${H - pb}" y2="${H - pb + (m === 1 ? 6 : 3)}" stroke="var(--muted)"/>`;
    if ((m - 1) % stepM) return;
    if (stepM > 12 && +d.slice(0, 4) % (stepM / 12)) return;
    s += `<text x="${X(i)}" y="${H - fs * .4}" text-anchor="middle"${stepM < 3 && m === 1 ? ' style="font-weight:700"' : ""}>${stepM < 3 ? (m === 1 ? d.slice(0, 4) : m + "月") : stepM >= 12 ? d.slice(0, 4) : d.slice(0, 4) + "/" + m}</text>` });
  const path = (v, Y) => { let p = ""; v.forEach((y, i) => { if (y == null) return; p += (p ? "L" : "M") + X(i).toFixed(1) + " " + Y(y).toFixed(1) }); return p };
  s += `<path d="${path(o.right.v, YR)}" fill="none" stroke="${o.right.c}" stroke-width="${1.3 * lw}" opacity=".9"/>`;
  o.left.forEach(l => { s += `<path d="${path(l.v, YL)}" fill="none" stroke="${l.c}" stroke-width="${(l.w || 1.8) * lw}" stroke-dasharray="${l.dash || ""}"/>` });
  (o.marks || []).forEach(m => { const i = D.indexOf(m.d); if (i < 0) return; s += `<line x1="${X(i)}" x2="${X(i)}" y1="${pt}" y2="${H - pb}" stroke="${m.c}" stroke-dasharray="2 3"/><text x="${X(i) + 3}" y="${pt + fs}" style="fill:${m.c}">${m.t}</text>` });
  s += `<g class="cursor" style="display:none"><line y1="${pt}" y2="${H - pb}" stroke="var(--muted)" stroke-dasharray="3 3"/></g>`;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = s;
  const show = e => { const r = svg.getBoundingClientRect(), vx = (o.rot ? (e.clientY - r.top) / r.height : (e.clientX - r.left) / r.width) * W, i = Math.max(0, Math.min(n - 1, Math.round((vx - pl) / (W - pl - pr) * (n - 1))));
    const g = svg.querySelector(".cursor"); g.style.display = ""; g.querySelector("line").setAttribute("x1", X(i)); g.querySelector("line").setAttribute("x2", X(i));
    tip.innerHTML = o.tip(i); tip.hidden = false; const ww = o.rot ? svg.clientWidth : r.width, px = X(i) / W * ww; let left = px + 12; if (left + tip.offsetWidth > ww) left = px - tip.offsetWidth - 12; tip.style.left = Math.max(0, left) + "px"; tip.style.top = "8px" };
  svg.addEventListener("pointerdown", show); svg.addEventListener("pointermove", e => { if (e.pointerType === "mouse" || e.buttons) show(e) });
}

// 横屏看大图：手机竖着拿时整张图转 90 度铺满屏幕；横着拿或电脑上直接全屏
function openBig(id, title) {
  const o = document.getElementById(id).__opt; if (!o) return;
  const port = innerHeight > innerWidth, Wv = port ? innerHeight : innerWidth, Hv = port ? innerWidth : innerHeight;
  const ov = document.createElement("div"); ov.className = "bigov";
  ov.innerHTML = `<div class="bigin" style="width:${Wv}px;height:${Hv}px;${port ? `transform:translateX(${innerWidth}px) rotate(90deg);transform-origin:top left;` : ""}">
    <div class="bighd"><b>${title}</b><span><span class="bigr"><button type="button" data-y="1">近1年</button><button type="button" data-y="2">近2年</button><button type="button" data-y="0" aria-pressed="true">全部</button></span><button type="button" class="bigx">✕ 关闭</button></span></div>
    <div class="chartwrap"><svg class="chart" role="img" style="touch-action:none;width:100%;height:${Hv - 64}px"></svg><div class="tip" hidden></div></div></div>`;
  document.body.appendChild(ov); const ofl = document.body.style.overflow; document.body.style.overflow = "hidden";
  const close = () => { ov.remove(); document.body.style.overflow = ofl; removeEventListener("resize", close) };
  ov.querySelector(".bigx").addEventListener("click", close); addEventListener("resize", close);
  const W = 1400, H = Math.round(W * (Hv - 64) / (Wv - 24));
  const draw = y => {          // 按时间范围截取后重画（换一个新的 svg，避免重复绑定事件）
    const old = ov.querySelector("svg"), sv = old.cloneNode(false); old.replaceWith(sv);
    let i0 = 0;
    if (y) { const last = new Date(o.dates[o.dates.length - 1] + "T00:00:00Z"); last.setUTCFullYear(last.getUTCFullYear() - y);
      const f = last.toISOString().slice(0, 10); i0 = Math.max(0, o.dates.findIndex(d => d >= f)) }
    DualChart(sv, { ...o, W, H, big: true, rot: port, dates: o.dates.slice(i0),
      left: o.left.map(l => ({ ...l, v: l.v.slice(i0) })), right: { ...o.right, v: o.right.v.slice(i0) }, bg: o.bg && o.bg.slice(i0), tip: i => o.tip(i + i0) });
  };
  ov.querySelectorAll(".bigr button").forEach(b => b.addEventListener("click", () => {
    ov.querySelectorAll(".bigr button").forEach(x => x.setAttribute("aria-pressed", x === b)); draw(+b.dataset.y) }));
  requestAnimationFrame(() => draw(0));
}
