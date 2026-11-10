"""海外小仓位：4 只 QDII 基金 + 纳指100 摘要。只作提醒，不进定投组合。

用累计净值（分红加回）算：
  - 从最高点回撤：≥10% 回调，≥20% 大幅回撤（有余钱可以多加），≥30% 深度回撤
  - 偏离年线（250 日均线）：高出 25% 以上算过热，暂停加钱（和黄金页同一条规则）
  - 近一年收益；两只科技基金的相关性；亚太精选场内 ETF（159687）溢价率
回测：每周 1000 元，普通定投 vs 按上面规则（过热暂停、大幅回撤买 2 倍；没买的钱放现金 1.5%）。
"""
import datetime as dt
import json
import math
import os

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "overseas.json")
FUNDS = [
    ("006555", "浦银全球智能科技", "主动管理 · 美股科技为主（美国约 71%），重仓芯片和科技巨头"),
    ("539002", "建信新兴市场混合", "主动管理 · 名为新兴市场，实际美国约 55%、韩国约 18%，重仓芯片和存储"),
    ("007280", "摩根日本精选", "主动管理 · 全部买日本，行业较分散（电子、银行、消费）"),
    ("021189", "南方亚太精选ETF联接", "指数基金 · 富时亚太低碳精选指数（日本、韩国、中国台湾、印度等）"),
]
HOT, WEEKLY, FEE, CASH = 0.25, 1000, 0.0005, 0.015


def zone(dd, dev):
    if dev is not None and dev > HOT:
        return "过热", "暂停加钱，已有的不动", "r1"
    if dd >= 0.30:
        return "深度回撤", "有余钱可以多加", "g2"
    if dd >= 0.20:
        return "大幅回撤", "有余钱可以多加", "g1"
    if dd >= 0.10:
        return "回调", "照常持有", "c0"
    return "正常", "照常持有", "c0"


def xirr(cfs):
    d0 = cfs[0][0]
    f = lambda r: sum(a / (1 + r) ** ((d - d0).days / 365) for d, a in cfs)  # noqa: E731
    lo, hi = -0.9, 3.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(100):
        m = (lo + hi) / 2
        if f(lo) * f(m) <= 0:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def backtest(D, P, mult):
    """每周第一个交易日存 1000；按倍数从现金池买，钱不够就买池子里有的"""
    hold = pool = 0.0
    nav = peak = 1.0
    mdd, prev, wk, cfs = 0.0, 0.0, None, []
    for i, d in enumerate(D):
        if i:
            hold *= P[i] / P[i - 1]
            pool *= 1 + CASH * (d - D[i - 1]).days / 365
        cur = hold + pool
        if prev > 0:
            nav *= cur / prev
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
        if d.isocalendar()[:2] != wk:
            wk = d.isocalendar()[:2]
            pool += WEEKLY
            cfs.append((d, -WEEKLY))
            amt = min(pool, WEEKLY * (mult[i] if mult else 1))
            hold += amt * (1 - FEE)
            pool -= amt
        prev = hold + pool
    cfs.append((D[-1], hold + pool))
    x = xirr(cfs)
    return {"xirr": round(x, 4) if x is not None else None, "mdd": round(mdd, 4),
            "invested": WEEKLY * (len(cfs) - 1), "final": round(hold + pool), "cash": round(pool)}


