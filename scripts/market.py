"""
见底评分与市场参考指标（只作参考，不直接决定买卖；破净率另外用于轮动的“见底才大举加仓”）。

见底评分 0~100，越高越接近底部，五项各自换算成历史百分位后取平均：
  破净率高（10 年）、股债利差高（10 年）、融资余额占流通市值低（3 年）、
  两市成交额 20 日均值低（3 年，地量）、创业板指市盈率低（10 年）。
"""
import bisect
import datetime as dt
import json
import os

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PB_HOT = 0.85     # 破净率到近 10 年 85% 分位以上 = 见底


def _series(key):
    try:
        d, src = S.get_series(key)
        return sorted(d), d, src
    except Exception as e:  # noqa: BLE001
        print(f"[参考] {key} 取不到：{e}")
        return [], {}, None


def pct_at(keys, d, day, years, min_n=200):
    """day 当天的值在之前 years 年里的百分位（只用 day 之前的数据）"""
    j = bisect.bisect_right(keys, day) - 1
    if j < 0:
        return None
    lo = bisect.bisect_left(keys, (dt.date.fromisoformat(keys[j]) - dt.timedelta(days=int(years * 365.25))).isoformat())
    w = [d[k] for k in keys[lo:j]]
    if len(w) < min_n:
        return None
    v = d[keys[j]]
    return sum(x < v for x in w) / len(w)


def pb_hot_series():
    """每个交易日破净率是否 ≥85% 分位，返回 dict(date -> bool)。轮动回测和当前信号都用它。"""
    k, d, _ = _series("pb_below")
    out = {}
    for day in k:
        p = pct_at(k, d, day, 10)
        if p is not None:
            out[day] = p >= PB_HOT
    return out


def hot_lookup(hot):
    ks = sorted(hot)

    def f(day):
        j = bisect.bisect_right(ks, day) - 1
        return hot[ks[j]] if j >= 0 else False
    return f


def ma(d, keys, n):
    out, s = {}, 0.0
    for i, k in enumerate(keys):
        s += d[k]
        if i >= n:
            s -= d[keys[i - n]]
        if i >= n - 1:
            out[k] = s / n
    return out


def run():
    pbk, pb, _ = _series("pb_below")
    mrk, mr, _ = _series("margin_ratio")
    mk, mg, _ = _series("margin")
    ak, am, _ = _series("mkt_amt")
    ck, cpe, _ = _series("pe_cyb")
    kk, kpe, _ = _series("pe_kc")
    ek, et, _ = _series("etf300")
    pk, pe300, _ = _series("pe300")
    yk, y10, _ = _series("cn10y")
    am20 = ma(am, ak, 20) if ak else {}
    a2k = sorted(am20)
    erp = {}
    for day in pk:
        j = bisect.bisect_right(yk, day) - 1
        if j >= 0 and pe300[day] > 0:
            erp[day] = 100 / pe300[day] - y10[yk[j]]
    ek2 = sorted(erp)

    def items(day):
        it = {}
        p = pct_at(pbk, pb, day, 10)
        it["pb"] = {"name": "破净率", "pct": p, "bottom": p, "val": pb.get(pbk[bisect.bisect_right(pbk, day) - 1]) if pbk else None}
        p = pct_at(ek2, erp, day, 10)
        it["erp"] = {"name": "股债利差", "pct": p, "bottom": p}
        p = pct_at(mrk, mr, day, 3)
        it["margin"] = {"name": "融资占流通市值", "pct": p, "bottom": None if p is None else 1 - p}
        p = pct_at(a2k, am20, day, 3)
        it["amt"] = {"name": "两市成交额(20日均)", "pct": p, "bottom": None if p is None else 1 - p}
        p = pct_at(ck, cpe, day, 10, 50)
        it["pe_cyb"] = {"name": "创业板指市盈率", "pct": p, "bottom": None if p is None else 1 - p}
        return it

    def score(it):
        xs = [v["bottom"] for v in it.values() if v["bottom"] is not None]
        return round(100 * sum(xs) / len(xs), 1) if xs else None

    today = max(pbk[-1] if pbk else "", ak[-1] if ak else "", mk[-1] if mk else "")
    it = items(today)
    sc = score(it)
    # 近 3 年每周的见底评分
    hist, d0 = [], dt.date.fromisoformat(today) - dt.timedelta(days=3 * 365)
    day = d0
    while day.isoformat() <= today:
        s = score(items(day.isoformat()))
        if s is not None:
            hist.append([day.isoformat(), s])
        day += dt.timedelta(days=7)

    def last(keys, d, back=0):
        return d[keys[-1 - back]] if len(keys) > back else None
    m20 = (last(mk, mg) / last(mk, mg, 20) - 1) if len(mk) > 20 else None
    e20 = (last(ek, et) / last(ek, et, 20) - 1) if len(ek) > 20 else None
    pbp = it["pb"]["pct"]
    zone = "接近底部" if sc is not None and sc >= 75 else "偏冷" if sc is not None and sc >= 60 else \
        "偏热" if sc is not None and sc < 30 else "正常"
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "date": today, "score": sc, "zone": zone, "hist": hist,
        "pb_hot": bool(pbp is not None and pbp >= PB_HOT), "pb_hot_line": PB_HOT,
        "items": it,
        "extra": {
            "pb_val": last(pbk, pb), "erp_val": round(last(ek2, erp), 2) if ek2 else None,
            "margin_val": last(mk, mg), "margin_chg20": round(m20, 4) if m20 is not None else None,
            "amt_val": last(ak, am), "amt20": round(last(a2k, am20), 0) if a2k else None,
            "pe_cyb": last(ck, cpe), "pe_kc": last(kk, kpe),
            "pe_kc_pct": pct_at(kk, kpe, kk[-1], 10, 50) if kk else None,
            "etf300": last(ek, et), "etf300_chg20": round(e20, 4) if e20 is not None else None, "etf300_days": len(ek),
        },
    }
    with open(os.path.join(ROOT, "data", "market.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 market.json：{today} 见底评分 {sc}（{zone}），破净率分位 {pbp}")
    return data
