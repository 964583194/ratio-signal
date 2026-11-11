"""黄金：压舱石，平时照常买，便宜时多入一点，涨得极端时卖一部分。黄金页签的结论和每周倍数都由这里的 states() 决定。

六档（从上往下，先满足的算；2026-11-11 定，回测见页面）：
  可以卖一部分  比年线高 30% 以上：卖 1/3（每段行情一次），这周不买
  不动          比年线高 25% 以上：暂停买，定投款买红利低波100
  可以多买      ETF 资金恐慌撤出（SPDR 持仓 60 日减少 ≥8%）：2 倍
  先等等        刚开始跌（离最高点 ≥15% 但还在 10 个月线上方），或波动很大（≥30% 或近 5 年 90% 分位以上）：0.5 倍
  便宜，入一点  比年线低 5% 以上：1.5 倍
  买            其余：1 倍

逐个回测过的 5 个现成模型（黄金ETF 518880，2014 年起）：
  用      ETF 资金撤出：SPDR 黄金 ETF 持仓 60 个交易日减少 ≥8%（大资金恐慌撤出，历史上是好买点）
  看方向  10 个月趋势：价格在 210 日均线上方还是下方（只看方向，不用来买卖：择时反而更差）
  看风险  波动率：20 日年化波动率；≥30% 或在近 5 年 90% 分位以上算“还没稳定”
  不用    实际利率（能解释已经发生的涨跌，不能预测）、金银比（时灵时不灵）、期货持仓（样本是牛市，反向不成立）
"""
import bisect
import datetime as dt
import json
import math
import os
import statistics as st

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "goldmodel.json")
START = "2014-08-01"
OUTFLOW = -0.08     # SPDR 60 日持仓变化
VOL_HI = 0.30


def ffill(src):
    ks = sorted(src)

    def f(d):
        j = bisect.bisect_right(ks, d) - 1
        return src[ks[j]] if j >= 0 else None
    return f


def pct_in(vals, i, w, minn=200):
    v = vals[i]
    xs = [x for x in vals[max(0, i - w):i + 1] if x is not None]
    return None if v is None or len(xs) < minn else sum(x < v for x in xs) / len(xs)


STATES = [  # key, 结论, 颜色, 倍数, 本周操作
    ("sell", "可以卖一部分", "r1", 0.0, "卖出 1/3（每段行情只卖一次），这周不买，定投款买红利低波100"),
    ("hot", "不动", "h1", 0.0, "暂停买入，定投款买红利低波100"),
    ("more", "可以多买", "g2", 2.0, "2 倍定投"),
    ("wait", "先等等", "h1", 0.5, "先少买：0.5 倍定投，剩下的放红利低波100"),
    ("cheap", "便宜，入一点", "g1", 1.5, "1.5 倍定投"),
    ("buy", "买", "c0", 1.0, "照常 1 倍定投"),
]
SMAP = {k: (lab, cls, m, act) for k, lab, cls, m, act in STATES}


def states(days, px):
    """逐日判断六档，返回 [(key, 原因)]。要用 SPDR 持仓（缓存兜底）"""
    n = len(px)
    try:
        spf = ffill(S.get_series("spdr")[0])
    except Exception:  # noqa: BLE001
        spf = lambda d: None  # noqa: E731
    SP = [spf(d) for d in days]
    m210, m250, a1, a2, peak, out = [None] * n, [None] * n, 0.0, 0.0, 0.0, []
    for i, v in enumerate(px):
        a1 += v
        a2 += v
        if i >= 210:
            a1 -= px[i - 210]
        if i >= 250:
            a2 -= px[i - 250]
        if i >= 209:
            m210[i] = a1 / 210
        if i >= 249:
            m250[i] = a2 / 250
    vol = [None] * n
    for i in range(21, n):
        r = [math.log(px[j] / px[j - 1]) for j in range(i - 19, i + 1)]
        vol[i] = st.pstdev(r) * math.sqrt(252)
    for i in range(n):
        peak = max(peak, px[i])
        dd = px[i] / peak - 1
        if m250[i] is None:
            out.append(("buy", "年线还算不出来，照常买"))
            continue
        dev = px[i] / m250[i] - 1
        w = [x for x in vol[max(0, i - 1250):i + 1] if x is not None]
        vp = sum(x < vol[i] for x in w) / len(w) if vol[i] is not None and len(w) > 200 else 0
        s60 = SP[i] / SP[i - 60] - 1 if i >= 60 and SP[i] and SP[i - 60] else None
        if dev > .30:
            out.append(("sell", f"比年线高 {dev:.0%}，涨得极端"))
        elif dev > .25:
            out.append(("hot", f"比年线高 {dev:.0%}，涨太急"))
        elif s60 is not None and s60 <= OUTFLOW:
            out.append(("more", f"ETF 资金恐慌撤出（近 60 日持仓 {s60:+.0%}）"))
        elif dd <= -.15 and m210[i] and px[i] > m210[i]:
            out.append(("wait", f"离最高点 {dd:.0%}，但还在 10 个月线上方，刚开始跌"))
        elif vol[i] is not None and (vol[i] >= VOL_HI or vp >= .9):
            out.append(("wait", f"波动很大（{vol[i]:.0%}），还没稳定"))
        elif dev <= -.05:
            out.append(("cheap", f"比年线低 {-dev:.0%}，便宜"))
        else:
            out.append(("buy", f"比年线 {dev:+.0%}，位置正常"))
    return out


