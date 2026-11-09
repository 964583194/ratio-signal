"""
中证A500 与 纳指100 的“便宜还是贵”指标与回测，写入 data/a500.json、data/ndx.json。

中证A500：
  价格用中证A500（000510），估值用沪深300 的市盈率（A500 自己的市盈率 2024 年才开始发布，历史太短；
  两者成分和走势高度重合）。
  - 市盈率分位：比现在便宜的天数占比，越低越便宜
  - 股债利差：1/PE − 十年国债，越高越便宜
  - 便宜指数 = (100 − 市盈率分位 + 股债利差分位) / 2，0~100，越高越便宜
  - 年线：MA250，连续 2 天收在下方算有效跌破
纳指100（拿不到免费的历史市盈率，所以不用估值）：
  - 离历史最高点的回撤
  - 年线 MA250 与有效跌破
  - 国内纳指ETF（513100）溢价率

所有分位都只用当天及之前的数据（没有未来函数）。
"""
import bisect
import datetime as dt
import json
import os

import sources as S
from dividend import expanding_share, xirr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEKLY = 1000
FEE = 0.0005
CASH = 0.015


def now_str():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def on_or_before(table, keys, d):
    k = bisect.bisect_right(keys, d) - 1
    return table[keys[k]] if k >= 0 else None


def ma(vals, n):
    out, s = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def below_flags(close, m):
    """有效跌破：连续 2 天收在年线下方；有效站回：连续 2 天收在年线上方"""
    out, state = [], False
    for i in range(len(close)):
        if m[i] is None or i == 0 or m[i - 1] is None:
            out.append(False)
            continue
        b0, b1 = close[i - 1] < m[i - 1], close[i] < m[i]
        if b0 and b1:
            state = True
        elif not b0 and not b1:
            state = False
        out.append(state)
    return out


def ma_events(dates, flags):
    ev, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        if not f and start is not None:
            ev.append([dates[start], dates[i - 1], i - start])
            start = None
    if start is not None:
        ev.append([dates[start], None, len(flags) - start])
    return ev


def backtest(dates, px, div, mult=None, exit_flags=None):
    """每周首个交易日拿出 WEEKLY 元进现金池；买入 min(池子, WEEKLY×倍数)。
    mult=None 为普通定投；exit_flags 为 True 时清仓持有现金、不买入（年线择时）。"""
    hold = pool = 0.0
    nav = peak = 1.0
    mdd, prev = 0.0, 0.0
    cfs, last_wk, inv = [], None, 0
    for i, d in enumerate(dates):
        if i:
            hold *= px[i] / px[i - 1] * (1 + div / 252)
            pool *= 1 + CASH / 252
        cur = hold + pool
        if prev > 0:
            nav *= cur / prev
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
        if exit_flags is not None and exit_flags[i] and hold > 0:
            pool += hold * (1 - FEE)
            hold = 0.0
        wk = d.isocalendar()[:2]
        if wk != last_wk:
            last_wk = wk
            pool += WEEKLY
            inv += WEEKLY
            cfs.append((d, -WEEKLY))
            if exit_flags is not None:
                if not exit_flags[i]:
                    hold += pool * (1 - FEE)
                    pool = 0.0
            else:
                m = 1 if mult is None else mult[i]
                amt = pool if mult is None else min(pool, WEEKLY * m)
                hold += amt * (1 - FEE)
                pool -= amt
        prev = hold + pool
    final = hold + pool
    cfs.append((dates[-1], final))
    x = xirr(cfs)
    return {"xirr": round(x, 4) if x is not None else None, "mdd": round(mdd, 4),
            "invested": inv, "final": round(final), "pool": round(pool)}


