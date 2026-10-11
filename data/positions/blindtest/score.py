import csv, gzip, json, sys, collections
deck, wd, D, judge = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3], sys.argv[4]
SEEN = {"Lionel Messi","Joshua Kimmich","Philipp Lahm","David Alaba","Fabinho","Roberto Firmino","James Milner","Sergio Ramos",
        "Franck Ribéry","Adnan Januzaj","Nani","Lucas Moura","Jérémy Ménez","Cristian Tello","Samir Nasri","Yannick Carrasco","Arjen Robben","Douglas Costa"}
MAP = {"Goalkeeper":"GK","Centre-Back":"CB","Sweeper":"CB","Left-Back":"LB","Right-Back":"RB","Defensive Midfield":"DM",
       "Central Midfield":"CM","Attacking Midfield":"AM","Left Midfield":"LM","Right Midfield":"RM","Left Winger":"LW",
       "Right Winger":"RW","Centre-Forward":"ST","Second Striker":"ST"}
mine, key = {}, None
for line in open(judge, encoding="utf-8"):
    line = line.strip()
    if line.startswith("# "): key = line[2:]
    elif line: n, ps = line.split("|"); mine[(key, n)] = ps.split(",")
keys = {k for k, _ in mine}
games = {}
with gzip.open(f"{D}/games.csv.gz", "rt") as f:
    for r in csv.DictReader(f): games[r["game_id"]] = int(r["season"])
starts = collections.defaultdict(collections.Counter); ss = collections.Counter()
with gzip.open(f"{D}/game_lineups.csv.gz", "rt") as f:
    for r in csv.DictReader(f):
        s = games.get(r["game_id"])
        if s is None or r["type"] != "starting_lineup": continue
        starts[(r["player_id"], s, r["club_id"])][r["position"]] += 1
agg = collections.Counter(); byclub = collections.defaultdict(collections.Counter)
fps, misses, nostart, prim_wrong = [], [], [], []
for c in deck["club_seasons"]:
    if c["key"] not in keys: continue
    s = c["season"]
    # the club's Transfermarkt id: where most of this squad started that season
    votes = collections.Counter()
    for p in c["players"]:
        tm = wd[p["id"]]["tm"]
        for (pid, ss_, club), cnt in ((k, v) for k, v in starts.items() if tm and k[0] == tm[0] and k[1] == s):
            votes[club] += sum(cnt.values())
    club = votes.most_common(1)[0][0]
    for p in c["players"]:
        if p["name"] in SEEN: agg["excluded (seen)"] += 1; continue
        m = mine[(c["key"], p["name"])]
        tm = wd[p["id"]]["tm"]
        raw = starts.get((tm[0], s, club), collections.Counter()) if tm else collections.Counter()
        t = collections.Counter()
        for pos, n in raw.items():
            if pos in MAP: t[MAP[pos]] += n
            if pos == "Second Striker": ss[p["name"]] += n
        if not t: nostart.append((c["key"], p["name"], m)); agg["no starts for the club"] += 1; continue
        ranked = [x for x, _ in t.most_common()]
        truth4 = set(ranked[:4]); total = sum(t.values())
        a = agg; b = byclub[c["key"]]
        for z in (a, b):
            z["scored"] += 1
            z["mine"] += len(m); z["mine_ok"] += sum(1 for x in m if x in t)
            z["truth4"] += len(truth4); z["truth4_hit"] += len(truth4 & set(m))
            z["starts"] += total; z["starts_cov"] += sum(n for x, n in t.items() if x in m)
            z["primary_ok"] += m[0] in {x for x, n in t.items() if n == max(t.values())}
            z["exact"] += set(m) == truth4
            reg = {x for x, n in t.items() if n >= 3}
            z["reg"] += len(reg); z["reg_hit"] += len(reg & set(m))
        for x in m:
            if x not in t: fps.append((c["key"], p["name"], x, dict(t)))
        for x in ranked[:4]:
            if x not in m: misses.append((c["key"], p["name"], x, t[x], m))
        if m[0] not in {x for x, n in t.items() if n == max(t.values())}: prim_wrong.append((c["key"], p["name"], m, dict(t.most_common())))
def rep(z):
    return (f"scored {z['scored']}: primary {z['primary_ok']/z['scored']:.1%} | precision {z['mine_ok']}/{z['mine']} = {z['mine_ok']/z['mine']:.1%}"
            f" | recall(top4) {z['truth4_hit']}/{z['truth4']} = {z['truth4_hit']/z['truth4']:.1%} | recall(>=3 starts) {z['reg_hit']}/{z['reg']} = {z['reg_hit']/z['reg']:.1%}"
            f" | starts covered {z['starts_cov']/z['starts']:.1%} | exact set {z['exact']/z['scored']:.1%}")
print("ALL", rep(agg)); print({k: v for k, v in agg.items() if "(" in k or "no starts" in k})
for k in sorted(byclub): print(k, rep(byclub[k]))
print("\nPRIMARY WRONG", len(prim_wrong)); [print("  ", x) for x in prim_wrong]
print("\nFALSE POSITIVES (I listed, never started there)", len(fps)); [print("  ", x) for x in fps]
print("\nMISSES (top-4 truth I left out)", len(misses)); [print("  ", x) for x in misses]
print("\nNO STARTS FOR THE CLUB", nostart)
print("\nSecond Striker starts by sampled player:", ss.most_common())
