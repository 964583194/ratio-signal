"""托底资金（国家队）：头部沪深300 ETF 合计规模占沪深300 流通市值。只作观察，不进定投规则。

四只：华泰柏瑞 510300、易方达 510310、华夏 510330、嘉实 159919。
  规模 = 份额 × 单位净值（不能用累计净值：这几只做过份额折算，累计净值约只有实际每份价值的一半）
  占比 = 规模 ÷ 沪深300 流通市值。流通市值只有当天值（东方财富），之前的按沪深300 点位从最早一次真实值倒推，越早越不准。
  分位 = 占比在过去 252 个交易日的分位；方向 = 合计份额近 20 个交易日变化。
状态（先观察，阈值待检验）：
  大幅流入·托底：近 20 日份额 ≥ +15%      撤出中：近 20 日份额 ≤ −15%
  重仓持有：分位 ≥ 80%                     低仓观望：分位 ≤ 20%
  回补中：近 20 日份额 > +3%               减仓中：近 20 日份额 < −3%      其余：持平
长期历史另用基金季报（data/raw/etf300_quarterly.json，2013 年起，季度末净资产合计）。
"""
import bisect
import datetime as dt
import json
import os

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "etf300.json")
SH = ("510300", "510310", "510330")
START = "2015-01-01"
RECENT = "2023-01-01"     # 统计“2023 年起”的事件（汇金大规模用 ETF 托底以来）
IN_TH, OUT_TH, HI, LO, WIN = 0.15, -0.15, 0.80, 0.20, 252


def zone(pct, chg):
    if chg is not None and chg >= IN_TH:
        return "大幅流入·托底", "国家队在大举买入，有人托底；但往往还在下跌途中，不等于马上见底", "g1"
    if chg is not None and chg <= OUT_TH:
        return "撤出中", "托底资金在撤，历史上之后沪深300 偏弱；指数在高位时要留意偏热", "h1"
    if pct is not None and pct >= HI:
        return "重仓持有", "托底资金在场，下跌有人接；但不代表现在便宜", "c0"
    if pct is not None and pct <= LO:
        return "低仓观望", "托底资金基本撤空，下跌时没人接", "c0"
    if chg is not None and chg > 0.03:
        return "回补中", "托底资金正在回来", "c0"
    if chg is not None and chg < -0.03:
        return "减仓中", "托底资金在慢慢减", "c0"
    return "持平", "变化不大", "c0"


def ffill(src, days):
    ks = sorted(src)
    out = []
    for d in days:
        j = bisect.bisect_right(ks, d) - 1
        out.append(src[ks[j]] if j >= 0 else None)
    return out


