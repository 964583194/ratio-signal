"""组合信号（实验）：几个指标同时出现才算的"组合"，每个组合对应一句怎么做。只作提醒，不改任何倍数和买卖规则。

组合（同时亮多个时，按下面顺序取第一个当标题）：
  跟进买入  低位（市场温度底部 / 偏冷）+ 近 20 天国家队急买（5 日净申购 ≥ 沪深300 市值 1.5‰）
  见底加码  破净率见底 + 见底灯 ≥4 + 方向（宽度、M1、信贷脉冲）至少 2 个回升
  高位撤离  高位（偏热 / 顶部）+ 近 20 天国家队集中卖出（5 日净赎回 ≥ 市值 1.5‰ 或 20 日 ≥ 2‰；2023 年前没有申赎数据，用 20 日份额 ≤ −15%）
国家队买卖都用同一把尺子：净申购 ÷ 沪深300 流通市值（相对值）。不用"占成交额"：高位时成交额很大，卖出会被稀释。
  高位护盘  高位 + 托底资金大幅流入（20 日份额 ≥ +15%）：高位救市，往往还要跌
  高位走弱  高位 + 方向 3 个都在走弱
  磨底等待  低位 + 方向 3 个都在走弱 + 没有国家队急买
都没亮：照规则买。
回测：每个组合亮着的每一天，之后 20 / 60 / 120 / 250 个交易日沪深300 的表现。
"""
import bisect
import datetime as dt
import json
import os


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "verdict.json")
ZN = ["底部", "偏冷", "正常", "偏热", "顶部"]
RUSH, BIG = 0.0015, 0.002
SIG = [  # key, 名称, 颜色, 怎么做, 条件说明, 回测从哪年起
    ("follow", "跟进买入", "g2", "跟着买：按规则买，规则让加码时别犹豫，备用金可以用起来",
     "低位（底部 / 偏冷）+ 近 20 天国家队急买", "2023"),
    ("bottom", "见底加码", "g2", "按规则买，加码别犹豫：便宜到极点，而且开始好转",
     "破净率见底 + 见底灯 ≥4 + 方向至少 2 个回升", "2013"),
    ("exit", "高位撤离", "r1", "不追加；各板块到卖出线就卖，宁可早一点",
     "高位（偏热 / 顶部）+ 近 20 天国家队集中卖出", "2013"),
    ("rescue", "高位护盘", "r1", "别被托市迷惑：不追加，按规则卖",
     "高位 + 国家队大幅流入（高位救市）", "2013"),
    ("weak", "高位走弱", "h1", "不追加，留意各板块卖出信号",
     "高位 + 方向 3 个都在走弱", "2013"),
    ("grind", "磨底等待", "g1", "便宜但还在跌：分批慢慢买，别一次把备用金打光",
     "低位 + 方向 3 个都在走弱 + 没有国家队急买", "2013"),
]


def _load(n):
    with open(os.path.join(ROOT, "data", n), encoding="utf-8") as fh:
        return json.load(fh)


