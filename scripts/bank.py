"""
银行（实验，放在“债基 · 银行”页签）：中证银行 399986 的“便宜还是贵”，写入 data/bank.json。

- 股息率：近 12 个月 全收益涨幅 ÷ 价格涨幅 − 1（和红利打分同一算法）
- 利差 = 股息率 − 十年国债（百分点），看近 10 年分位，越高越便宜
- 市盈率分位（近 10 年），越低越便宜
- 银行便宜指数 = (利差分位 + (1 − 市盈率分位)) / 2 × 100，0~100，越高越便宜
- 只作提醒，不占组合比例；回测几种分档，看择时有没有用

所有分位都只用当天及之前的数据（没有未来函数）。
"""
import bisect
import datetime as dt

import sources as S
from value import backtest, dump, forward, ma, now_str

WIN = 2500      # 近 10 年（交易日）
MIN = 750       # 至少 3 年才算分位

# 分档：(下限, 回测用的倍数, 状态, 操作)
# 2026-11-16 回测：按档调金额都不如普通定投，所以操作一律“照常”，档位只说位置
ZONES = [(80, 2.0, "很便宜", "位置偏低，照常定投"), (60, 1.5, "偏便宜", "照常定投"),
         (20, 1.0, "正常", "照常定投"), (-1, 0.5, "偏贵", "位置偏高，照常定投")]


def zone(c):
    for lo, m, z, a in ZONES:
        if c >= lo:
            return m, z, a
    return ZONES[-1][1:]


def rolling_pct(vals, win=WIN, mn=MIN):
    """严格小于当天值的占比（窗口含当天）。None 跳过。"""
    out, win_l, buf = [], [], []
    for v in vals:
        if v is None:
            out.append(None)
            continue
        buf.append(v)
        bisect.insort(win_l, v)
        if len(buf) > win:
            old = buf.pop(0)
            win_l.pop(bisect.bisect_left(win_l, old))
        n = len(win_l)
        out.append(bisect.bisect_left(win_l, v) / n if n >= mn else None)
    return out


def ffill(table, dates):
    ks = sorted(table)
    out = []
    for d in dates:
        j = bisect.bisect_right(ks, d) - 1
        out.append(table[ks[j]] if j >= 0 else None)
    return out