def backtest2(dates, px, div, mult, tp=True):
    """现行规则：每周 1000 元进“红利池”（红利低波100 全收益），按倍数从池子里买；
    tp=True 时加目标止盈：偏贵区间（倍数 <1）持仓盈利 ≥50% 卖 1/3、≥100% 再卖一半，卖出的钱回红利池。"""
    tr, _ = S.get_series("hl100_tr")
    tk = sorted(tr)
    H = [on_or_before(tr, tk, d.isoformat()) for d in dates]
    hold = pool = cost = 0.0
    nav = peak = 1.0
    mdd, prev, nsell = 0.0, 0.0, 0
    cfs, last_wk, hit = [], None, set()
    for i, d in enumerate(dates):
        if i:
            hold *= px[i] / px[i - 1] * (1 + div / 252)
            pool *= H[i] / H[i - 1]
        cur = hold + pool
        if prev > 0:
            nav *= cur / prev
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
        wk = d.isocalendar()[:2]
        if wk != last_wk:
            last_wk = wk
            pool += WEEKLY
            cfs.append((d, -WEEKLY))
            m = mult[i]
            amt = min(pool, WEEKLY * m)
            hold += amt * (1 - FEE)
            pool -= amt
            cost += amt
            if tp and cost > 0:
                if m >= 1:
                    hit.clear()
                g = hold / cost - 1
                for th, f in ((0.5, 1 / 3), (1.0, 0.5)):
                    if m < 1 and g >= th and th not in hit:
                        s = hold * f
                        hold -= s
                        cost *= 1 - f
                        pool += s * (1 - 2 * FEE)
                        hit.add(th)
                        nsell += 1
        prev = hold + pool
    final = hold + pool
    cfs.append((dates[-1], final))
    x = xirr(cfs)
    return {"xirr": round(x, 4) if x is not None else None, "mdd": round(mdd, 4),
            "invested": WEEKLY * (len(cfs) - 1), "final": round(final), "pool": round(pool), "sells": nsell}


def forward(px, idx_groups, h=250):
    out = []
    for name, cond in idx_groups:
        xs = [px[i + h] / px[i] - 1 for i in range(len(px) - h) if cond(i)]
        out.append({"zone": name, "n": len(xs),
                    "avg": round(sum(xs) / len(xs), 4) if xs else None,
                    "win": round(sum(x > 0 for x in xs) / len(xs), 3) if xs else None,
                    "worst": round(min(xs), 4) if xs else None})
    return out