def run():
    shares = {c: S.get_series(f"sh{c}")[0] for c in SH}
    shares["159919"] = S.get_series("sz159919")[0]
    navs = {c: S.get_series(f"unav{c}")[0] for c in (*SH, "159919")}
    hs, _ = S.get_series("hs300")
    try:
        cap, _ = S.get_series("cap300")
    except Exception:  # noqa: BLE001
        cap = {}
    days = sorted(d for d in shares["510300"] if d >= START and d in hs
                  and all(d in shares[c] for c in SH))
    if len(days) < WIN + 20:
        raise RuntimeError(f"托底资金：份额数据只有 {len(days)} 天")
    sz = ffill(shares["159919"], days)
    nv = {c: ffill(navs[c], days) for c in navs}
    close = [hs[d] for d in days]
    # 流通市值：有真实值用真实值；更早的从最早一次真实值按点位倒推
    ck = sorted(cap)
    if ck:
        a0 = ck[0]
        anchor_cap, anchor_close = cap[a0], hs[max(k for k in hs if k <= a0)]
    else:
        raise RuntimeError("托底资金：没有沪深300 流通市值")
    rows = []
    for i, d in enumerate(days):
        sh = [shares[c][d] for c in SH] + [sz[i]]
        if None in sh or any(nv[c][i] is None for c in nv):
            continue
        size = sum(shares[c][d] * nv[c][i] for c in SH) + sz[i] * nv["159919"][i]
        real = d in cap
        cp = cap[d] if real else anchor_cap * close[i] / anchor_close
        rows.append({"d": d, "size": size, "ratio": size / cp * 100, "sh": sum(sh), "close": close[i], "real": real})
    # 分位、20 日变化、状态
    for i, r in enumerate(rows):
        w = [x["ratio"] for x in rows[max(0, i - WIN + 1):i + 1]]
        r["pct"] = sum(v < r["ratio"] for v in w) / len(w) if i >= WIN - 1 else None
        r["chg"] = r["sh"] / rows[i - 20]["sh"] - 1 if i >= 20 else None
        r["zone"] = zone(r["pct"], r["chg"])[0]
    # 事件：进入“大幅流入”或“撤出中”的第一天（距上次同类事件 ≥ 20 个交易日），看之后沪深300
    events, lastk = [], {}
    for i, r in enumerate(rows):
        for k in ("大幅流入·托底", "撤出中"):
            if r["zone"] == k and (i == 0 or rows[i - 1]["zone"] != k) and i - lastk.get(k, -99) >= 20:
                lastk[k] = i
                fw = {str(h): round(rows[i + h]["close"] / r["close"] - 1, 4) if i + h < len(rows) else None for h in (20, 60, 120)}
                events.append({"date": r["d"], "kind": k, "close": r["close"], "pct": r["pct"], "chg": round(r["chg"], 4), "fwd": fw})
    def mkstats(since):
        out = {}
        for k in ("大幅流入·托底", "撤出中", "全部交易日"):
            ev = [e for e in events if e["kind"] == k and e["date"] >= since] if k != "全部交易日" else \
                [{"fwd": {str(h): rows[i + h]["close"] / rows[i]["close"] - 1 if i + h < len(rows) else None for h in (20, 60, 120)}}
                 for i in range(len(rows)) if rows[i]["d"] >= since]
            st = {"n": len(ev)}
            for h in ("20", "60", "120"):
                xs = [e["fwd"][h] for e in ev if e["fwd"][h] is not None]
                st[h] = {"avg": round(sum(xs) / len(xs), 4), "up": round(sum(x > 0 for x in xs) / len(xs), 3), "n": len(xs)} if xs else None
            out[k] = st
        return out
    # 汇金 2023 年起才大规模用这几只 ETF 托底；之前占比只有 0.2%~0.3%，±15% 的“事件”多半是普通资金进出
    stats, stats_all = mkstats(RECENT), mkstats(START)
    L = rows[-1]
    zn, act, cls = zone(L["pct"], L["chg"])
    try:   # 季报：[季末日期, 四只期末净资产合计（亿元）, 合计份额（亿份）]
        with open(os.path.join(ROOT, "data", "raw", "etf300_quarterly.json"), encoding="utf-8") as fh:
            qraw = json.load(fh)
    except Exception:  # noqa: BLE001
        qraw = []
    hk = sorted(hs)
    quarterly = []
    for qd, qsize, _qsh in qraw:
        j = bisect.bisect_right(hk, qd) - 1
        if j < 0:
            continue
        c = hs[hk[j]]
        quarterly.append([qd, round(qsize * 1e8 / (anchor_cap * c / anchor_close) * 100, 3), round(qsize), c])
    first_real = next((r["d"] for r in rows if r["real"]), None)
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": L["d"], "size": round(L["size"] / 1e8), "ratio": round(L["ratio"], 3), "pct": None if L["pct"] is None else round(L["pct"], 3),
                   "chg20": None if L["chg"] is None else round(L["chg"], 4), "shares": round(L["sh"] / 1e8, 1), "close": L["close"],
                   "zone": zn, "action": act, "cls": cls, "real_cap": L["real"],
                   "hi": round(max(r["ratio"] for r in rows), 3), "lo": round(min(r["ratio"] for r in rows), 3)},
        "first_real_cap": first_real,
        "series": [[r["d"], round(r["ratio"], 4), None if r["pct"] is None else round(r["pct"] * 100, 1),
                    round(r["sh"] / 1e8, 1), r["close"]] for r in rows],
        "events": events, "stats": stats, "stats_all": stats_all, "recent_from": RECENT, "quarterly": quarterly,
        "rule": {"in": IN_TH, "out": OUT_TH, "hi": HI, "lo": LO, "win": WIN},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    pct_txt = "—" if L["pct"] is None else f"{L['pct']:.0%}"
    print(f"写入 {OUT}：{L['d']} 规模 {L['size'] / 1e8:.0f} 亿，占比 {L['ratio']:.2f}%，252 日分位 "
          f"{pct_txt}，20 日份额 {L['chg']:+.1%}，{zn}；事件 {len(events)} 次")
    return data


if __name__ == "__main__":
    run()