def run():
    px_raw, src_px = S.get_series("bank", 2500)
    pe_raw, src_pe = S.get_series("bank_pe", 2000)
    tr_raw, src_tr = S.get_series("bank_tr", 2000)
    y10_raw, _ = S.get_series("cn10y", 2500)
    print(f"银行：价格 {len(px_raw)} 天（{src_px}），市盈率 {len(pe_raw)} 天（{src_pe}），全收益 {len(tr_raw)} 天（{src_tr}）")

    # 全收益偶尔晚几天：缺的几天按价格涨跌补上
    tl = max(tr_raw)
    tr_raw = dict(tr_raw)
    for d in sorted(x for x in px_raw if x > tl)[:10]:
        tr_raw[d] = tr_raw[tl] * px_raw[d] / px_raw[tl]

    dates = sorted(set(px_raw) & set(tr_raw))
    px = [px_raw[d] for d in dates]
    tri = [tr_raw[d] for d in dates]
    pe = ffill(pe_raw, dates)
    y10 = ffill(y10_raw, dates)
    D = [dt.date.fromisoformat(d) for d in dates]

    dy, j = [], 0
    for i, d in enumerate(D):
        while D[j] < d - dt.timedelta(days=365):
            j += 1
        dy.append(None if (d - D[j]).days < 350 else (tri[i] / tri[j]) / (px[i] / px[j]) - 1)
    sp = [None if a is None or b is None else a * 100 - b for a, b in zip(dy, y10)]
    sp_pct = rolling_pct(sp)
    pe_pct = rolling_pct([v if v and v > 0 else None for v in pe])
    cheap = [None if a is None or b is None else (a + 1 - b) / 2 * 100 for a, b in zip(sp_pct, pe_pct)]
    m250 = ma(px, 250)

    i0 = next(k for k, c in enumerate(cheap) if c is not None)
    Dd, P = D[i0:], tri[i0:]

    def bt(mfun):
        return backtest(Dd, P, 0.0, [mfun(k) for k in range(i0, len(dates))])

    def zm(vals, hi, lo, mh=2.0, ml=0.5):
        return lambda k: 1.0 if vals[k] is None else mh if vals[k] >= hi else ml if vals[k] < lo else 1.0

    variants = [
        ("普通定投", "", None),
        ("便宜指数四档", "≥80 2 倍，60~80 1.5 倍，<20 0.5 倍", lambda k: zone(cheap[k])[0]),
        ("便宜指数两头", "≥80 2 倍，<20 0.5 倍", zm(cheap, 80, 20)),
        ("只看利差", "分位 ≥80% 2 倍，<20% 0.5 倍", zm([None if v is None else v * 100 for v in sp_pct], 80, 20)),
        ("只看市盈率", "便宜程度 ≥80 2 倍，<20 0.5 倍", zm([None if v is None else (1 - v) * 100 for v in pe_pct], 80, 20)),
        ("偏贵时停买", "≥80 2 倍，<20 不买", zm(cheap, 80, 20, 2.0, 0.0)),
    ]
    bts = []
    for name, desc, f in variants:
        r = backtest(Dd, P, 0.0) if f is None else bt(f)
        r["name"] = name
        r["desc"] = desc
        bts.append(r)
    # 分档线敏感性：上沿 × 下沿
    grid = []
    for hi in (70, 75, 80, 85, 90):
        for lo in (10, 20, 30):
            r = bt(zm(cheap, hi, lo))
            grid.append({"hi": hi, "lo": lo, "xirr": r["xirr"], "mdd": r["mdd"]})

    fwd = forward(P, [("便宜指数 ≥80", lambda i: cheap[i0 + i] >= 80), ("60~80", lambda i: 60 <= cheap[i0 + i] < 80),
                      ("20~60", lambda i: 20 <= cheap[i0 + i] < 60), ("<20", lambda i: cheap[i0 + i] < 20),
                      ("全部交易日", lambda i: True)])

    # 和债基的关系：周收益相关（债基用十年国债近似：票息 + 7 年久期 × 收益率变化）
    wk, last = [], None
    for k in range(i0, len(dates)):
        w = D[k].isocalendar()[:2]
        if w != last:
            wk.append(k)
            last = w
    rb, rd = [], []
    for a, b in zip(wk, wk[1:]):
        if y10[a] is None or y10[b] is None:
            continue
        rb.append(tri[b] / tri[a] - 1)
        rd.append(y10[a] / 100 * (D[b] - D[a]).days / 365 - 7.0 * (y10[b] - y10[a]) / 100)
    corr = None
    if len(rb) > 50:
        mb, md = sum(rb) / len(rb), sum(rd) / len(rd)
        cov = sum((x - mb) * (y - md) for x, y in zip(rb, rd))
        vb = sum((x - mb) ** 2 for x in rb) ** .5
        vd = sum((y - md) ** 2 for y in rd) ** .5
        corr = round(cov / (vb * vd), 3) if vb and vd else None

    i = len(dates) - 1
    m, zn, act = zone(cheap[i])
    data = {
        "updated": now_str(), "name": "中证银行", "kind": "bank", "experimental": True,
        "sources": {"price": src_px, "pe": src_pe, "tr": src_tr},
        "latest": {"date": dates[i], "close": round(px[i], 2), "prev_close": round(px[i - 1], 2),
                   "ma250": round(m250[i], 2) if m250[i] else None,
                   "dev": round(px[i] / m250[i] - 1, 4) if m250[i] else None,
                   "pe": round(pe[i], 2) if pe[i] else None, "pe_pct": round(pe_pct[i], 3) if pe_pct[i] is not None else None,
                   "dy": round(dy[i], 4), "y10": y10[i], "spread": round(sp[i], 2), "sp_pct": round(sp_pct[i], 3),
                   "cheap": round(cheap[i], 1), "zone": zn, "mult": m, "action": act},
        "zones": [[lo, mm, z, a] for lo, mm, z, a in ZONES],
        "backtest": bts, "grid": grid, "bt_start": dates[i0], "forward": fwd, "corr_bond": corr,
        "series": [[dates[k], round(cheap[k], 1)] for k in range(i0, len(dates))],
        "px_series": [[dates[k], round(px[k], 2)] for k in range(i0, len(dates))],
        "ma_series": [[dates[k], round(m250[k], 2)] for k in range(i0, len(dates)) if m250[k]],
        "sp_series": [[dates[k], round(sp[k], 2)] for k in range(i0, len(dates)) if sp[k] is not None],
    }
    dump("bank.json", data)
    for r in bts:
        print(f"  回测 {r['name']}：年化 {r['xirr']}，回撤 {r['mdd']}，未投现金 {r['pool']}")
    print(f"  分档线敏感性：{grid}")
    print(f"  未来一年：{fwd}")
    print(f"  银行与债基周收益相关：{corr}")


if __name__ == "__main__":
    run()