def dump(name, data):
    path = os.path.join(ROOT, "data", name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {path}：{data['latest']['date']}")


# ================================================================ 中证A500
A_ZONES = [(80, 3.0, "很便宜", "3 倍定投"), (60, 2.0, "偏便宜", "2 倍定投"), (40, 1.0, "正常", "正常定投"),
           (20, 0.6, "偏贵", "0.6 倍定投"), (-1, 0.3, "很贵", "0.3 倍定投，其余进现金池")]


def a_zone(c):
    for th, m, n, a in A_ZONES:
        if c >= th:
            return m, n, a


def run_a500(price_key="a500", name="中证A500", kind="a500", out="a500.json"):
    px_raw, _ = S.get_series(price_key)
    pe_raw, _ = S.get_series("pe300", 2500)
    try:
        pe_a, _ = S.get_series("pe_a500", 100)
    except Exception:  # noqa: BLE001
        pe_a = {}
    cgb, _ = S.get_series("cn10y", 2500)
    print(f"A500 价格 {len(px_raw)} 天，沪深300 PE {len(pe_raw)} 天，A500 PE {len(pe_a)} 天，国债 {len(cgb)} 天")

    dates = sorted(d for d in px_raw if d >= min(pe_raw))
    pk, ck = sorted(pe_raw), sorted(cgb)
    px = [px_raw[d] for d in dates]
    pe = [on_or_before(pe_raw, pk, d) for d in dates]
    y10 = [on_or_before(cgb, ck, d) for d in dates]
    erp = [None if (p is None or y is None) else 100 / p - y for p, y in zip(pe, y10)]
    import dividend as Dv
    old_w, Dv.WARMUP = Dv.WARMUP, 750       # 至少 3 年历史才算分位
    pe_pct = expanding_share(pe, "lt")      # 比现在便宜的天数占比
    erp_pct = expanding_share(erp, "lt")    # 利差低于现在的天数占比（越高越便宜）
    Dv.WARMUP = old_w
    m250 = ma(px, 250)
    below = below_flags(px, m250)
    cheap = [None if (a is None or b is None) else 50 * (1 - a) + 50 * b for a, b in zip(pe_pct, erp_pct)]

    i0 = next(i for i, c in enumerate(cheap) if c is not None and m250[i] is not None)
    D = [dt.date.fromisoformat(d) for d in dates[i0:]]
    P, C = px[i0:], cheap[i0:]
    mult = [a_zone(c)[0] for c in C]
    DIV = 0.025
    bt = {"plain": backtest(D, P, DIV), "value": backtest(D, P, DIV, mult)}
    # 年线：跌破时暂停加码（倍数封顶 1）
    mult_ma = [min(m, 1.0) if b else m for m, b in zip(mult, below[i0:])]
    bt["value_ma"] = backtest(D, P, DIV, mult_ma)
    bt["timing"] = backtest(D, P, DIV, exit_flags=below[i0:])
    bt["value_tp"] = backtest2(D, P, DIV, mult)
    fwd = forward(P, [(f"{n}（便宜指数 {'≥'+str(th) if th>=0 else '<20'}）", (lambda i, th=th, nx=nx: C[i] >= th and C[i] < nx))
                      for (th, _, n, _), nx in zip(A_ZONES, [101, 80, 60, 40, 20])])
    fwd += forward(P, [("年线上方", lambda i: not below[i0 + i]), ("有效跌破年线", lambda i: below[i0 + i]),
                       ("全部交易日", lambda i: True)])

    i = len(dates) - 1
    m, zn, act = a_zone(cheap[i])
    last_pe_a = pe_a[max(pe_a)] if pe_a else None
    data = {
        "updated": now_str(), "name": name, "kind": kind,
        "latest": {"date": dates[i], "close": px[i], "pe300": pe[i], "pe_a500": last_pe_a,
                   "y10": y10[i], "erp": round(erp[i], 2), "pe_pct": round(pe_pct[i], 3),
                   "erp_pct": round(erp_pct[i], 3), "cheap": round(cheap[i], 1), "zone": zn,
                   "mult": m, "action": act, "ma250": round(m250[i], 2),
                   "dev": round(px[i] / m250[i] - 1, 4), "below": below[i],
                   "prev_close": px[i - 1]},
        "zones": [[th, mm, n, a] for th, mm, n, a in A_ZONES],
        "backtest": bt, "bt_start": dates[i0], "div": DIV,
        "forward": fwd,
        "ma_events": ma_events(dates, below)[-8:],
        "series": [[d, round(c, 1)] for d, c in zip(dates[i0:], C)],
        "dev_series": [[dates[k], round(px[k] / m250[k] - 1, 4)] for k in range(len(dates)) if m250[k]],
        "erp_series": [[dates[k], round(erp[k], 2)] for k in range(len(dates)) if erp[k] is not None],
    }
    dump(out, data)


# ================================================================ 纳指100
# 回测里的预算中性加码方案：平时 0.8 倍省下钱，回撤时加码。实测跑不赢普通定投，页面上作为对照
N_ZONES = [(0.30, 3.0, "深度回撤", "照常定投"), (0.20, 2.0, "大幅回撤", "照常定投"),
           (0.10, 1.5, "回调", "照常定投"), (-1, 0.8, "接近高点", "照常定投")]   # 回撤档位只作参考，不改金额


def n_zone(dd):
    for th, m, n, a in N_ZONES:
        if dd >= th:
            return m, n, a


def run_ndx():
    raw, _ = S.get_series("ndx", 2500)
    try:
        ust, _ = S.get_series("us10y", 400)
    except Exception:  # noqa: BLE001
        ust = {}
    dates = sorted(raw)
    px = [raw[d] for d in dates]
    print(f"纳指100 {len(dates)} 天（{dates[0]} 起），美债 {len(ust)} 天")

    peak, dd = 0.0, []
    for v in px:
        peak = max(peak, v)
        dd.append(1 - v / peak)
    m250 = ma(px, 250)
    below = below_flags(px, m250)

    i0 = 250
    D = [dt.date.fromisoformat(d) for d in dates[i0:]]
    P, DD, B = px[i0:], dd[i0:], below[i0:]
    mult = [n_zone(x)[0] for x in DD]
    DIV = 0.007
    bt = {"plain": backtest(D, P, DIV), "value": backtest(D, P, DIV, mult),
          "value_ma": backtest(D, P, DIV, [1.0 if b else m for m, b in zip(mult, B)]),
          "timing": backtest(D, P, DIV, exit_flags=B)}
    fwd = forward(P, [(f"{n}（回撤 {'≥'+format(th,'.0%') if th>=0 else '<10%'}）",
                       (lambda i, th=th, nx=nx: DD[i] >= th and DD[i] < nx))
                      for (th, _, n, _), nx in zip(N_ZONES, [9, 0.30, 0.20, 0.10])])
    fwd += forward(P, [("年线上方", lambda i: not B[i]), ("有效跌破年线", lambda i: B[i]),
                       ("跌破年线且回撤≥20%", lambda i: B[i] and DD[i] >= .2), ("全部交易日", lambda i: True)])

    # 513100 溢价率：同一天收盘价 ÷ 净值 − 1
    prem = None
    try:
        nav, _ = S.get_series("nav513100", 100)
        etf, _ = S.get_series("etf513100", 100)
        both = sorted(set(nav) & set(etf))
        prem = {"date": both[-1], "price": etf[both[-1]], "nav": nav[both[-1]],
                "value": round(etf[both[-1]] / nav[both[-1]] - 1, 4),
                "series": [[d, round(etf[d] / nav[d] - 1, 4)] for d in both[-120:]]}
    except Exception as e:  # noqa: BLE001
        print(f"溢价率获取失败：{e}")

    i = len(dates) - 1
    m, zn, act = n_zone(dd[i])
    uk = sorted(ust)
    hi_i = max(range(len(px)), key=lambda k: px[k])
    data = {
        "updated": now_str(), "name": "纳指100", "kind": "ndx",
        "latest": {"date": dates[i], "close": px[i], "prev_close": px[i - 1], "high": px[hi_i],
                   "high_date": dates[hi_i], "dd": round(dd[i], 4), "zone": zn, "mult": m,
                   "action": act, "ma250": round(m250[i], 2), "dev": round(px[i] / m250[i] - 1, 4),
                   "below": below[i], "ust10": on_or_before(ust, uk, dates[i]) if uk else None},
        "premium": prem,
        "zones": [[th, mm, n, a] for th, mm, n, a in N_ZONES],
        "backtest": bt, "bt_start": dates[i0], "div": DIV,
        "forward": fwd,
        "ma_events": ma_events(dates, below)[-10:],
        "series": [[d, round(-x * 100, 2)] for d, x in zip(dates[i0:], DD)],
        "dev_series": [[dates[k], round(px[k] / m250[k] - 1, 4)] for k in range(len(dates)) if m250[k]],
    }
    dump("ndx.json", data)


G_ZONES = [(0.15, 2.0, "回撤 ≥15%", "2 倍定投"), (-1, 1.0, "正常", "正常定投")]
G_HOT = 0.25    # 比年线高 25% 以上暂停买入


def g_mult(dd, dev):
    if dev is not None and dev > G_HOT:
        return 0.0, "过热", "暂停买入，定投款买红利低波100"
    for th, m, n, a in G_ZONES:
        if dd >= th:
            return m, n, a


def run_gold():
    raw, _ = S.get_series("gold", 2000)
    dates = sorted(raw)
    px = [raw[d] for d in dates]
    print(f"黄金ETF {len(dates)} 天（{dates[0]} 起）")
    peak, dd = 0.0, []
    for v in px:
        peak = max(peak, v)
        dd.append(1 - v / peak)
    m250 = ma(px, 250)
    below = below_flags(px, m250)
    dev = [px[k] / m250[k] - 1 if m250[k] else None for k in range(len(px))]
    i0 = 250
    D = [dt.date.fromisoformat(d) for d in dates[i0:]]
    P, DD, B = px[i0:], dd[i0:], below[i0:]
    mult = [g_mult(a, b)[0] for a, b in zip(DD, dev[i0:])]
    bt = {"plain": backtest(D, P, 0.0), "value": backtest2(D, P, 0.0, mult, tp=False)}
    fwd = forward(P, [("比年线高 25% 以上（过热）", lambda i: dev[i0 + i] > G_HOT),
                      ("回撤 ≥15%", lambda i: DD[i] >= .15), ("回撤 5%~15%", lambda i: .05 <= DD[i] < .15),
                      ("接近高点（回撤 <5%）", lambda i: DD[i] < .05),
                      ("有效跌破年线", lambda i: B[i]), ("全部交易日", lambda i: True)])
    i = len(dates) - 1
    m, zn, act = g_mult(dd[i], dev[i])
    hi_i = max(range(len(px)), key=lambda k: px[k])
    data = {
        "updated": now_str(), "name": "黄金", "kind": "gold",
        "latest": {"date": dates[i], "close": px[i], "prev_close": px[i - 1], "high": px[hi_i],
                   "high_date": dates[hi_i], "dd": round(dd[i], 4), "zone": zn, "mult": m, "action": act,
                   "ma250": round(m250[i], 3), "dev": round(dev[i], 4), "below": below[i], "hot": G_HOT},
        "backtest": bt, "bt_start": dates[i0], "div": 0,
        "forward": fwd,
        "ma_events": ma_events(dates, below)[-10:],
        "series": [[d, round(-x * 100, 2)] for d, x in zip(dates[i0:], DD)],
        "dev_series": [[dates[k], round(dev[k], 4)] for k in range(len(dates)) if dev[k] is not None],
    }
    dump("gold.json", data)


def run():
    for f in (run_a500, lambda: run_a500("hs300", "沪深300", "hs300", "hs300.json"), run_ndx, run_gold):
        try:
            f()
        except Exception as e:  # noqa: BLE001
            print(f"{getattr(f, '__name__', '沪深300')} 失败，保留旧数据：{e}")


if __name__ == "__main__":
    run()
