import glob, json, sys, csv
tot = {}
for f in glob.glob(sys.argv[1] + "/**/*.json", recursive=True):
    for d, a in json.load(open(f)).items():
        t = tot.setdefault(d, [0] * 11)
        for k in range(11): t[k] += a[k]
with open("data/raw/breadth_daily.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["date", "n", "up", "dn", "upamt", "dnamt", "n20", "a20", "n250", "a250", "nh", "nl"])
    for d in sorted(tot):
        a = tot[d]; a[3] = round(a[3] / 1e8, 2); a[4] = round(a[4] / 1e8, 2)
        w.writerow([d] + a)
print("天数", len(tot))
