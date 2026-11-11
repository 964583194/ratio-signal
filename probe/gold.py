import json, sys, csv, io, urllib.request
sys.path.insert(0, "scripts")
import sources as S
out = {}
def get(url, t=120):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=t).read().decode("utf-8", "replace")
# 1) FRED，加长超时、只要 2010 年起
for s in ("DFII10",):
    try:
        txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}&cosd=2010-01-01", 180)
        rd = csv.reader(io.StringIO(txt)); next(rd)
        d = {r[0]: float(r[1]) for r in rd if len(r) > 1 and r[1] not in (".", "")}
        print("== FRED", s, len(d), min(d), max(d)); out["fred_" + s] = d
    except Exception as e:
        print("== FRED 失败", e)
# 2) 美国财政部：每日实际收益率曲线（10 年），按年取
d = {}
for y in range(2010, 2027):
    try:
        txt = get(f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all?type=daily_treasury_real_yield_curve&field_tdr_date_value={y}&page&_format=csv", 60)
        rd = csv.DictReader(io.StringIO(txt))
        for r in rd:
            v = r.get("10 YR")
            if v:
                m, dd, yy = r["Date"].split("/"); d[f"{yy}-{m}-{dd}"] = float(v)
        print("财政部", y, "累计", len(d))
    except Exception as e:
        print("财政部", y, "失败", e)
if d:
    print("== treasury_real10", len(d), min(d), max(d)); out["ust_real10"] = d
s = json.dumps(out, separators=(",", ":"))
for i in range(0, len(s), 1500):
    print(f"CHUNK{i // 1500:05d}:" + s[i:i + 1500])
print("CHUNKEND")
