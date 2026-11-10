"""见顶信号灯：7 个信号各自独立亮灯，同时亮 ≥3 个算接近顶部，2 个算偏热。只作提醒，不改定投规则。

  挤   成交额集中度：每月成交额前 5% 的个股占全市场（沪深 A 股）成交额 ≥ 45%
  贵   股债利差（沪深300 盈利收益率 − 十年国债）≤ 近 10 年 10% 分位
  疯   破净率 ≤ 近 10 年 10% 分位（几乎没有便宜股，普涨式顶部）
  热   创业板50 ÷ 红利低波100 ≥ 近 10 年 89% 分位（轮动第一档卖出线）
  走   托底资金：头部沪深300 ETF 近 40 个交易日份额减少 ≥ 15%（2023 年起才有意义）
  分歧 宽度背离：沪深300 在近一年最高点 5% 以内，但站上 12 个月均线的股票 < 45%
  高估 巴菲特指标（总市值 ÷ GDP）≥ 近 10 年 90% 分位

集中度和宽度是月度数据：已完成的月份来自每月一次的全市场月线（.github/workflows/breadth.yml），
当月用每天收盘后的全市场行情快照累计（成交额）和最新价对比前 12 个月均线（宽度），算出来是“本月至今”。
"""
import bisect
import datetime as dt
import json
import math
import os
import time
import urllib.parse

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "topsig.json")
START = "2010-01-01"
W10 = 2440          # 约 10 年交易日
NAMES = ["挤", "贵", "疯", "热", "走", "分歧", "高估"]
DESC = {"挤": "前 5% 个股占成交额 ≥45%（资金抱团）", "贵": "股债利差在近 10 年最低 10%",
        "疯": "破净率在近 10 年最低 10%（几乎没有便宜股）", "热": "创业板 ÷ 红利在近 10 年 89% 分位以上",
        "走": "国家队近 40 日份额减少 ≥15%", "分歧": "指数近一年高位，但站上年线的股票 <45%",
        "高估": "总市值 ÷ GDP 在近 10 年 90% 分位以上"}
UT = "fa5fd1943c7b386f172d6893dbfba10b"


