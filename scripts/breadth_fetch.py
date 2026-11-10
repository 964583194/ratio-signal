"""每月一次：全部沪深 A 股月线（前复权收盘 + 成交额），分片并行抓取。用法：python breadth_fetch.py 分片号 分片数 输出文件"""
import json
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import sources as S

UT = "fa5fd1943c7b386f172d6893dbfba10b"


def codes():
    out = []
    for pn in range(1, 80):
        q = urllib.parse.urlencode({"pn": pn, "pz": 200, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f12",
                                    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23", "fields": "f12,f13", "ut": UT})
        d = None
        for k in range(3):
            try:
                d = S.jget("https://push2.eastmoney.com/api/qt/clist/get?" + q, "https://quote.eastmoney.com/")
                break
            except Exception:  # noqa: BLE001
                time.sleep(2 * (k + 1))
        rows = ((d or {}).get("data") or {}).get("diff") or []
        if not rows:
            break
        out += [f"{r['f13']}.{r['f12']}" for r in rows]
    return sorted(set(out))


def one(sec):
    q = urllib.parse.urlencode({"secid": sec, "fields1": "f1", "fields2": "f51,f53,f57", "klt": "103", "fqt": "1",
                                "beg": "20090101", "end": "20500101", "ut": UT})
    for k in range(4):
        for host in ("push2his", "33.push2his", "63.push2his", "91.push2his"):
            try:
                j = S.jget(f"https://{host}.eastmoney.com/api/qt/stock/kline/get?" + q, "https://quote.eastmoney.com/")
                return sec, [[a.split(",")[0][:7], float(a.split(",")[1]), float(a.split(",")[2])]
                             for a in (j.get("data") or {}).get("klines") or []]
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        time.sleep(2 * (k + 1))
    return sec, None


if __name__ == "__main__":
    i, n, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    cs = codes()
    print("股票总数", len(cs))
    cs = cs[i::n]
    res, fail = {}, 0
    with ThreadPoolExecutor(8) as ex:
        for sec, r in ex.map(one, cs):
            if r:
                res[sec] = r
            else:
                fail += 1
    print(f"分片 {i}/{n}：{len(cs)} 只，成功 {len(res)}，失败 {fail}")
    if len(res) < len(cs) * 0.9:
        raise SystemExit("失败太多")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, separators=(",", ":"))
