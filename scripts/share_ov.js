// 总览分享图：直接用网页"本周这么做"那张卡片，套成 3:4 竖图（share.py 打开 index.html 后执行）
async () => {
  for (let i = 0; i < 60 && !document.querySelector('#o_rows a'); i++) await new Promise(r => setTimeout(r, 200));
  const T = await fetch('data/temp.json').then(r => r.json()).catch(() => null);
  const sec = document.querySelector('#viewO section.panel').cloneNode(true);
  sec.querySelector('h2 button')?.remove();
  sec.querySelectorAll('.chev').forEach(e => e.remove());
  sec.querySelector('#o_note')?.remove();
  let date = '';
  sec.querySelectorAll('.todo>a').forEach(a => {
    a.removeAttribute('href'); a.style.gridTemplateColumns = '6.4em 1fr'; a.style.padding = '9px 0';
    a.querySelectorAll('small').forEach(s => s.remove());
    if (a.querySelector('.n').textContent.trim() === '黄金')
      a.querySelector('.a').innerHTML = '<span style="color:var(--muted)">只看位置，暂不给建议</span>';
  });
  const m = (document.querySelector('#o_note') || {}).textContent?.match(/\d{4}-\d{2}-\d{2}/); date = m ? m[0] : '';
  const d = new Date(date + 'T00:00:00Z'), y = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const t = new Date(d); t.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const wk = Math.ceil(((t - new Date(Date.UTC(t.getUTCFullYear(), 0, 1))) / 864e5 + 1) / 7);
  const wd = '日一二三四五六'[d.getUTCDay()];
  const box = document.createElement('div');
  box.id = 'shot';
  box.style.cssText = 'position:fixed;left:0;top:0;width:360px;height:480px;z-index:999;background:var(--bg);padding:14px 12px 10px;box-sizing:border-box;display:flex;flex-direction:column;gap:8px;overflow:hidden';
  box.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:baseline;padding:0 4px">
      <b style="font-size:17px">指数定投 · 周记</b><span style="font-size:12px;color:var(--muted)">${date} 周${wd} · 第 ${wk} 周</span></div>
    <div style="padding:0 4px;font-size:12.5px;color:var(--muted)">${T ? `市场：<b style="color:var(--ink)">${T.latest.zone}</b> · ` : ''}周四收盘后定，周五 15:00 前下单</div>`;
  sec.style.margin = '0'; sec.style.flex = '1';
  box.appendChild(sec);
  const ft = document.createElement('div');
  ft.style.cssText = 'font-size:10.5px;color:var(--muted);text-align:center';
  ft.textContent = '个人指数定投记录，按规则自动计算，不构成投资建议';
  box.appendChild(ft);
  document.body.appendChild(box);
  // 内容太多就整体缩小，保证一屏放下
  const inner = sec, free = 480 - 14 - 10 - box.children[0].offsetHeight - box.children[1].offsetHeight - ft.offsetHeight - 24;
  if (inner.scrollHeight > free) { inner.style.zoom = (free / inner.scrollHeight).toFixed(3); }
  return date;
}