def run():
    T = _load("temp.json")["series"]          # [日期, 区间 0~4, 沪深300, 见底灯, 见顶灯, 各灯, 方向]
    names = _load("temp.json").get("bot_names") or []
    E = {x[0]: x[3] for x in _load("etf300.json")["series"]}
    NS = _load("ntf.json")["series"]
    E3 = _load("etf300.json").get("latest") or {}
    cap0 = E3["size"] / (E3["ratio"] / 100) if E3.get("size") and E3.get("ratio") else None
    # 每天的沪深300 流通市值：ntf.json 第 7 列；旧数据没有时按沪深300 点位从最新一次推算
    NT = {x[0]: (x[5], x[6] if len(x) > 6 and x[6] else (cap0 * x[4] / NS[-1][4] if cap0 else None))
          for x in NS if len(x) > 5 and x[5] is not None}
    NT = {k: v for k, v in NT.items() if v[1]}
    D, P = [x[0] for x in T], [x[2] for x in T]
    n = len(D)
    ek = sorted(E)

    def shares(d):
        j = bisect.bisect_right(ek, d) - 1
        return E[ek[j]] if j >= 0 else None
    c20, r5, r20 = [None] * n, [None] * n, [None] * n
    for k in range(n):
        if k >= 20:
            a, b = shares(D[k]), shares(D[k - 20])
            c20[k] = a / b - 1 if a and b else None
        for w, arr in ((5, r5), (20, r20)):
            ds = D[max(0, k - w + 1):k + 1]
            if k >= w - 1 and all(d in NT for d in ds):
                arr[k] = sum(NT[d][0] for d in ds) / NT[D[k]][1]
    rush = [x is not None and x >= RUSH for x in r5]
    rush20 = [any(rush[max(0, k - 19):k + 1]) for k in range(n)]
    sell = [((r5[k] is not None and r5[k] <= -RUSH) or (r20[k] is not None and r20[k] <= -BIG)) if r5[k] is not None
            else (c20[k] is not None and c20[k] <= -0.15) for k in range(n)]
    sell20 = [any(sell[max(0, k - 19):k + 1]) for k in range(n)]
    pbi = names.index("破净率") if "破净率" in names else 0
    F = {"z": [x[1] for x in T], "bot": [x[3] for x in T], "pb": [x[5][pbi] == "1" for x in T],
         "nup": [x[6].count("1") for x in T], "out": [c is not None and c <= -0.15 for c in c20],
         "inn": [c is not None and c >= 0.15 for c in c20], "rush": rush20, "sell": sell20}
    low = lambda k: F["z"][k] <= 1  # noqa: E731
    high = lambda k: F["z"][k] >= 3  # noqa: E731
    cond = {
        "follow": lambda k: low(k) and F["rush"][k],
        "bottom": lambda k: F["pb"][k] and F["bot"][k] >= 4 and F["nup"][k] >= 2,
        "exit": lambda k: high(k) and F["sell"][k],
        "rescue": lambda k: high(k) and F["inn"][k],
        "weak": lambda k: high(k) and F["nup"][k] == 0,
        "grind": lambda k: low(k) and F["nup"][k] == 0 and not F["rush"][k],
    }

    def agg(idx):
        o = {"days": len(idx)}
        for h in (20, 60, 120, 250):
            r = [P[k + h] / P[k] - 1 for k in idx if k + h < n]
            o[str(h)] = {"avg": round(sum(r) / len(r), 4), "up": round(sum(x > 0 for x in r) / len(r), 3), "n": len(r)} if r else None
        return o

    def episodes(c, since):
        eps, last = [], -999
        for k in range(n):
            if D[k] >= since and c(k):
                if k - last > 20:
                    eps.append(D[k])
                last = k
        return eps
    i = n - 1
    sigs = []
    for key, name, cls, act, rule, since in SIG:
        c = cond[key]
        idx = [k for k in range(n) if D[k] >= since and c(k)]
        on = c(i)
        run_from = None
        if on:
            k = i
            while k > 0 and c(k - 1):
                k -= 1
            run_from = D[k]
        sigs.append({"key": key, "name": name, "cls": cls, "act": act, "rule": rule, "since": since, "on": on, "from": run_from,
                     "stats": agg(idx), "eps": episodes(c, since)})
    base = {s: agg([k for k in range(n) if D[k] >= s]) for s in ("2013", "2023")}
    lit = [s for s in sigs if s["on"]]
    head = lit[0] if lit else None
    zi = F["z"][i]
    facts = [
        {"name": "市场温度", "text": f"{ZN[zi]}（见底灯 {T[i][3]} / 6，见顶灯 {T[i][4]} / 7）", "tag": "低位" if zi <= 1 else "高位" if zi >= 3 else "中间"},
        {"name": "国家队急买", "text": ("近 20 天出现过（" + next(D[k] for k in range(max(0, i - 19), i + 1) if rush[k]) + "）") if F["rush"][i]
         else f"近 20 天没有（近 5 日净申购占沪深300 市值 {(r5[i] if r5[i] is not None else (r5[i - 1] or 0)) * 1000:.2f}‰，≥1.5‰ 算急买）", "tag": "有" if F["rush"][i] else "没有"},
        {"name": "托底资金", "text": "近 20 日份额 " + (f"{c20[i] * 100:+.0f}%" if c20[i] is not None else "—")
         + ("（大幅流入）" if F["inn"][i] else "（集中卖出）" if F["sell"][i] else ""), "tag": "流入" if F["inn"][i] else "卖出" if F["sell"][i] else "平稳"},
        {"name": "方向", "text": f"宽度、M1、信贷脉冲 {F['nup'][i]} / 3 回升", "tag": "回升" if F["nup"][i] >= 2 else "走弱" if F["nup"][i] == 0 else "一般"},
        {"name": "破净率", "text": "已到见底标准" if F["pb"][i] else "没到见底标准", "tag": "见底" if F["pb"][i] else "没到"},
    ]
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": D[i], "head": head["key"] if head else None,
                   "title": head["name"] if head else "没有特别信号",
                   "act": head["act"] if head else "照规则买，不用额外做什么",
                   "cls": head["cls"] if head else "c0", "lit": [s["key"] for s in lit], "facts": facts},
        "signals": sigs, "base": base,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{D[i]} {data['latest']['title']}（亮着：{'、'.join(s['name'] for s in lit) or '无'}）")
    return data


if __name__ == "__main__":
    run()
