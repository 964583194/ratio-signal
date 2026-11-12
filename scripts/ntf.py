"""国家队宽基 ETF 流向：只作提醒，不改定投倍数。

净申购（亿元）= 当天份额变化 × 单位净值。份额来自上交所、深交所，单位净值来自天天基金；缓存 data/raw/ntf.json（2023 年起）。
  加速度 = 4 只沪深300 ETF（510300/510310/510330/159919）近 20 日日均净申购 − 近 60 日日均
  流入在加速：加速度在近一年（250 个交易日）最高的 10%；流出在加速：最低的 10%；其余平稳
  放量托底日：3 只上交所沪深300 ETF 成交额 ≥ 前 20 日均值的 2.5 倍，且当天下跌
加仓提醒：流入在加速刚出现（新的一段）→ 宽基额外买 4 周的量，分 2~4 周买完；同一段只加一次；市场在偏热 / 顶部区不加。
分指数：近 5 / 20 日和今年以来各指数 ETF 净申购，看国家队在买哪个指数。
"""
import bisect
import datetime as dt
import json
import os
import statistics as st
import time

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "raw", "ntf.json")
OUT = os.path.join(ROOT, "data", "ntf.json")
GROUPS = {   # 指数 → ETF
    "沪深300": ["510300", "510310", "510330", "159919"],
    "上证50": ["510050", "510100"],
    "中证500": ["510500", "512500", "159922"],
    "中证1000": ["512100", "159845"],
    "科创50": ["588000", "588080"],
    "创业板": ["159915", "159949"],
    "A500": ["512050", "563360", "560610", "563800", "512020", "159338", "159352", "159361"],
}
FOUR = GROUPS["沪深300"]
AMT = ("510300", "510310", "510330")
CODES = [c for v in GROUPS.values() for c in v]
SHORT, LONG, WIN, HI, LO, VOL = 20, 60, 250, 0.90, 0.10, 2.5
FRESH = 20     # 新的一段加速流入出现后 20 个交易日内，算“刚出现”


def _load(p, d):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return d


def refresh(C):
    """增量更新份额、净值、成交额；失败就用缓存"""
    sh, nav, amt = C.setdefault("shares", {}), C.setdefault("nav", {}), C.setdefault("amt", {})
    last = max(sh.get("510300", {"2023-01-01": 0}))
    for d in S._wdays(last)[1:][-20:]:       # 上交所：一天一次，全部 ETF
        try:
            day = S.sse_scale_day(d)
        except Exception as e:  # noqa: BLE001
            print("国家队流向：上交所", d, e)
            continue
        for c in CODES:
            if day.get(c):
                sh.setdefault(c, {})[d] = day[c]
    try:                                       # 深交所：一次取近一段，全部基金
        import akshare as ak  # noqa: PLC0415
        d0 = (dt.date.today() - dt.timedelta(days=20)).strftime("%Y%m%d")
        for k in range(3):
            try:
                df = ak.fund_scale_daily_szse(start_date=d0, end_date=dt.date.today().strftime("%Y%m%d"))
                break
            except Exception:  # noqa: BLE001
                time.sleep(5 * (k + 1))
        else:
            raise RuntimeError("深交所接口连不上")
        x = df[df["基金代码"].astype(str).isin(CODES)]
        for _, r in x.iterrows():
            sh.setdefault(str(r["基金代码"]), {})[str(r["日期"])[:10]] = float(r["基金份额"])
    except Exception as e:  # noqa: BLE001
        print("国家队流向：深交所", e)
    for c in CODES:                            # 单位净值
        try:
            nav.setdefault(c, {}).update(S.em_lsjz(c, 1))
        except Exception:  # noqa: BLE001
            try:
                nav[c] = {d: v for d, v in S.em_pzd(c).items() if d >= "2023-01-01"}
            except Exception as e:  # noqa: BLE001
                print("国家队流向：净值", c, e)
    beg = (dt.date.fromisoformat(max(amt or {"2023-01-01": 0})) - dt.timedelta(days=10)).strftime("%Y%m%d")
    for c in AMT:                              # 成交额（亿元）
        try:
            for d, v in S.em_amount("1." + c, beg).items():
                amt.setdefault(d, {})[c] = round(v, 3)
        except Exception as e:  # noqa: BLE001
            print("国家队流向：成交额", c, e)


