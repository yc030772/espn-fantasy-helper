// ==UserScript==
// @name         ESPN 拍賣選秀 → Fantasy 助手
// @namespace    fantasy-helper
// @version      1.2
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
   本機助手頁:監聽變化 -> window.postMessage 給 index.html */

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

if (location.hostname === 'fantasy.espn.com') {
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
}
