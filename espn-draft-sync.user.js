// ==UserScript==
// @name         ESPN 拍賣選秀 → Fantasy 助手
// @namespace    fantasy-helper
// @version      1.3
// @description  讀 ESPN 選秀室右側 Picks 清單(誰用多少錢買走誰),即時同步到本機的 Fantasy 助手
// @match        https://fantasy.espn.com/basketball/draft*
// @match        http://localhost:*/*
// @match        http://127.0.0.1:*/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_addValueChangeListener
// ==/UserScript==

/* 兩個頁面跑同一支腳本,用 Tampermonkey 的共用儲存傳資料:
   ESPN 選秀室:每秒讀 Picks 清單 -> GM_setValue
   本機助手頁:監聽變化 -> window.postMessage 給 index.html
   反方向:助手算好的儀表板(當前球員價位 + 我的 9 類別名次)-> GM_setValue('dash') -> 畫在 ESPN 的 Picks 上方 */

// 每筆成交是一個 li.pick-message__container:
//   .playerinfo__playername = 人名、.pick-info = 「$20 - Messi」、大頭照網址 .../full/{ESPN 球員 id}.png
// id 跟助手用的 id 相同,配對最準;抓不到 li(ESPN 改版)就退回純文字解析。
function parsePickItems(root) {
  return [...root.querySelectorAll('li.pick-message__container')].map(li => {
    const name = li.querySelector('.playerinfo__playername')?.textContent.trim();
    const m = li.querySelector('.pick-info')?.textContent.trim().match(/^\$(\d+)\s*-\s*(.+)$/);
    const id = +(li.querySelector('img')?.src.match(/\/full\/(\d+)\.png/)?.[1] || 0);
    return name && m ? { id, name, price: +m[1], team: m[2].trim() } : null;
  }).filter(Boolean);
}
// 純文字備案:每筆兩行「Michael Porter Jr. / BKN SF, PF」接「$18 - Han's Heated Team」
function parsePicks(text) {
  const lines = text.split('\n').map(s => s.trim()).filter(Boolean), out = [];
  for (let i = 0; i < lines.length - 1; i++) {
    const a = lines[i].match(/^(.+?) \/ [A-Z]{2,4}\b/), b = lines[i + 1].match(/^\$(\d+) - (.+)$/);
    if (a && b) out.push({ name: a[1], price: +b[1], team: b[2] });
  }
  return out;
}

// 正在競標的球員:.player-selected__player-info-container 裡的人名;
// 找不到(ESPN 改版)就退回「不在 Picks 清單裡的第一個 .playerinfo__playername」
function nominee(root) {
  const el = root.querySelector('.player-selected__player-info-container .playerinfo__playername')
    || [...root.querySelectorAll('.playerinfo__playername')].find(e => !e.closest('li.pick-message__container'));
  return el ? el.textContent.trim() : '';
}

