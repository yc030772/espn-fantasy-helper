# Fantasy Basketball 助手(ESPN H2H 9-Cat)

純靜態網頁,沒有後端。ESPN 的 API 開放 CORS,聯盟資料由瀏覽器直接抓。

- **選秀**:依 9-cat z-score 排名。前幾輪拿最好的人,陣容成形後自動改成補弱項(等於幫你 punt)。
- **交易**:選好送出/得到的球員,直接看「對上這隊 9 類贏幾類」的前後變化,附 1 換 1 自動推薦。
- **FA**:排除所有已被選走的球員,依你隊上最弱的類別加權排序,並列出可以 drop 的人。

資料 = 2025-26 球季實際數據(ESPN 尚未發布 2026-27 預測)。

## 更新資料

```bash
python3 rank.py --json data.json
```

`rank.py` 也能單獨在終端機用:`python3 rank.py --top 50 --pos C`。

## 本機預覽

```bash
python3 -m http.server 8899
```