def one(code, name, desc):
    raw, src = S.get_series(f"nav{code}", 200)
    dates = sorted(raw)
    D = [dt.date.fromisoformat(d) for d in dates]
    P = [raw[d] for d in dates]
    ma = [None] * len(P)
    s = 0.0
    for i, v in enumerate(P):
        s += v
        if i >= 250:
            s -= P[i - 250]
        if i >= 249:
            ma[i] = s / 250
    peak, dd = 0.0, []
    for v in P:
        peak = max(peak, v)
        dd.append(1 - v / peak)
    dev = [P[i] / ma[i] - 1 if ma[i] else None for i in range(len(P))]
    i = len(P) - 1
    zn, act, cls = zone(dd[i], dev[i])
    j1 = next((k for k in range(i, -1, -1) if (D[i] - D[k]).days >= 365), None)
    hist_mdd = max(dd)
    # 回测：前一交易日信号，当天净值成交；年线有了以后才开始
    i0 = next((k for k in range(len(P)) if ma[k]), None)
    bt = None
    if i0 is not None and len(P) - i0 > 250:
        mult = [1.0] * len(P)
        for k in range(i0 + 1, len(P)):
            mult[k] = 0.0 if dev[k - 1] > HOT else 2.0 if dd[k - 1] >= 0.20 else 1.0
        bt = {"start": dates[i0], "plain": backtest(D[i0:], P[i0:], None), "rule": backtest(D[i0:], P[i0:], mult[i0:])}
    print(f"海外 {name}：{len(P)} 天（{dates[0]} 起，{src}），回撤 {dd[i]:.1%}，偏离年线 "
          f"{dev[i] if dev[i] is None else round(dev[i] * 100, 1)}%，{zn}")
    return {
        "code": code, "name": name, "desc": desc, "source": src,
        "latest": {"date": dates[i], "nav": P[i], "dd": round(dd[i], 4), "dev": None if dev[i] is None else round(dev[i], 4),
                   "ma": None if ma[i] is None else round(ma[i], 4), "high": max(P), "hist_mdd": round(hist_mdd, 4),
                   "ret1y": round(P[i] / P[j1] - 1, 4) if j1 is not None else None,
                   "zone": zn, "action": act, "cls": cls},
        "series": [[dates[k], round(-dd[k] * 100, 2)] for k in range(len(P))],
        "nav_series": [[dates[k], round(P[k], 4)] for k in range(len(P))],
        "dev_series": [[dates[k], round(dev[k] * 100, 2)] for k in range(len(P)) if dev[k] is not None],
        "bt": bt,
        "_weekly": {dates[k]: P[k] for k in range(len(P))},
    }


def corr_1y(a, b):
    """两只基金近一年周收益相关性"""
    common = sorted(set(a) & set(b))
    if len(common) < 60:
        return None
    end = dt.date.fromisoformat(common[-1])
    common = [d for d in common if (end - dt.date.fromisoformat(d)).days <= 365][::5]
    ra = [a[common[k]] / a[common[k - 1]] - 1 for k in range(1, len(common))]
    rb = [b[common[k]] / b[common[k - 1]] - 1 for k in range(1, len(common))]
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return round(num / den, 3) if den else None


def premium():
    try:
        px, _ = S.get_series("etf159687", 100)
        nv, _ = S.get_series("nav159687", 100)
    except Exception as e:  # noqa: BLE001
        print(f"159687 溢价率读取失败：{e}")
        return None
    common = sorted(set(px) & set(nv))
    if not common:
        return None
    d = common[-1]
    return {"date": d, "close": px[d], "nav": nv[d], "value": round(px[d] / nv[d] - 1, 4)}


def run():
    funds = []
    for code, name, desc in FUNDS:
        try:
            funds.append(one(code, name, desc))
        except Exception as e:  # noqa: BLE001  某一只失败不影响其他
            print(f"海外 {name} 计算失败：{e}")
    if not funds:
        raise RuntimeError("海外小仓位：4 只基金都没有数据")
    by = {f["code"]: f for f in funds}
    corr = corr_1y(by["006555"]["_weekly"], by["539002"]["_weekly"]) if "006555" in by and "539002" in by else None
    for f in funds:
        f.pop("_weekly")
    ndx = None
    try:
        with open(os.path.join(ROOT, "data", "ndx.json"), encoding="utf-8") as fh:
            L = json.load(fh)["latest"]
        ndx = {"date": L["date"], "dd": L["dd"], "zone": L["zone"], "action": L["action"], "below": L.get("below")}
    except Exception:  # noqa: BLE001
        pass
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    data = {"updated": now, "latest": {"date": max(f["latest"]["date"] for f in funds)},
            "funds": funds, "corr_tech": corr, "premium": premium(), "ndx": ndx}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{len(funds)} 只基金，科技基金相关性 {corr}")


if __name__ == "__main__":
    run()
