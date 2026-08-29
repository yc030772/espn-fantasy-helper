"""ESPN Fantasy Basketball draft ranker.

用上季實際數據算 9-cat z-score(或 points league 總分),排出該選誰。
  python3 rank.py            # 9-cat, 前 60 名
  python3 rank.py --mode pts --top 100
  python3 rank.py --pos C    # 只看中鋒
輸出同時存成 rankings.csv。
"""
import argparse, csv, json, statistics as st, time, urllib.request

URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{s}/players?scoringPeriodId=0&view=kona_player_info"
TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
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


def nba_teams():
    """ESPN 官方隊伍配色與隊徽。site API 的 team id 與 fantasy 的 proTeamId 相同。"""
    req = urllib.request.Request(TEAMS_URL, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    out = {}
    for g in d["sports"][0]["leagues"][0]["teams"]:
        t = g["team"]
        out[int(t["id"])] = {"abbr": t["abbreviation"], "name": t["shortDisplayName"],
                             "color": "#" + t["color"], "alt": "#" + (t.get("alternateColor") or t["color"]),
                             "logo": t["logos"][0]["href"]}
    return out


def totals(player, season, src=0):
    """該季全季累積數據。src=0 實際,src=1 ESPN 賽前投影。

    stat 的 id 格式是 {statSourceId}{statSplitTypeId}{season},
    所以 "002027" = 2026-27 實際,"102027" = 2026-27 投影。
    """
    key = "%d0%d" % (src, season)
    for s in player.get("stats", []):
        if s.get("id") == key:
            return s.get("stats") or {}
    return {}


def zscores(rows, ref=None):
    """9-cat z-score。FG%/FT% 用出手量加權(投得少的高命中率不該灌水)。

    ref = 用來算聯盟平均與標準差的樣本。預設全體;傳入「出賽數夠的球員」可
    避免只打 2 場的人扭曲基準,同時仍然給每個人算出分數。
    """
    cats = ["PTS", "REB", "AST", "STL", "BLK", "3PM"]
    ref = ref or rows
    lg_fg = sum(r["FGM"] for r in ref) / max(sum(r["FGA"] for r in ref), 1)
    lg_ft = sum(r["FTM"] for r in ref) / max(sum(r["FTA"] for r in ref), 1)
    for r in rows:
        r["FG_imp"] = r["FGA"] * (r["FGM"] / r["FGA"] - lg_fg) if r["FGA"] else 0.0
        r["FT_imp"] = r["FTA"] * (r["FTM"] / r["FTA"] - lg_ft) if r["FTA"] else 0.0
    for c in cats + ["TO", "FG_imp", "FT_imp"]:
        vals = [r[c] for r in ref]
        m, sd = st.mean(vals), st.pstdev(vals) or 1.0
        sign = -1 if c == "TO" else 1
        for r in rows:
            r["z" + c] = sign * (r[c] - m) / sd
    for r in rows:
        r["score"] = sum(W[c] * r["z" + c] for c in cats + ["TO", "FG_imp", "FT_imp"])
    return rows


STATS = ("PTS", "REB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "FTM", "FTA", "3PM")


def per_game(t):
    gp = t.get(S["GP"], 0)
    if not gp:
        return None
    return dict({k: t.get(S[k], 0) / gp for k in STATS},
                GP=gp, MIN=round(t.get(S["MIN"], 0) / gp, 1))


def build(season=2026, rank_season=2027, min_gp=20, source="auto"):
    """主檔 = 新球季名單(含新秀與整季報銷的傷兵),再左連接數據。

    以前拿舊球季當主檔又用 GP>=20 過濾,結果 Sabonis / Trae / Tatum 這種
    去年打不到 20 場的人整批消失在選秀板上,新秀更是完全沒出現。

    數據來源(source):
      proj   ESPN 對 rank_season 的賽前投影 —— 這是最想要的,因為它已經
             把傷癒歸隊、換隊、角色變化算進去了。
      actual 上一季實際數據。
      auto   有投影就用投影,沒有就退回實際數據(預設)。
    """
    master = fetch(rank_season)
    proj = {p["id"]: pg for p in master
            if (pg := per_game(totals(p, rank_season, src=1)))}
    use_proj = source == "proj" or (source == "auto" and len(proj) >= 100)
    if source == "proj" and not proj:
        raise SystemExit(f"ESPN 尚未發布 {rank_season} 的逐項投影,改用 --source actual")
    if use_proj:
        stats, tag = proj, f"ESPN {rank_season} 賽前投影"
    else:
        stats = {p["id"]: pg for p in fetch(season)
                 if (pg := per_game(totals(p, season)))}
        tag = f"{season-1}-{str(season)[2:]} 實際數據"
    print(f"數據來源:{tag}({len(stats)} 人有數據)")
    rows = []
    for p in master:
        d = p.get("draftRanksByRankType") or {}
        adp = (p.get("ownership") or {}).get("averageDraftPosition")
        rk = d.get("STANDARD", {}).get("rank")
        if not rk and not (adp and adp < 140):
            continue                              # ESPN 完全沒排名的人不放進來
        s = stats.get(p["id"])
        r = {"name": p["fullName"], "id": p["id"], "pos": POS.get(p.get("defaultPositionId"), "?"),
             "team": p.get("proTeamId"), "injury": p.get("injuryStatus", ""),
             "espn_rank": rk, "roto_rank": d.get("ROTO", {}).get("rank"),
             "auction": d.get("STANDARD", {}).get("auctionValue") or 0, "adp": adp,
             "GP": s["GP"] if s else 0, "MIN": s["MIN"] if s else 0}
        for k in STATS:
            r[k] = s[k] if s else 0.0
        r["sample"] = "ok" if r["GP"] >= min_gp else ("thin" if r["GP"] else "none")
        rows.append(r)
    rows and rows[0].setdefault("source", tag)
    for r in rows:
        r["source"] = tag
    return rows


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--mode", choices=["9cat", "pts"], default="9cat")
    a.add_argument("--top", type=int, default=60)
    a.add_argument("--pos", default=None, help="PG/SG/SF/PF/C")
    a.add_argument("--min-gp", type=int, default=20)
    a.add_argument("--source", choices=["auto", "proj", "actual"], default="auto",
                   help="auto = ESPN 有投影就用投影,沒有就用上一季實際數據")
    a.add_argument("--out", default="rankings.csv")
    a.add_argument("--json", default=None, help="順便輸出網頁用的 data.json")
    args = a.parse_args()

    rows = build(min_gp=args.min_gp, source=args.source)
    ref = [r for r in rows if r["sample"] == "ok"]      # 基準只用樣本夠的人
    if args.mode == "pts":
        for r in rows:
            r["score"] = sum(w * r[c] for c, w in PTS_SCORING.items())
    else:
        zscores(rows, ref)
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, 1):
        r["my_rank"] = i
    thin = sum(r["sample"] == "thin" for r in rows)
    none = sum(r["sample"] == "none" for r in rows)
    print(f"\n樣本充足 {len(ref)} 人 · 小樣本(<{args.min_gp} 場) {thin} 人 · 無數據(新秀等) {none} 人")
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
        json.dump({"players": rows, "teams": nba_teams()},
                  open(args.json, "w"), separators=(",", ":"))
        print(f"網頁資料已存到 {args.json}({len(rows)} 人 + 30 隊配色/隊徽)")


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