// ESPN 頁右上角的儀表板(固定位置,蓋在 Picks 清單上方的空白處;點標題可收合)
const C = { good: '#3ddc97', warn: '#ffb454', bad: '#ff6b6b', blue: '#4c9aff', dim: '#9aa4b2' };
function drawDash(d) {
  let box = document.getElementById('fh-dash');
  if (!box) {
    box = document.createElement('div'); box.id = 'fh-dash';
    Object.assign(box.style, { position: 'fixed', top: '200px', right: '30px', width: '470px', zIndex: 99999,
      background: '#1b1f27', color: '#e6e6e6', borderRadius: '10px', padding: '12px 14px',
      font: '14px/1.4 -apple-system,system-ui,sans-serif', boxShadow: '0 4px 16px rgba(0,0,0,.4)' });
    box.onclick = e => { if (e.target.closest('.fh-h')) box.classList.toggle('fh-min'); draw(); };
    document.body.append(box);
  }
  // 對齊 Picks 那一欄:找文字剛好是「Picks」的標題,用它所在欄位的位置與寬度;找不到就靠右上
  const h = [...document.querySelectorAll('body *')].find(e => !e.children.length && e.textContent.trim() === 'Picks');
  if (h) { const r = h.parentElement.getBoundingClientRect(), t = h.getBoundingClientRect();
    Object.assign(box.style, { left: r.left + 'px', right: 'auto', width: r.width + 'px', top: t.bottom + 8 + 'px' }); }
  const $ = (v, c) => `<b style="color:${c};font-size:18px">${v == null ? '–' : '$' + v}</b>`;
  const rc = r => r <= 3 ? C.good : r <= d.half ? C.warn : C.bad;
  const lc = d.left == null ? C.dim : d.left <= d.open / 2 ? C.good : d.left <= d.open ? C.warn : C.bad;
  const head = `<div class="fh-h" style="cursor:pointer;font-weight:700;font-size:17px">${d.name || '尚未提名'}`
    + (d.name ? ` <span style="font-weight:400;font-size:14px;color:${C.dim}">剩餘第 <b style="color:${lc}">${d.left ?? '–'}</b> 名 / 場上剩 ${d.open} 空位</span>` : '') + '</div>';
  if (box.classList.contains('fh-min')) { box.innerHTML = head; return; }
  const prices = `<div style="margin:6px 0 10px">建議 ${$(d.bid, C.good)} · 均價 ${$(d.avg, C.warn)} · ESPN ${$(d.espn, '#e6e6e6')}`
    + ` · 我最高 ${$(d.my, d.bid && d.bid > d.my ? C.bad : C.blue)}</div>`;
  const cats = d.cats ? `<div style="display:flex;gap:4px;flex-wrap:wrap">` + d.cats.map(x =>
      `<div style="flex:1;min-width:36px;text-align:center;background:#262b35;border-radius:6px;padding:4px 0">`
      + `<div style="font-size:11px;color:${C.dim}">${x.c}</div><b style="color:${rc(x.r)}">#${x.r}</b></div>`).join('')
      + `<div style="flex:1;min-width:44px;text-align:center;border:1px solid ${C.blue};border-radius:6px;padding:4px 0">`
      + `<div style="font-size:11px;color:${C.dim}">前段</div><b>${d.cats.filter(x => x.r <= d.half).length}/9</b></div></div>`
    : `<div style="color:${C.dim}">買到第一個人之後顯示 9 類別名次</div>`;
  box.innerHTML = head + (d.name ? prices : `<div style="margin:6px 0 10px">我最高可出 ${$(d.my, C.blue)}</div>`) + cats;
}
const draw = () => { const s = GM_getValue('dash', ''); if (s) drawDash(JSON.parse(s)); };

if (location.hostname === 'fantasy.espn.com') {
  draw();
  GM_addValueChangeListener('dash', draw);
  let last = '', lastNom = null;
  setInterval(() => {
    const n = nominee(document);
    if (n !== lastNom) { lastNom = n; GM_setValue('nom', n); }
    let picks = parsePickItems(document);
    if (!picks.length) picks = parsePicks(document.body.innerText);
    const s = JSON.stringify(picks);
    if (s !== last) { last = s; GM_setValue('picks', s); }
  }, 1000);
} else {
  const send = s => s && window.postMessage({ type: 'espn-picks', picks: JSON.parse(s) }, '*');
  // index.html 載入資料後才會接訊息,開頁時多送幾次
  [1000, 3000, 6000].forEach(ms => setTimeout(() => send(GM_getValue('picks', '')), ms));
  GM_addValueChangeListener('picks', (k, o, n) => send(n));
  GM_addValueChangeListener('nom', (k, o, n) => window.postMessage({ type: 'espn-nom', name: n }, '*'));
  window.addEventListener('message', e => { if (e.data && e.data.type === 'espn-dash') GM_setValue('dash', JSON.stringify(e.data.d)); });
}
