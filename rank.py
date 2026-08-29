"""ESPN Fantasy Basketball draft ranker.

用上季實際數據算 9-cat z-score(或 points league 總分),排出該選誰。
  python3 rank.py            # 9-cat, 前 60 名
  python3 rank.py --mode pts --top 100
  python3 rank.py --pos C    # 只看中鋒
輸出同時存成 rankings.csv。
"""
import argparse, csv, json, statistics as st, time, urllib.request

URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{s}/players?scoringPeriodId=0&view=kona_player_info"
POS = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}
# ESPN stat id -> 名稱(累積量,非場均)
S = {"PTS": "0", "BLK": "1", "STL": "2", "AST": "3", "REB": "6", "TO": "11",
     "FGM": "13", "FGA": "14", "FTM": "15", "FTA": "16", "3PM": "17", "GP": "42", "MIN": "40"}
# H2H 9-cat 建議權重 = 1/σ(整隊該類別總分);TO 與 PTS/AST 相關 -0.85,額外壓低
W = {"PTS": 1.25, "REB": 1.10, "AST": 1.00, "STL": 1.20, "BLK": 0.90,
     "3PM": 0.95, "TO": 0.60, "FG_imp": 0.90, "FT_imp": 0.75}
# ESPN 預設 points league 計分
PTS_SCORING = {"PTS": 1, "REB": 1, "AST": 2, "STL": 4, "BLK": 4, "TO": -2}


