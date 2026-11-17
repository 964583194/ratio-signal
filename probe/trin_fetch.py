"""探针：全部 A 股日线 → 每天的涨跌家数、涨跌成交额、站上 20/250 日线家数、创一年新高/新低家数（按分片汇总，可相加）。"""
import json, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "scripts")
import sources as S
from breadth_fetch import codes, UT


def one(sec):
    q = urllib.parse.urlencode({"secid": sec, "fields1": "f1", "fields2": "f51,f53,f57", "klt": "101", "fqt": "1",
                                "beg": "20120101", "end": "20500101", "ut": UT})
    for k in range(4):
        for host in ("push2his", "33.push2his", "63.push2his", "91.push2his"):
            try:
                j = S.jget(f"https://{host}.eastmoney.com/api/qt/stock/kline/get?" + q, "https://quote.eastmoney.com/")
                return sec, [(a.split(",")[0], float(a.split(",")[1]), float(a.split(",")[2]))
                             for a in (j.get("data") or {}).get("klines") or []]
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        time.sleep(2 * (k + 1))
    return sec, None


def add(agg, rows):
    # 字段：n 有涨跌的家数, up, dn, upamt, dnamt, n20, a20, n250, a250, nh, nl
    cl = [r[1] for r in rows]
    s20 = s250 = 0.0
    for i, (d, c, amt) in enumerate(rows):
        s20 += c; s250 += c
        if i >= 20: s20 -= cl[i - 20]
        if i >= 250: s250 -= cl[i - 250]
        if i == 0:
            continue
        a = agg.setdefault(d, [0] * 11)
        p = cl[i - 1]
        a[0] += 1
        if c > p: a[1] += 1; a[3] += amt
        elif c < p: a[2] += 1; a[4] += amt
        if i >= 19: a[5] += 1; a[6] += c > s20 / 20
        if i >= 249:
            a[7] += 1; a[8] += c > s250 / 250
            w = cl[i - 249:i + 1]
            a[9] += c >= max(w); a[10] += c <= min(w)


if __name__ == "__main__":
    i, n, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    cs = codes()
    print("股票总数", len(cs))
    cs = cs[i::n]
    import os
    prev = json.load(open(out)) if os.path.exists(out) else {"agg": {}, "done": []}
    agg, done = prev["agg"], set(prev["done"])
    cs = [c for c in cs if c not in done]
    print("这次要抓", len(cs))
    ok, fail = 0, 0
    with ThreadPoolExecutor(3) as ex:
        for sec, r in ex.map(one, cs):
            if r is not None:
                done.add(sec); ok += 1
                if len(r) > 1: add(agg, r)
            elif r is None:
                fail += 1
    print(f"分片 {i}/{n}：{len(cs)} 只，成功 {ok}，失败 {fail}")
    json.dump({"agg": agg, "done": sorted(done)}, open(out, "w"))