def run():
    C = _load(CACHE, {})
    if not os.environ.get("NO_FETCH"):
        refresh(C)
        with open(CACHE, "w", encoding="utf-8") as fh:
            json.dump(C, fh, separators=(",", ":"))
    sh, nav, amt = C["shares"], C["nav"], C["amt"]
    px = nav["510300"]                          # 交易日 = 510300 有净值的日子
    days = sorted(d for d in px if d >= "2023-01-01" and d in sh.get("510300", {}))
    nk = {c: sorted(nav.get(c, {})) for c in CODES}
    shk = {c: sorted(sh.get(c, {})) for c in CODES}

    def at(src, ks, d):
        j = bisect.bisect_right(ks, d) - 1
        return src[ks[j]] if j >= 0 else None
    flow = {c: [0.0] * len(days) for c in CODES}
    for c in CODES:
        prev = None
        for i, d in enumerate(days):
            s = sh.get(c, {}).get(d)
            if s is None:
                continue
            n = at(nav.get(c, {}), nk[c], d)
            if prev is not None and n:
                flow[c][i] = (s - prev) / 1e8 * n
            prev = s
    n = len(days)
    f4 = [sum(flow[c][i] for c in FOUR) for i in range(n)]
    acc = [None] * n
    for i in range(LONG - 1, n):
        acc[i] = sum(f4[i - SHORT + 1:i + 1]) / SHORT - sum(f4[i - LONG + 1:i + 1]) / LONG
    pct, state = [None] * n, [None] * n
    for i in range(n):
        if acc[i] is None:
            continue
        w = [x for x in acc[max(0, i - WIN):i + 1] if x is not None]
        if len(w) < 60:
            continue
        pct[i] = sum(x <= acc[i] for x in w) / len(w)
        state[i] = "流入在加速" if pct[i] >= HI else "流出在加速" if pct[i] <= LO else "平稳"
    close = [px[d] for d in days]

    def fwd(i):
        return {str(h): round(close[i + h] / close[i] - 1, 4) if i + h < n else None for h in (20, 60, 120)}
    # 加速流入的每一段：第一天
    eps = [{"date": days[i], "acc": round(acc[i], 1), "fwd": fwd(i)} for i in range(1, n)
           if state[i] == "流入在加速" and state[i - 1] != "流入在加速"]
    # 放量托底日
    A = [sum((amt.get(d) or {}).get(c, 0) for c in AMT) for d in days]
    vols = []
    for i in range(20, n):
        m = st.mean(A[i - 20:i])
        if m and A[i] >= VOL * m and close[i] < close[i - 1]:
            vols.append({"date": days[i], "x": round(A[i] / m, 1), "amt": round(A[i]), "fwd": fwd(i)})

    def agg(rows):
        o = {"n": len(rows)}
        for h in ("20", "60", "120"):
            xs = [r[h] for r in rows if r[h] is not None]
            o[h] = {"avg": round(st.mean(xs), 4), "up": round(sum(x > 0 for x in xs) / len(xs), 3), "n": len(xs)} if xs else None
        return o
    stats = {"流入在加速（每天）": agg([fwd(i) for i in range(n) if state[i] == "流入在加速"]),
             "流出在加速（每天）": agg([fwd(i) for i in range(n) if state[i] == "流出在加速"]),
             "加速流入第一天": agg([e["fwd"] for e in eps]),
             "放量托底日": agg([v["fwd"] for v in vols]),
             "全部交易日": agg([fwd(i) for i in range(n) if state[i]])}
    # 分指数
    year = days[-1][:4]
    yi = next(i for i, d in enumerate(days) if d.startswith(year))
    gt = lambda cs, a, b: round(sum(flow[c][i] for c in cs for i in range(a, b)))  # noqa: E731
    groups = [{"name": g, "d5": gt(cs, n - 5, n), "d20": gt(cs, n - 20, n), "ytd": gt(cs, yi, n)} for g, cs in GROUPS.items()]
    total = {"name": "合计", **{k: sum(g[k] for g in groups) for k in ("d5", "d20", "ytd")}}
    # 现在
    i = n - 1
    s = state[i]
    last_ep = eps[-1] if eps else None
    since = days.index(last_ep["date"]) if last_ep else None
    fresh = s == "流入在加速" and since is not None and i - since < FRESH
    T = _load(os.path.join(ROOT, "data", "temp.json"), {})
    z = (T.get("latest") or {}).get("z")
    hot = z is not None and z >= 3
    if fresh and not hot:
        act, cls, key = f"国家队在加速买入（{last_ep['date']} 开始）：可以在宽基（A500 / 沪深300）上额外买 4 周的量，分 2~4 周买完；这一段只加这一次", "g1", "加仓|" + last_ep["date"]
    elif fresh:
        act, cls, key = "国家队在加速买入，但市场在偏热 / 顶部区，这次不额外加", "c0", "偏热不加|" + last_ep["date"]
    elif s == "流入在加速":
        act, cls, key = f"加速还在持续（{last_ep['date']} 开始，已经提醒过加仓），照常", "c0", "持续|" + last_ep["date"]
    elif s == "流出在加速":
        act, cls, key = "国家队在加速撤出，之后沪深300 偏弱，别额外加钱", "h1", "流出在加速"
    else:
        act, cls, key = "流入流出没有明显加速，照常", "c0", "平稳"
    lv = vols[-1] if vols else None
    vol_recent = bool(lv and days.index(lv["date"]) >= n - 5)
    hs, _ = S.get_series("hs300")
    hk = sorted(hs)
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": days[-1], "state": s, "acc": round(acc[i], 1), "pct": round(pct[i], 3), "f4_20": round(sum(f4[-20:])),
                   "action": act, "cls": cls, "key": key, "episode": last_ep, "fresh": fresh, "hot": hot,
                   "vol_last": lv, "vol_recent": vol_recent},
        "groups": groups + [total],
        "episodes": eps, "vols": vols, "stats": stats,
        "series": [[days[k], None if acc[k] is None else round(acc[k], 1), None if pct[k] is None else round(pct[k] * 100),
                    round(sum(f4[max(0, k - 19):k + 1])), hs[hk[max(0, bisect.bisect_right(hk, days[k]) - 1)]]] for k in range(n)],
        "rule": {"short": SHORT, "long": LONG, "win": WIN, "hi": HI, "lo": LO, "vol": VOL},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{days[-1]} {s}（加速度 {acc[i]:+.1f} 亿/天，近一年 {pct[i]:.0%} 分位），{act}；"
          f"放量托底日最近 {lv['date'] if lv else '无'}")
    return data


if __name__ == "__main__":
    run()