def run():
    g, _ = S.get_series("gold")
    days = sorted(g)
    px = [g[d] for d in days]
    n = len(px)
    opt = {}
    for k in ("spdr", "real10", "ag0"):
        try:
            opt[k] = ffill(S.get_series(k)[0])
        except Exception as e:  # noqa: BLE001
            print(f"黄金分析：{k} 取不到（{e}）")
            opt[k] = lambda d: None  # noqa: E731
    SP = [opt["spdr"](d) for d in days]
    RY = [opt["real10"](d) for d in days]
    AG = [opt["ag0"](d) for d in days]
    ma210, ma250, acc, acc2 = [None] * n, [None] * n, 0.0, 0.0
    peak, dd = 0.0, []
    for i, v in enumerate(px):
        acc += v
        acc2 += v
        if i >= 210:
            acc -= px[i - 210]
        if i >= 250:
            acc2 -= px[i - 250]
        if i >= 209:
            ma210[i] = acc / 210
        if i >= 249:
            ma250[i] = acc2 / 250
        peak = max(peak, v)
        dd.append(v / peak - 1)
    vol = [None] * n
    for i in range(21, n):
        r = [math.log(px[j] / px[j - 1]) for j in range(i - 19, i + 1)]
        vol[i] = st.pstdev(r) * math.sqrt(252)
    volp = [pct_in(vol, i, 1250) for i in range(n)]
    sp60 = [SP[i] / SP[i - 60] - 1 if i >= 60 and SP[i] and SP[i - 60] else None for i in range(n)]
    ratio = [px[i] / AG[i] if AG[i] else None for i in range(n)]
    ratp = [pct_in(ratio, i, 1250) for i in range(n)]

    K = [i for i in range(n) if days[i] >= START and ma250[i] is not None]

    def fwd(i, h):
        return px[i + h] / px[i] - 1 if i + h < n else None

    def stat(ks):
        o = {"days": len(ks)}
        for h in (60, 120):
            xs = [fwd(i, h) for i in ks if fwd(i, h) is not None]
            o[str(h)] = {"avg": round(st.mean(xs), 4), "up": round(sum(x > 0 for x in xs) / len(xs), 3)} if len(xs) > 20 else None
        dn = [min(px[i + 1:min(n, i + 121)]) / px[i] - 1 for i in ks if i + 1 < n]
        o["dd"] = round(st.mean(dn), 4) if dn else None
        return o

    def episodes(flag):
        out, cur = [], None
        for i in K:
            if flag(i):
                if cur and i - cur[1] <= 20:
                    cur[1] = i
                else:
                    if cur:
                        out.append(cur)
                    cur = [i, i]
        if cur:
            out.append(cur)
        res = []
        for a, b in out:
            r120 = fwd(a, 120)
            res.append({"from": days[a], "to": days[b], "r60": None if fwd(a, 60) is None else round(fwd(a, 60), 4),
                        "r120": None if r120 is None else round(r120, 4),
                        "dn": round(min(px[a + 1:min(n, a + 121)]) / px[a] - 1, 4) if a + 1 < n else None})
        return res
    is_out = lambda i: sp60[i] is not None and sp60[i] <= OUTFLOW  # noqa: E731
    is_in = lambda i: sp60[i] is not None and sp60[i] >= -OUTFLOW  # noqa: E731
    above = lambda i: ma210[i] is not None and px[i] > ma210[i]  # noqa: E731
    vhot = lambda i: vol[i] is not None and (vol[i] >= VOL_HI or (volp[i] or 0) >= .9)  # noqa: E731
    # 实际利率：同期 3 个月变化的相关（两段时期对比）
    def corr(a, b):
        xs = [(RY[i] - RY[i - 63], px[i] / px[i - 63] - 1) for i in K if a <= days[i][:4] <= b and RY[i] is not None and RY[i - 63] is not None]
        try:
            return round(st.correlation([x for x, _ in xs], [y for _, y in xs]), 2) if len(xs) > 50 else None
        except Exception:  # noqa: BLE001
            return None
    stats = {
        "all": stat(K),
        "outflow": stat([i for i in K if is_out(i)]), "inflow": stat([i for i in K if is_in(i)]),
        "above": stat([i for i in K if above(i)]), "below": stat([i for i in K if not above(i)]),
        "vol_hot": stat([i for i in K if vhot(i)]), "vol_calm": stat([i for i in K if volp[i] is not None and volp[i] <= .1]),
        "dd15": stat([i for i in K if dd[i] <= -.15]), "hot25": stat([i for i in K if ma250[i] and px[i] / ma250[i] - 1 > .25]),
        "ratio_low": stat([i for i in K if ratp[i] is not None and ratp[i] <= .2]),
        "real_corr": {"2013-2020": corr("2013", "2020"), "2022-2026": corr("2022", "2026")},
    }
    # 择时对照：均线上方持有、下方空仓 vs 一直持有
    def timing(sig):
        v, pk, mdd = 1.0, 1.0, 0.0
        for i in range(K[0], n - 1):
            v *= 1 + (px[i + 1] / px[i] - 1 if sig(i) else 0.015 / 252)
            pk = max(pk, v)
            mdd = min(mdd, v / pk - 1)
        yrs = (n - 1 - K[0]) / 252
        return {"cagr": round(v ** (1 / yrs) - 1, 4), "mdd": round(mdd, 4)}
    stats["timing"] = {"hold": timing(lambda i: True), "trend": timing(above)}
    eps = episodes(is_out)

    # ---- 现在
    i = n - 1
    dev = px[i] / ma250[i] - 1
    lights = {
        "outflow": {"on": is_out(i), "value": sp60[i], "tons": SP[i]},
        "trend": {"up": above(i), "dev": round(px[i] / ma210[i] - 1, 4)},
        "vol": {"hot": vhot(i), "value": None if vol[i] is None else round(vol[i], 4), "pct": None if volp[i] is None else round(volp[i], 3)},
    }
    ST = states(days, px)
    key, why = ST[i]
    lab, cls, mult, act = SMAP[key]
    verdict = f"{lab}：{why} → {act}"
    state = lab
    # 各档历史表现（之后 60 / 120 个交易日）
    state_stats = {k: stat([j for j in K if ST[j][0] == k]) for k, *_ in STATES}
    sell_eps = []
    for e in episodes(lambda j: ST[j][0] == "sell"):
        sell_eps.append(e)
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": days[i], "close": px[i], "dd": round(dd[i], 4), "dev250": round(dev, 4), "key": key, "label": lab, "cls": cls, "mult": mult, "why": why,
                   "lights": lights, "verdict": verdict, "action": act, "state": state,
                   "ref": {"real10": RY[i], "real10_chg3m": None if RY[i] is None or RY[i - 63] is None else round(RY[i] - RY[i - 63], 2),
                           "ratio_pct": None if ratp[i] is None else round(ratp[i], 3)}},
        "series": [[days[k], px[k], None if ma210[k] is None else round(ma210[k], 4), SP[k], None if vol[k] is None else round(vol[k], 4), RY[k]]
                   for k in range(n) if days[k] >= START],
        "stats": stats, "outflow_episodes": eps, "sell_episodes": sell_eps,
        "states": [{"key": k, "label": lab_, "cls": c_, "mult": m_, "action": a_, **state_stats[k]} for k, lab_, c_, m_, a_ in STATES],
        "state_series": "".join("SHMWCB"["sell hot more wait cheap buy".split().index(ST[j][0])] for j in range(n) if days[j] >= START),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{days[i]} {verdict}")
    return data


if __name__ == "__main__":
    run()
