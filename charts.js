// 交易系统共用图表：LineChart（单线，带时间范围切换）、DualChart（双纵轴，按月刻度）、openBig（横屏大图）
// ---------------- 通用交互折线图：时间范围切换 + 按住/悬停看数值
function niceStep(span){const raw=span/5,m=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/m;return (f<1.5?1:f<3?2:f<7?5:10)*m}
function LineChart(svg,opt){
  const W=opt.W,H=opt.H,pr=14,pt=12;let pl=44,pb=26,fs=11;
  const wrap=svg.parentNode,tip=wrap.querySelector(".tip");
  const bar=document.querySelector(`.ranges[data-for="${svg.id}"]`);
  if(bar&&!opt.noBig){   // 每张单线图都可以横屏看大图
    const bb=document.createElement("button");bb.type="button";bb.className="bigbtn";bb.textContent="⤢ 大图";bb.style.marginLeft="auto";
    bb.addEventListener("click",e=>{e.stopPropagation();const sec=svg.closest("section"),h=sec&&sec.querySelector("h3,h2");
      openBig(svg.id,((h&&h.textContent)||"").replace(/⤢.*$/,"").trim())});
    bar.appendChild(bb)}
  let full=[],range=opt.range||"all",cur=[],X=null,Y=null,ctx={};
  bar.addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;range=b.dataset.r;
    bar.querySelectorAll("button").forEach(x=>x.setAttribute("aria-pressed",x===b));draw()});
  function slice(){
    if(range==="all")return full;
    const last=new Date(full[full.length-1][0]+"T00:00:00Z");
    last.setUTCFullYear(last.getUTCFullYear()-(range==="1y"?1:3));
    const f=last.toISOString().slice(0,10);return full.filter(p=>p[0]>=f)}
  function draw(){
    cur=slice();const n=cur.length;if(n<2)return;
    const ovs=(opt.overlays||[]).map(o=>{const m=new Map(o.data);return {...o,v:cur.map(p=>m.has(p[0])?m.get(p[0]):null)}});
    // 手机上 SVG 会被缩小，按实际宽度放大文字，保证约 10px 可读
    const cw=svg.clientWidth||W;fs=Math.min(22,Math.max(11,10.5*W/cw));svg.style.setProperty("--fs",fs+"px");
    pb=Math.round(fs*1.9);
    let ymin,ymax,ticks;
    if(opt.fixedY){[ymin,ymax]=opt.fixedY;ticks=opt.ticks}
    else{const all=cur.map(p=>p[1]).concat(...ovs.map(o=>o.v.filter(x=>x!=null)));let lo=Math.min(...all),hi=Math.max(...all);const pad=(hi-lo)*.08||.01;
      const st=niceStep((hi-lo+2*pad)*(H<250?1.4:1));ymin=Math.floor((lo-pad)/st)*st;ymax=Math.ceil((hi+pad)/st)*st;ticks=[];
      for(let v=ymin;v<=ymax+st/2;v+=st)ticks.push(+v.toFixed(6))}
    const st0=ticks[1]-ticks[0],yl=ticks.map(v=>opt.fixedY||st0>=1?String(Math.round(v)):v.toFixed(Math.max(2,-Math.floor(Math.log10(st0+1e-12)))));
    pl=Math.round(Math.max(...yl.map(t=>t.length))*fs*.62+fs*.8);
    X=i=>pl+i/(n-1)*(W-pl-pr);Y=v=>pt+(1-(v-ymin)/(ymax-ymin))*(H-pt-pb);
    const cy=v=>Math.min(H-pb,Math.max(pt,Y(v)));
    let s="";
    (opt.bands||[]).forEach(b=>{const y1=cy(b.to==null?ymax:b.to),y2=cy(b.from==null?ymin:b.from);if(y2-y1>0)s+=`<rect x="${pl}" y="${y1}" width="${W-pl-pr}" height="${y2-y1}" fill="${b.fill}"/>`});
    const stp=ticks[1]-ticks[0],dec=opt.fixedY||stp>=1?0:Math.max(2,-Math.floor(Math.log10(stp+1e-12)));
    ticks.forEach(v=>{s+=`<line x1="${pl}" x2="${W-pr}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width="${opt.strong===v?1.6:1}"/><text x="${pl-fs*.45}" y="${Y(v)+fs*.36}" text-anchor="end">${opt.fixedY?v:v.toFixed(dec)}</text>`});
    (opt.lines||[]).forEach(l=>{if(l.v<ymin||l.v>ymax)return;s+=`<line x1="${pl}" x2="${W-pr}" y1="${Y(l.v)}" y2="${Y(l.v)}" stroke="${l.c}" stroke-dasharray="${l.dash||""}" stroke-width="${l.w||1.2}"/>`;
      if(l.label)s+=`<text x="${W-pr-2}" y="${Y(l.v)-3}" text-anchor="end" style="fill:${l.c}">${l.label}</text>`});
    // 横轴：跨度 ≤ 15 个月按月标注，否则按年
    const span=(new Date(cur[n-1][0])-new Date(cur[0][0]))/864e5,monthly=span<460;let last="",lastX=-1e9;
    cur.forEach(([dt],i)=>{const k=monthly?dt.slice(0,7):dt.slice(0,4);if(k!==last){const first=last==="";last=k;
      if(first)return;const mm=+dt.slice(5,7);if(monthly&&mm%2===0)return;
      const lab=monthly?(mm===1?dt.slice(0,4):mm+"月"):k;
      if(X(i)-lastX<fs*3.2)return;lastX=X(i);
      s+=`<text x="${X(i)}" y="${H-fs*.45}" text-anchor="middle">${lab}</text><line x1="${X(i)}" x2="${X(i)}" y1="${H-pb}" y2="${H-pb+4}" stroke="var(--muted)"/>`}});
    const step=Math.max(1,Math.floor(n/700));let d="";
    for(let i=0;i<n;i+=step)d+=(d?"L":"M")+X(i).toFixed(1)+" "+Y(cur[i][1]).toFixed(1);
    d+="L"+X(n-1).toFixed(1)+" "+Y(cur[n-1][1]).toFixed(1);
    ovs.forEach(o=>{let od="";for(let i=0;i<n;i+=step){const v=o.v[i];if(v==null){continue}od+=(od?"L":"M")+X(i).toFixed(1)+" "+Y(v).toFixed(1)}
      if(od)s+=`<path d="${od}" fill="none" stroke="${o.c}" stroke-width="${o.w||1.3}" stroke-dasharray="${o.dash||""}" stroke-linejoin="round"/>`});
    s+=`<path d="${d}" fill="none" stroke="var(--ink)" stroke-width="${range==="all"?1.4:1.8}" stroke-linejoin="round"/>`;
    s+=`<circle cx="${X(n-1)}" cy="${Y(cur[n-1][1])}" r="4.5" fill="var(--mark)" stroke="var(--panel)" stroke-width="2"/>`;
    s+=`<g class="cursor" style="display:none"><line y1="${pt}" y2="${H-pb}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/><circle r="5" fill="var(--panel)" stroke="var(--ink)" stroke-width="2"/></g>`;
    svg.innerHTML=s;hide()}
  function show(e){
    if(!cur.length)return;const r=svg.getBoundingClientRect(),vx=(e.clientX-r.left)/r.width*W;
    const n=cur.length,i=Math.max(0,Math.min(n-1,Math.round((vx-pl)/(W-pl-pr)*(n-1))));
    const [dt,v]=cur[i],g=svg.querySelector(".cursor");if(!g)return;
    g.style.display="";g.querySelector("line").setAttribute("x1",X(i));g.querySelector("line").setAttribute("x2",X(i));
    const c=g.querySelector("circle");c.setAttribute("cx",X(i));c.setAttribute("cy",Y(v));
    tip.innerHTML=opt.tip(dt,v,i);tip.hidden=false;
    const px=X(i)/W*r.width,py=Y(v)/H*r.height,tw=tip.offsetWidth,th=tip.offsetHeight;
    let left=px+12;if(left+tw>r.width)left=px-tw-12;
    let top=py-th-10;if(top<0)top=py+12;
    tip.style.left=Math.max(0,left)+"px";tip.style.top=top+"px"}
  function hide(){tip.hidden=true;const g=svg.querySelector(".cursor");if(g)g.style.display="none"}
  let rt;window.addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(()=>{if(full.length)draw()},150)});
  svg.addEventListener("pointerdown",e=>{show(e)});
  svg.addEventListener("pointermove",e=>{if(e.pointerType==="mouse"||e.buttons||e.pressure>0)show(e)});
  svg.addEventListener("pointerleave",e=>{if(e.pointerType==="mouse")hide()});
  document.addEventListener("pointerdown",e=>{if(!svg.contains(e.target))hide()});
  return {set(series,o){full=series;Object.assign(opt,o||{});svg.__lc={full,opt};draw()}};
}
// 双纵轴折线图：左轴若干条（同一刻度），右轴一条；按住看当天数值
function DualChart(svg, o) {
  if (!o.big) svg.__opt = o;          // 留给“横屏看大图”用
  const W = o.W || 720, H = o.H || 260, pt = 14, lw = o.big ? 1.5 : 1;
  const wrap = svg.parentNode, tip = wrap.querySelector(".tip");
  const D = o.dates, n = D.length;
  // sameAxis：左右用同一个刻度（比如价格和它的均线），刻度只显示在右边
  const ly = o.left.flatMap(s => s.v.filter(v => v != null)), ry = (o.sameAxis ? o.right.v.concat(ly) : o.right.v).filter(v => v != null);
  let [l0, l1] = o.leftRange || [Math.min(...ly), Math.max(...ly)];
  const rpad = (Math.max(...ry) - Math.min(...ry)) * .06, r0 = Math.min(...ry) - rpad, r1 = Math.max(...ry) + rpad;
  if (o.sameAxis) [l0, l1] = [r0, r1];
  const cw = svg.clientWidth || W, fs = Math.min(o.big ? 34 : 22, Math.max(11, (o.big ? 11.5 : 10.5) * W / cw));
  svg.style.setProperty("--fs", fs + "px");
  const pb = Math.round(fs * 1.9), pl = o.leftTicks.length ? Math.round(Math.max(...o.leftTicks.map(v => String(o.leftFmt(v)).length)) * fs * .62 + fs * .9) : Math.round(fs * .6), pr = Math.round(Math.max(2.9, String(Math.round(r1)).length * .62 + .7) * fs);
  const X = i => pl + i / (n - 1) * (W - pl - pr);
  const YL = v => pt + (1 - (v - l0) / (l1 - l0)) * (H - pt - pb), YR = v => pt + (1 - (v - r0) / (r1 - r0)) * (H - pt - pb);
  let s = "";
  if (o.bg) { let j0 = 0; for (let i = 1; i <= n; i++) if (i === n || o.bg[i] !== o.bg[j0]) { if (o.bg[j0]) s += `<rect x="${X(Math.max(0, j0 - .5))}" y="${pt}" width="${Math.max(1, X(Math.min(n - 1, i - .5)) - X(Math.max(0, j0 - .5)))}" height="${H - pt - pb}" fill="${o.bg[j0]}"/>`; j0 = i } }
  (o.bands || []).forEach(b => { const y1 = YL(b.to), y2 = YL(b.from); s += `<rect x="${pl}" y="${y1}" width="${W - pl - pr}" height="${y2 - y1}" fill="${b.fill}"/>` });
  (o.leftTicks).forEach(v => { s += `<line x1="${pl}" x2="${W - pr}" y1="${YL(v)}" y2="${YL(v)}" stroke="var(--line)"/><text x="${pl - 6}" y="${YL(v) + fs * .36}" text-anchor="end" style="fill:${o.leftColor || "var(--muted)"}">${o.leftFmt(v)}</text>` });
  const rt = []; const st = niceStep((r1 - r0) * 0.8); for (let v = Math.ceil(r0 / st) * st; v <= r1; v += st) rt.push(v);
  rt.forEach(v => { s += `<text x="${W - pr + 6}" y="${YR(v) + fs * .36}" text-anchor="start" style="fill:${o.right.c}">${o.right.fmt ? o.right.fmt(v) : Math.round(v)}</text>` });
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

// 单线图（LineChart）的数据换成 DualChart 的参数，给横屏大图用
function lcToDual({ full, opt }) {
  const dates = full.map(p => p[0]), v = full.map(p => p[1]);
  const ovs = (opt.overlays || []).map(x => { const m = new Map(x.data); return { v: dates.map(d => m.has(d) ? m.get(d) : null), c: x.c, w: x.w || 1.3, dash: x.dash } });
  const all = v.concat(...ovs.map(x => x.v)).filter(x => x != null);
  let lo, hi, ticks;
  if (opt.fixedY) { [lo, hi] = opt.fixedY; ticks = opt.ticks }
  else { const st = niceStep(Math.max(...all) - Math.min(...all)); lo = Math.floor(Math.min(...all) / st) * st; hi = Math.ceil(Math.max(...all) / st) * st;
    ticks = []; for (let t = lo; t <= hi + st / 2; t += st) ticks.push(+t.toFixed(6)) }
  const dec = hi - lo >= 5 ? 0 : 2;
  return { dates, leftRange: [lo, hi], leftTicks: ticks, leftFmt: t => t.toFixed(dec), left: [{ v, c: "var(--ink)", w: 1.6 }, ...ovs],
    right: { v, c: "transparent" }, bands: (opt.bands || []).map(b => ({ from: b.from == null ? lo : b.from, to: b.to == null ? hi : b.to, fill: b.fill })),
    tip: i => opt.tip ? opt.tip(dates[i], v[i], i) : dates[i] + " " + v[i] };
}
// 横屏看大图：手机竖着拿时整张图转 90 度铺满屏幕；横着拿或电脑上直接全屏
function openBig(id, title) {
  const el = document.getElementById(id);
  let o = el.__opt;
  if (!o && el.__lc) o = lcToDual(el.__lc);   // 单线图：换成双轴图的格式来画（右轴不显示）
  if (!o) return;
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