def _load(name, default):
    try:
        with open(os.path.join(RAW, name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def _save(name, obj):
    with open(os.path.join(RAW, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))


def snapshot():
    """全部沪深 A 股当天行情：{代码: (最新价, 成交额)}"""
    out = {}
    for pn in range(1, 80):
        q = urllib.parse.urlencode({"pn": pn, "pz": 200, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f12",
                                    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23", "fields": "f2,f6,f12,f13", "ut": UT})
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
        for r in rows:
            p, a = r.get("f2"), r.get("f6")
            if isinstance(p, (int, float)) and isinstance(a, (int, float)):
                out[f"{r['f13']}.{r['f12']}"] = (float(p), float(a))
    if len(out) < 3000:
        raise RuntimeError(f"全市场快照只有 {len(out)} 只")
    return out


def update_month(M, day):
    """用当天快照更新“本月至今”的集中度和宽度（同一天只累计一次）"""
    mon = day[:7]
    mtd = _load("mtd_amt.json", {})
    if mtd.get("month") != mon:
        mtd = {"month": mon, "days": [], "amt": {}}
    if day in mtd["days"]:
        return "已累计过"
    snap = snapshot()
    for c, (_p, a) in snap.items():
        if a > 0:
            mtd["amt"][c] = mtd["amt"].get(c, 0) + a
    mtd["days"].append(day)
    _save("mtd_amt.json", mtd)
    xs = sorted((v for v in mtd["amt"].values() if v > 0), reverse=True)
    e = dict(M.get(mon) or {})
    if len(xs) > 3000:
        e["top5"] = round(sum(xs[:math.ceil(len(xs) * .05)]) / sum(xs), 4)
        e["nstk"] = len(xs)
    prev = _load("stock_prev12.json", {})
    if prev.get("month") == mon and prev.get("closes"):
        n = up = 0
        for c, cl in prev["closes"].items():
            if c in snap and len(cl) == 12 and snap[c][0] > 0:
                n += 1
                up += snap[c][0] > sum(cl) / 12
        if n > 2000:
            e["ma12"] = round(up / n, 4)
    e["partial"] = True
    e["days"] = len(mtd["days"])
    M[mon] = e
    return f"本月第 {len(mtd['days'])} 天，{len(xs)} 只"


def pct_series(vals, W=W10, min_n=250):
    out = []
    for i, v in enumerate(vals):
        if v is None:
            out.append(None)
            continue
        w = [x for x in vals[max(0, i - W):i + 1] if x is not None]
        out.append(sum(x < v for x in w) / len(w) if len(w) > min_n else None)
    return out


def ffill(src):
    ks = sorted(src)
    return lambda d: src[ks[bisect.bisect_right(ks, d) - 1]] if bisect.bisect_right(ks, d) else None


def run():
    M = _load("breadth_monthly.json", {})
    hs, _ = S.get_series("hs300")
    day = max(hs)
    try:
        msg = update_month(M, day)
        _save("breadth_monthly.json", M)
        print("见顶信号灯：当月集中度/宽度", msg)
    except Exception as e:  # noqa: BLE001  快照失败就用已有月度数据
        print(f"见顶信号灯：全市场快照失败（{e}），当月用已有数据")
    cyb, _ = S.get_series("cyb50")
    hl, _ = S.get_series("hl100")
    pb, _ = S.get_series("pb_below")
    pe, _ = S.get_series("pe300")
    y, _ = S.get_series("cn10y")
    try:
        bf, _ = S.get_series("buffett")
    except Exception:  # noqa: BLE001
        bf = {}
    try:
        with open(os.path.join(ROOT, "data", "etf300.json"), encoding="utf-8") as fh:
            E = json.load(fh)["series"]
    except Exception:  # noqa: BLE001
        E = []
    eS = {r[0]: r[3] for r in E}
    ek = sorted(eS)
    days = [d for d in sorted(hs) if d >= "2005-01-01"]
    P, PE, Y, BF = ffill(pb), ffill(pe), ffill(y), ffill(bf) if bf else (lambda d: None)
    close = [hs[d] for d in days]
    pbp = pct_series([P(d) for d in days])
    erp = pct_series([(100 / PE(d) - Y(d)) if PE(d) and Y(d) is not None else None for d in days])
    rr = pct_series([(cyb[d] / hl[d]) if d in cyb and d in hl else None for d in days])
    bfp = pct_series([BF(d) for d in days], min_n=500)
    rows = []
    for i, d in enumerate(days):
        if d < START:
            continue
        mo = M.get(d[:7]) or {}
        hi = max(close[max(0, i - 250):i + 1])
        walk = False
        if d >= "2023-01-01" and ek:
            j = bisect.bisect_right(ek, d) - 1
            walk = j >= 40 and eS[ek[j]] / eS[ek[j - 40]] - 1 <= -0.15
        L = [(mo.get("top5") or 0) >= 0.45,
             erp[i] is not None and erp[i] <= 0.10,
             pbp[i] is not None and pbp[i] <= 0.10,
             rr[i] is not None and rr[i] >= 0.89,
             walk,
             mo.get("ma12") is not None and close[i] >= hi * 0.95 and mo["ma12"] < 0.45,
             bfp[i] is not None and bfp[i] >= 0.90]
        rows.append({"d": d, "L": [int(x) for x in L], "close": close[i],
                     "v": [mo.get("top5"), erp[i], pbp[i], rr[i], None, mo.get("ma12"), bfp[i]]})
    n = len(rows)

    def fwd(i, h):
        return rows[i + h]["close"] / rows[i]["close"] - 1 if i + h < n else None

    def stats(ks):
        st = {"days": len(ks)}
        for h in (60, 120, 250):
            xs = [fwd(i, h) for i in ks if fwd(i, h) is not None]
            st[str(h)] = {"avg": round(sum(xs) / len(xs), 4), "up": round(sum(x > 0 for x in xs) / len(xs), 3)} if xs else None
        return st
    cnt = [sum(r["L"]) for r in rows]
    S3 = stats([i for i in range(n) if cnt[i] >= 3])
    S2 = stats([i for i in range(n) if cnt[i] >= 2])
    S0 = stats(list(range(n)))
    segs, cur = [], None    # 亮 ≥3 个的时段
    for i in range(n):
        if cnt[i] >= 3:
            if cur and i - cur[1] <= 5:
                cur[1] = i
            else:
                if cur:
                    segs.append(cur)
                cur = [i, i]
    if cur:
        segs.append(cur)
    segs = [[rows[a]["d"], rows[b]["d"]] for a, b in segs if b - a >= 3]
    L = rows[-1]
    c = cnt[-1]
    zone, act, cls = (("接近顶部", "分批止盈，轮动卖出可以更果断，A500 / 沪深300 少买", "h1") if c >= 3 else
                      ("偏热", "不追加，A500 / 沪深300 少买", "h1") if c == 2 else ("正常", "不额外操作", "c0"))
    cm = M.get(L["d"][:7]) or {}
    val = {"挤": cm.get("top5"), "贵": L["v"][1], "疯": L["v"][2], "热": L["v"][3], "分歧": cm.get("ma12"), "高估": L["v"][6]}
    if ek:
        j = len(ek) - 1
        val["走"] = round(eS[ek[j]] / eS[ek[j - 40]] - 1, 4) if j >= 40 else None
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": L["d"], "count": c, "lit": [NAMES[k] for k in range(7) if L["L"][k]], "zone": zone, "action": act, "cls": cls,
                   "values": val, "month_partial": bool(cm.get("partial")), "month_days": cm.get("days")},
        "names": NAMES, "desc": DESC,
        "series": [[r["d"], sum(r["L"]), r["close"], "".join(map(str, r["L"]))] for r in rows],
        "monthly": [[k, v.get("top5"), v.get("ma12")] for k, v in sorted(M.items()) if k >= "2010-01"],
        "stats": {"ge3": S3, "ge2": S2, "all": S0}, "segments": segs,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{L['d']} 亮 {c} 个 {data['latest']['lit']}，{zone}；≥3 个的时段 {segs}")
    return data


if __name__ == "__main__":
    run()
