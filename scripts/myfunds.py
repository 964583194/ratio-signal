"""我的基金：只看名单里的基金代码（不含金额），每只给一个结论：可以加 / 照常 / 先别加 / 可以减。只作提醒。

净值：天天基金 pingzhongdata 的日增长率连乘（分红已加回），缓存在 data/raw/myfunds_nav.json。
系统里已有信号的（A500、纳指100、黄金、债基）直接用系统结论；海外小仓位 4 只用 overseas.py 的提醒规则。
其余基金用通用规则（41 只基金合在一起回测验证过，见 stats）：
  可以减   比年线高 25% 以上，且市场温度在偏热 / 顶部区
  先别加   比年线高 25% 以上（涨太急）；或在年线下方且年线还在往下（下跌趋势）；或市场在偏热 / 顶部区
  可以加   站在年线上方、离最高点跌了 20% 以上（跌深后企稳），且市场不在偏热 / 顶部区
  照常     其余；跌得深但还没站回年线的，标“等站回年线再加”
另外标注：近两年跑输沪深300 超过 20 个百分点（考虑换成指数）、成立不到一年（信号仅供参考）、同组基金走势高度相似。
"""
import bisect
import datetime as dt
import json
import os
import re
import statistics as st
import time
import urllib.request

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.path.join(ROOT, "data", "myfunds_list.json")
CACHE = os.path.join(ROOT, "data", "raw", "myfunds_nav.json")
OUT = os.path.join(ROOT, "data", "myfunds.json")
CHARTS = {"000043": "嘉实美国成长股票"}   # 纳指页签画走势与年线
LABELS = {"add": ("可以加", "g1"), "hold": ("照常", "c0"), "wait": ("先别加", "h1"), "cut": ("可以减", "r1")}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def fetch_nav(code):
    """[[日期, 复权净值]]，用日增长率连乘"""
    t = S.http(f"https://fund.eastmoney.com/pingzhongdata/{code}.js?v={int(time.time())}", "https://fund.eastmoney.com/")
    L = json.loads(re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", t).group(1))
    out, v = [], 1.0
    for i, p in enumerate(L):
        er = p.get("equityReturn")
        if i and isinstance(er, (int, float)):
            v *= 1 + er / 100
        out.append([time.strftime("%Y-%m-%d", time.gmtime(p["x"] / 1000 + 8 * 3600)), round(v, 6)])
    if len(out) < 20:
        raise RuntimeError("净值太少")
    return out


def feats(s):
    """逐日：偏离年线、离最高点、年线是否向上、是否在年线下"""
    v = [x[1] for x in s]
    n = len(v)
    ma, acc, mx, out = [None] * n, 0.0, 0.0, []
    for i in range(n):
        acc += v[i]
        if i >= 250:
            acc -= v[i - 250]
        if i >= 249:
            ma[i] = acc / 250
    for i in range(n):
        mx = max(mx, v[i])
        if ma[i] is None or i < 269:
            out.append(None)
            continue
        out.append({"dev": v[i] / ma[i] - 1, "dd": v[i] / mx - 1, "up": ma[i] > ma[i - 20], "below": v[i] < ma[i]})
    return v, out


def judge(f, z):
    """通用规则 → (标签, 原因)"""
    if f is None:
        return "hold", "成立时间短，还算不出年线，先照常"
    hotmkt = z is not None and z >= 3
    if f["dev"] > .25:
        return ("cut", f"比年线高 {f['dev']:.0%}，市场又在偏热 / 顶部区，可以分批减") if hotmkt else \
               ("wait", f"比年线高 {f['dev']:.0%}，涨太急，先别加")
    if f["below"] and not f["up"]:
        return "wait", f"在年线下方、年线还在往下（下跌趋势），离最高点 {f['dd']:.0%}，跌得再多也先别接"
    if hotmkt:
        return "wait", "市场在偏热 / 顶部区，先别加"
    if not f["below"] and f["dd"] <= -.2:
        return "add", f"离最高点 {f['dd']:.0%}，已经站回年线（跌深后企稳），可以加"
    if f["below"] and f["dd"] <= -.3:
        return "hold", f"离最高点 {f['dd']:.0%}，价格在年线下 {-f['dev']:.0%}（年线还在往上，趋势没走坏），等站回年线再加"
    return "hold", f"离最高点 {f['dd']:.0%}，偏离年线 {f['dev']:+.0%}，照常"


def system_view(sysk, code):
    """系统里已有信号的基金：直接用各页签的结论"""
    if sysk == "os":
        for x in (_load(os.path.join(ROOT, "data", "overseas.json"), {}).get("funds") or []):
            if x["code"] == code:
                L = x["latest"]
                tag = "add" if L["cls"] in ("g1", "g2") else "wait" if L["zone"] == "过热" else "hold"
                return tag, f"海外小仓位规则：{L['zone']}，{L['action']}", "#os"
        return None
    d = _load(os.path.join(ROOT, "data", f"{sysk}.json"), {})
    L = d.get("latest") or {}
    if not L:
        return None
    m = L.get("mult")
    if sysk == "gold":    # 黄金六档
        tag = {"sell": "cut", "hot": "wait", "more": "add", "wait": "wait", "cheap": "add"}.get(L.get("state"), "hold")
    elif sysk == "bond":
        tag = "add" if L.get("zone") == "便宜" else "hold"
    elif sysk == "ndx":
        tag = "hold"
    else:
        tag = "add" if (m or 1) > 1 else "wait" if m == 0 else "hold"
    page = {"a500": "broad", "ndx": "ndx", "gold": "gold", "bond": "bond"}[sysk]
    return tag, f"{ {'a500': '宽基', 'ndx': '纳指100', 'gold': '黄金', 'bond': '债基'}[sysk]}页：{L.get('zone')}，{L.get('action')}", page


def run():
    lst = _load(LIST, {}).get("funds") or []
    cache = _load(CACHE, {})
    hs, _ = S.get_series("hs300")
    last_trade = max(hs)
    ok = fail = streak = 0
    for f in lst:
        c = f["code"]
        if (cache.get(c) and cache[c][-1][0] >= last_trade) or os.environ.get("NO_FETCH") or streak >= 3:
            continue
        try:
            cache[c] = fetch_nav(c)
            ok += 1
            streak = 0
        except Exception as e:  # noqa: BLE001
            fail += 1
            streak += 1
            print(f"我的基金：{c} {f['name']} 净值取不到（{e}），用缓存" + ("；连续 3 只失败，其余也先用缓存" if streak >= 3 else ""))
    if ok:
        with open(CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, separators=(",", ":"))
    T = _load(os.path.join(ROOT, "data", "temp.json"), {})
    zser = {r[0]: r[1] for r in T.get("series", [])}
    zk = sorted(zser)
    zone = lambda d: zser[zk[bisect.bisect_right(zk, d) - 1]] if zk and bisect.bisect_right(zk, d) else None  # noqa: E731
    znow = (T.get("latest") or {}).get("z")
    hk = sorted(hs)
    hsat = lambda d: hs[hk[max(0, bisect.bisect_right(hk, d) - 1)]]  # noqa: E731

    # ---- 回测：所有非债基合在一起，按当时状态看之后表现
    recs = []
    for f in lst:
        s = cache.get(f["code"])
        if not s or f.get("sys") == "bond" or len(s) < 300:
            continue
        v, F = feats(s)
        n = len(v)
        for i in range(n):
            x = F[i]
            if x is None:
                continue
            tag, _ = judge(x, zone(s[i][0]))
            fw = v[i + 120] / v[i] - 1 if i + 120 < n else None
            dn = min(v[i + 1:min(n, i + 121)]) / v[i] - 1 if i + 1 < n else None
            recs.append((tag, fw, dn, f["code"]))

    def stat(rs):
        xs = [r[1] for r in rs if r[1] is not None]
        dn = [r[2] for r in rs if r[2] is not None]
        return {"days": len(rs), "funds": len({r[3] for r in rs}), "avg": round(st.mean(xs), 4) if xs else None,
                "up": round(sum(x > 0 for x in xs) / len(xs), 3) if xs else None, "dd": round(st.mean(dn), 4) if dn else None}
    stats = {k: stat([r for r in recs if r[0] == k]) for k in LABELS}
    stats["all"] = stat(recs)

    # ---- 每只现在的结论
    out, weekly = [], {}
    for f in lst:
        c = f["code"]
        s = cache.get(c)
        row = {"code": c, "name": f["name"], "group": f["group"], "sys": f.get("sys"), "note": f.get("note")}
        if not s:
            row.update({"tag": "hold", "reason": "净值取不到，暂无结论"})
            out.append(row)
            continue
        v, F = feats(s)
        x = F[-1]
        sv = system_view(f["sys"], c) if f.get("sys") else None
        if sv:
            row["tag"], row["reason"], row["page"] = sv
        else:
            row["tag"], row["reason"] = judge(x, znow)
        mx = max(v)
        row.update({"date": s[-1][0], "dd": round(v[-1] / mx - 1, 4), "start": s[0][0],
                    "dev": None if x is None else round(x["dev"], 4), "trend": None if x is None else ("up" if not x["below"] and x["up"] else "down" if x["below"] and not x["up"] else "flat"),
                    "young": (dt.date.fromisoformat(s[-1][0]) - dt.date.fromisoformat(s[0][0])).days < 365})
        if len(s) >= 490 and not f.get("sys") and re.search(r"混合|股票", f["name"]) and not re.search(r"ETF|指数", f["name"]):   # 只看主动基金
            r = v[-1] / v[-489] - 1
            h = hsat(s[-1][0]) / hsat(s[-489][0]) - 1
            row["ex2y"] = round(r - h, 4)
        # 走势小图：近 2 年每周一个点
        pts = s[-500:][::5] + ([s[-1]] if (len(s[-500:]) - 1) % 5 else [])
        row["spark"] = [round(p[1] / pts[0][1], 4) for p in pts]
        weekly[c] = {p[0]: p[1] for p in s[-260:][::5]}
        out.append(row)
    # 同组走势相似度：近一年周涨跌的平均相关系数
    groups = {}
    for r in out:
        groups.setdefault(r["group"], []).append(r["code"])
    gsim = {}
    for g, cs in groups.items():
        if g == "系统内" or len(cs) < 2:   # 系统内各只是不同资产，不比相似度
            continue
        rets = {}
        for c in cs:
            w = weekly.get(c) or {}
            ks = sorted(w)
            rets[c] = {ks[i]: w[ks[i]] / w[ks[i - 1]] - 1 for i in range(1, len(ks))}
        cors = []
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                a, b = rets[cs[i]], rets[cs[j]]
                ks = sorted(set(a) & set(b))
                if len(ks) < 20:
                    continue
                xa, xb = [a[k] for k in ks], [b[k] for k in ks]
                try:
                    cors.append(st.correlation(xa, xb))
                except Exception:  # noqa: BLE001
                    pass
        gsim[g] = round(st.mean(cors), 2) if cors else None
    cnt = {k: sum(r["tag"] == k for r in out) for k in LABELS}
    data = {"updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
            "zone": (T.get("latest") or {}).get("zone"), "zone_verdict": (T.get("latest") or {}).get("verdict"),
            "labels": {k: list(v) for k, v in LABELS.items()}, "count": cnt, "funds": out, "group_sim": gsim, "stats": stats}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    # 纳指页签上单独画走势和年线的基金（复权净值）
    charts = {}
    for c, nm in CHARTS.items():
        sr = cache.get(c)
        if not sr or len(sr) < 260:
            continue
        v, _ = feats(sr)
        ma = [None] * len(v)
        for i in range(249, len(v)):
            ma[i] = sum(v[i - 249:i + 1]) / 250
        charts[c] = {"name": nm, "date": sr[-1][0], "series": [[sr[i][0], round(v[i], 4), round(ma[i], 4)] for i in range(len(v)) if ma[i]]}
    with open(os.path.join(ROOT, "data", "fund_charts.json"), "w", encoding="utf-8") as fh:
        json.dump(charts, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{len(out)} 只，" + "、".join(f"{LABELS[k][0]} {cnt[k]}" for k in LABELS) + f"；净值更新 {ok} 只，失败 {fail} 只")
    return data


if __name__ == "__main__":
    run()
