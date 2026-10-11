"""Pick club-seasons from 2013-14 on for the blind test, one per club. Reads deck.json ONLY."""
import json, random, sys
deck = json.load(open(sys.argv[1]))
pool = [c for c in deck["club_seasons"] if c["season"] >= 2013]
random.Random(20261011).shuffle(pool)
picked, clubs = [], set()
for c in pool:
    if c["club"] in clubs: continue
    clubs.add(c["club"]); picked.append(c)
    if len(picked) == 16: break
for c in sorted(picked, key=lambda c: c["key"]):
    print(f"# {c['key']} {c['name']} {c['label']}")
    for p in c["players"]:
        print(f"{p['name']}|{p['pos']}|{p['rating']}")
    print()