def fetch(season, limit=500, tries=4):
    f = json.dumps({"players": {"limit": limit,
                                "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "STANDARD"}}})
    req = urllib.request.Request(URL.format(s=season),
                                 headers={"X-Fantasy-Filter": f, "User-Agent": "Mozilla/5.0"})
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(req, timeout=120))
        except Exception as e:                      # ESPN 偶爾丟連線,重試就好
            if i == tries - 1:
                raise
            print("retry %d (%s)" % (i + 1, type(e).__name__))
            time.sleep(3 * (i + 1))


def totals(player, season):
    """該季實際累積數據 (statSourceId=0, 全季)。"""
    for s in player.get("stats", []):
        if s.get("id") == "00%d" % season:
            return s.get("stats") or {}
    return {}


def zscores(rows):
    """9-cat z-score。FG%/FT% 用出手量加權(投得少的高命中率不該灌水)。"""
    cats = ["PTS", "REB", "AST", "STL", "BLK", "3PM"]
    lg_fg = sum(r["FGM"] for r in rows) / max(sum(r["FGA"] for r in rows), 1)
    lg_ft = sum(r["FTM"] for r in rows) / max(sum(r["FTA"] for r in rows), 1)
    for r in rows:
        r["FG_imp"] = r["FGA"] * (r["FGM"] / r["FGA"] - lg_fg) if r["FGA"] else 0.0
        r["FT_imp"] = r["FTA"] * (r["FTM"] / r["FTA"] - lg_ft) if r["FTA"] else 0.0
    for c in cats + ["TO", "FG_imp", "FT_imp"]:
        vals = [r[c] for r in rows]
        m, sd = st.mean(vals), st.pstdev(vals) or 1.0
        sign = -1 if c == "TO" else 1
        for r in rows:
            r["z" + c] = sign * (r[c] - m) / sd
    for r in rows:
        r["score"] = sum(W[c] * r["z" + c] for c in cats + ["TO", "FG_imp", "FT_imp"])
    return rows


def build(season=2026, rank_season=2027, min_gp=20):
    ranks = {p["id"]: (p.get("draftRanksByRankType", {}).get("STANDARD", {}).get("rank"),
                       p.get("ownership", {}).get("averageDraftPosition"))
             for p in fetch(rank_season)}
    rows = []
    for p in fetch(season):
        t = totals(p, season)
        gp = t.get(S["GP"], 0)
        if gp < min_gp:
            continue
        r = {"name": p["fullName"], "id": p["id"], "pos": POS.get(p.get("defaultPositionId"), "?"),
             "GP": gp, "MIN": round(t.get(S["MIN"], 0) / gp, 1),
             "injury": p.get("injuryStatus", "")}
        for k in ("PTS", "REB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "FTM", "FTA", "3PM"):
            r[k] = t.get(S[k], 0) / gp          # 場均
        r["espn_rank"], r["adp"] = ranks.get(p["id"], (None, None))
        rows.append(r)
    return rows


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--mode", choices=["9cat", "pts"], default="9cat")
    a.add_argument("--top", type=int, default=60)
    a.add_argument("--pos", default=None, help="PG/SG/SF/PF/C")
    a.add_argument("--min-gp", type=int, default=20)
    a.add_argument("--out", default="rankings.csv")
    a.add_argument("--json", default=None, help="順便輸出網頁用的 data.json")
    args = a.parse_args()

    rows = build(min_gp=args.min_gp)
    if args.mode == "pts":
        for r in rows:
            r["score"] = sum(w * r[c] for c, w in PTS_SCORING.items())
    else:
        zscores(rows)
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, 1):
        r["my_rank"] = i
    shown = [r for r in rows if not args.pos or r["pos"] == args.pos][:args.top]

    hdr = f"{'#':>3} {'球員':<24}{'POS':<4}{'GP':>3}{'MIN':>6}{'分數':>7}{'ESPN':>6}{'ADP':>7}  差值"
    print(f"\n== {args.mode} 排名 (2025-26 實際數據) ==\n{hdr}\n{'-'*len(hdr)}")
    for r in shown:
        adp = r["adp"] or 0
        edge = ("+%.0f" % (adp - r["my_rank"])) if adp and adp < 400 else ""
        flag = " ⚠" + r["injury"] if r["injury"] not in ("ACTIVE", "") else ""
        print(f"{r['my_rank']:>3} {r['name']:<24}{r['pos']:<4}{r['GP']:>3}{r['MIN']:>6}"
              f"{r['score']:>7.2f}{r['espn_rank'] or '-':>6}{adp:>7.0f}  {edge}{flag}")
    print("\n差值 = ESPN ADP - 我的排名,正數越大越是「便宜的好貨」。")

    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"完整 {len(rows)} 人已存到 {args.out}")
    if args.json:
        json.dump(rows, open(args.json, "w"), separators=(",", ":"))
        print(f"網頁資料已存到 {args.json}")


def demo():
    rows = [{"PTS": 25, "REB": 5, "AST": 5, "STL": 1, "BLK": 1, "3PM": 3, "TO": 3, "FGM": 9, "FGA": 18, "FTM": 4, "FTA": 5},
            {"PTS": 10, "REB": 3, "AST": 2, "STL": .5, "BLK": .2, "3PM": 1, "TO": 1, "FGM": 4, "FGA": 10, "FTM": 2, "FTA": 3},
            {"PTS": 2, "REB": 8, "AST": 1, "STL": .3, "BLK": 2, "3PM": 0, "TO": 4, "FGM": 1, "FGA": 2, "FTM": 0, "FTA": 2}]
    zscores(rows)
    assert rows[0]["score"] > max(rows[1]["score"], rows[2]["score"])   # 全能明星最高
    assert rows[2]["zTO"] < 0 < rows[1]["zTO"]                  # 失誤多 = 負分
    assert rows[2]["FT_imp"] < 0 < rows[0]["FT_imp"]            # 罰球爛 = 扣分
    # 權重要真的有作用:調高 TO 權重,失誤王的分數必須下降
    before = rows[2]["score"]
    W["TO"] = 2.0
    zscores(rows)
    assert rows[2]["score"] < before, (before, rows[2]["score"])
    W["TO"] = 0.60
    print("demo ok")


if __name__ == "__main__":
    import sys
    demo() if "--demo" in sys.argv else main()
