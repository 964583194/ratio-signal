"""黄金分析（独立页面 gold.html）：只作参考，黄金页签的定投规则不变（回撤 ≥15% 买 2 倍，比年线高 25% 以上暂停）。

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
    G = {}
    try:
        with open(os.path.join(ROOT, "data", "gold.json"), encoding="utf-8") as fh:
            G = json.load(fh)["latest"]
    except Exception:  # noqa: BLE001
        pass
    dev = px[i] / ma250[i] - 1
    rule = G.get("action") or ("暂停买入" if dev > .25 else "2 倍定投" if dd[i] <= -.15 else "正常定投")
    lights = {
        "outflow": {"on": is_out(i), "value": sp60[i], "tons": SP[i]},
        "trend": {"up": above(i), "dev": round(px[i] / ma210[i] - 1, 4)},
        "vol": {"hot": vhot(i), "value": None if vol[i] is None else round(vol[i], 4), "pct": None if volp[i] is None else round(volp[i], 3)},
    }
    w_price = f"已经便宜（离最高点 {dd[i]:.0%}）" if dd[i] <= -.15 else f"涨太急（比年线高 {dev:.0%}）" if dev > .25 else f"价格正常（离最高点 {dd[i]:.0%}）"
    w_flow = "ETF 资金在恐慌撤出" if lights["outflow"]["on"] else "还没有资金恐慌撤出"
    w_trend = "趋势向上" if lights["trend"]["up"] else "趋势还在走弱"
    w_vol = "波动很大、还没稳定" if lights["vol"]["hot"] else "波动偏高" if (volp[i] or 0) >= .8 else "波动正常"
    if lights["outflow"]["on"]:
        act = f"{rule}；资金恐慌撤出历史上是好买点，有余钱可以再多加一些"
    elif dd[i] <= -.15:
        act = f"{rule}照做，不追加更多"
    else:
        act = rule
    verdict = f"{w_price}，{w_flow}，{w_trend}，{w_vol} → {act}"
    state = "资金撤出" if lights["outflow"]["on"] else ("过热" if dev > .25 else "便宜" if dd[i] <= -.15 else "正常")
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": days[i], "close": px[i], "dd": round(dd[i], 4), "dev250": round(dev, 4), "rule": rule, "rule_zone": G.get("zone"),
                   "lights": lights, "verdict": verdict, "action": act, "state": state,
                   "ref": {"real10": RY[i], "real10_chg3m": None if RY[i] is None or RY[i - 63] is None else round(RY[i] - RY[i - 63], 2),
                           "ratio_pct": None if ratp[i] is None else round(ratp[i], 3)}},
        "series": [[days[k], px[k], None if ma210[k] is None else round(ma210[k], 4), SP[k], None if vol[k] is None else round(vol[k], 4), RY[k]]
                   for k in range(n) if days[k] >= START],
        "stats": stats, "outflow_episodes": eps,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{days[i]} {verdict}")
    return data


if __name__ == "__main__":
    run()
