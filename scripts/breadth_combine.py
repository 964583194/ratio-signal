"""合并各分片月线 → data/raw/breadth_monthly.json（每月集中度、宽度）和 data/raw/stock_prev12.json（当月之前 12 个月收盘，供每日快照算宽度）"""
import datetime as dt
import glob
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")

if __name__ == "__main__":
    data = {}
    for f in glob.glob(os.path.join(sys.argv[1], "**", "*.json"), recursive=True):
        with open(f, encoding="utf-8") as fh:
            data.update(json.load(fh))
    if len(data) < 4000:
        raise SystemExit(f"只合并到 {len(data)} 只股票，不更新")
    mon = {}
    for sec, r in data.items():
        cl = [x[1] for x in r]
        for i, (m, c, amt) in enumerate(r):
            e = mon.setdefault(m, {"n": 0, "up": 0, "n12": 0, "ma12": 0, "hi12": 0, "amts": []})
            if i >= 1 and cl[i - 1] > 0:
                e["n"] += 1
                e["up"] += c > cl[i - 1]
            if i >= 12:
                e["n12"] += 1
                e["ma12"] += c > sum(cl[i - 12:i]) / 12
                e["hi12"] += c >= max(cl[i - 12:i])
            if amt > 0:
                e["amts"].append(amt)
    out = {}
    for m, e in sorted(mon.items()):
        xs = sorted(e["amts"], reverse=True)
        k = len(xs)
        if m < "2009-01" or k < 500:
            continue
        out[m] = {"top5": round(sum(xs[:math.ceil(k * .05)]) / sum(xs), 4), "ma12": round(e["ma12"] / e["n12"], 4) if e["n12"] else None,
                  "up": round(e["up"] / e["n"], 4) if e["n"] else None, "hi12": round(e["hi12"] / e["n12"], 4) if e["n12"] else None, "nstk": k}
    cur = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m")
    old = {}
    try:
        with open(os.path.join(RAW, "breadth_monthly.json"), encoding="utf-8") as fh:
            old = json.load(fh)
    except Exception:  # noqa: BLE001
        pass
    if cur in old and old[cur].get("partial"):     # 当月以每日快照为准，月线只有月初几天
        out[cur] = old[cur]
    else:
        out.pop(cur, None)
    with open(os.path.join(RAW, "breadth_monthly.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    prev = {}
    for sec, r in data.items():
        past = [x[1] for x in r if x[0] < cur][-12:]
        if len(past) == 12:
            prev[sec] = past
    with open(os.path.join(RAW, "stock_prev12.json"), "w", encoding="utf-8") as fh:
        json.dump({"month": cur, "closes": prev}, fh, separators=(",", ":"))
    print(f"月度宽度：{len(data)} 只股票，{len(out)} 个月；前 12 个月收盘 {len(prev)} 只（供 {cur} 每日计算）")
