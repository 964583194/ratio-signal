"""国家队宽基 ETF 流向：只作提醒，不改定投倍数。

净申购（亿元）= 当天份额变化 × 单位净值。份额来自上交所、深交所，单位净值来自天天基金；缓存 data/raw/ntf.json（2023 年起）。
  加速度 = 4 只沪深300 ETF（510300/510310/510330/159919）近 20 日日均净申购 − 近 60 日日均
  集中大买：近 20 日净申购 ≥ 沪深300 流通市值的 2‰；集中大卖：≤ −2‰；其余平稳（2026-11-27 起，原来看加速度排名）
  放量托底日：3 只上交所沪深300 ETF 成交额 ≥ 前 20 日均值的 2.5 倍，且当天下跌（测过不用：之后 60 天没有优势，只留回测）
  加速流出之后只是略弱，不提醒
加仓提醒：集中大买刚出现（新的一段）→ 宽基额外买 4 周的量，分 2~4 周买完；同一段只加一次；市场在偏热 / 顶部区不加。
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
RUSH = 0.0015  # 急买 / 急卖：近 5 日净申购（赎回）≥ 沪深300 流通市值的 1.5‰
BIG = 0.002    # 集中大买 / 集中大卖：近 20 日净申购（赎回）≥ 沪深300 流通市值的 2‰
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
    d20 = [sum(f4[max(0, k - 19):k + 1]) for k in range(n)]
    pct, state = [None] * n, [None] * n
    for i in range(n):
        if acc[i] is None:
            continue
        w = [x for x in acc[max(0, i - WIN):i + 1] if x is not None]
        if len(w) < 60:
            continue
        pct[i] = sum(x <= acc[i] for x in w) / len(w)
        # 2026-11-27：加速流入还要求近 20 日确实净流入。原来只比速度，大卖之后"不卖了"也会被算成加速流入（2026-03 误报过）
    close = [px[d] for d in days]
    # 2026-11-27 改：不再看"加速度"排名（买得越久越稳定，60 日均值也跟着变大，反而显示不在加速；大卖后"不卖了"又会误报），
    # 改成直接看近 20 日净申购占沪深300 流通市值：≥2‰ 集中大买，≤−2‰ 集中大卖。买卖同一把尺子，相对值不用改门槛。
    E3 = _load(os.path.join(ROOT, "data", "etf300.json"), {}).get("latest") or {}
    cap0 = E3["size"] / (E3["ratio"] / 100) if E3.get("size") and E3.get("ratio") else None   # 亿元
    cap = [cap0 * close[k] / close[-1] if cap0 else None for k in range(n)]   # 按 510300 净值涨跌推算每天的流通市值
    r20 = [d20[k] / cap[k] if cap[k] else None for k in range(n)]
    for i in range(n):
        if r20[i] is None or i < 19:
            continue
        state[i] = "集中大买" if r20[i] >= BIG else "集中大卖" if r20[i] <= -BIG else "平稳"

    def fwd(i):
        return {str(h): round(close[i + h] / close[i] - 1, 4) if i + h < n else None for h in (20, 60, 120)}
    # 加速流入的每一段：第一天
    # 前 20 个交易日里已经加速过的不算新的一段（加了"近 20 日净流入"条件后，一段里可能断开一两天又接上，不能重复提醒加仓）
    eps = [{"date": days[i], "acc": round(acc[i], 1), "fwd": fwd(i)} for i in range(1, n)
           if state[i] == "集中大买" and "集中大买" not in state[max(0, i - FRESH):i]]
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
    stats = {"集中大买（每天）": agg([fwd(i) for i in range(n) if state[i] == "集中大买"]),
             "集中大卖（每天）": agg([fwd(i) for i in range(n) if state[i] == "集中大卖"]),
             "集中大买第一天": agg([e["fwd"] for e in eps]),
             "放量托底日": agg([v["fwd"] for v in vols]),
             "全部交易日": agg([fwd(i) for i in range(n) if state[i]])}
    # 分指数
    year = days[-1][:4]
    yi = next(i for i, d in enumerate(days) if d.startswith(year))
    gt = lambda cs, a, b: round(sum(flow[c][i] for c in cs for i in range(a, b)))  # noqa: E731
    groups = [{"name": g, "d5": gt(cs, n - 5, n), "d20": gt(cs, n - 20, n), "ytd": gt(cs, yi, n)} for g, cs in GROUPS.items()]
    total = {"name": "合计", **{k: sum(g[k] for g in groups) for k in ("d5", "d20", "ytd")}}
    # 现在
    # 大买之后的回落（实验，只作提醒）：近 20 天里 20 日净申购排进近一年最高 10%（大买过），现在近 5 日净赎回、20 日仍净流入
    d5 = [sum(f4[max(0, k - 4):k + 1]) for k in range(n)]
    p20 = [sum(x <= d20[k] for x in d20[max(0, k - 250):k + 1]) / len(d20[max(0, k - 250):k + 1]) for k in range(n)]

    def pull_of(k):
        if k < 60 or not (d5[k] < 0 < d20[k]) or max(p20[max(0, k - 20):k + 1]) < 0.9:
            return None
        return "明显回落" if -d5[k] >= d20[k] / 4 else "轻度回落"
    pulls = [pull_of(k) for k in range(n)]
    pstats = {lab: agg([fwd(k) for k in range(n) if pulls[k] == lab]) for lab in ("轻度回落", "明显回落")}
    pstats["任意一天"] = agg([fwd(k) for k in range(60, n)])
    pnow = pulls[-1]
    run_n = 0                       # 回落已经连续几天
    for k in range(n - 1, -1, -1):
        if not pulls[k]:
            break
        run_n += 1
    pull = {"level": pnow or ("持续流入" if d5[-1] > 0 and d20[-1] > 0 else "无"), "d5": round(d5[-1]), "d20": round(d20[-1]),
            "days": run_n, "since": days[n - run_n] if run_n else None,
            "note": {"轻度回落": "国家队大买后开始小幅赎回：短期偏弱（之后 60 日沪深300 平均约 −2%），按规则买，不额外加钱",
                     "明显回落": "国家队大买后赎回较多（超过近 20 日流入的 1/4）：短期偏弱（之后 60 日平均约 −5%），按规则买，不额外加钱"}.get(pnow, "没有大买后回落"),
            "stats": pstats}
    # 国家队急买 / 急卖（实验，只作提醒）：买卖都用同一把尺子 —— 净申购 ÷ 沪深300 流通市值（相对值，市场变大也不用改门槛）。
    # 不用"占成交额"：高位时成交额很大，卖出的占比会被稀释（2026-06 底 5 天卖了约 1000 亿，只占成交额 0.57%，占市值 1.6‰）
    r5 = [d5[k] / cap[k] if cap[k] else None for k in range(n)]
    rush_on = [x is not None and x >= RUSH for x in r5]
    reps = [{"date": days[k], "r5": round(r5[k], 4), "d5": round(d5[k]), "fwd": fwd(k)}
            for k in range(1, n) if rush_on[k] and not any(rush_on[max(0, k - 20):k])]
    rrun = 0
    for k in range(n - 1, -1, -1):
        if not rush_on[k]:
            break
        rrun += 1
    rush = {"on": rush_on[-1], "r5": None if r5[-1] is None else round(r5[-1], 5), "d5": round(d5[-1]), "th": RUSH,
            "r20": None if r20[-1] is None else round(r20[-1], 5), "d20": round(d20[-1]), "th20": BIG,
            "big": bool(r20[-1] is not None and r20[-1] >= BIG), "sell5": bool(r5[-1] is not None and r5[-1] <= -RUSH),
            "sell20": bool(r20[-1] is not None and r20[-1] <= -BIG),
            "days": rrun, "since": days[n - rrun] if rrun else None, "last": reps[-1] if reps else None,
            "stats": {"急买第一天": agg([e["fwd"] for e in reps]), "任意一天": pstats["任意一天"]}}
    i = n - 1
    s = state[i]
    last_ep = eps[-1] if eps else None
    since = days.index(last_ep["date"]) if last_ep else None
    fresh = s == "集中大买" and since is not None and i - since < FRESH
    T = _load(os.path.join(ROOT, "data", "temp.json"), {})
    z = (T.get("latest") or {}).get("z")
    hot = z is not None and z >= 3
    if fresh and not hot:
        act, cls, key = f"国家队集中大买（{last_ep['date']} 开始，近 20 日净申购占沪深300 市值 {r20[i] * 1000:.1f}‰）：可以在宽基（A500 / 沪深300）上额外买 4 周的量，分 2~4 周买完；这一段只加这一次", "g1", "加仓|" + last_ep["date"]
    elif fresh:
        act, cls, key = "国家队集中大买，但市场在偏热 / 顶部区，这次不额外加", "c0", "偏热不加|" + last_ep["date"]
    elif s == "集中大买":
        act, cls, key = f"集中大买还在持续（{last_ep['date']} 开始；每一段只在开始时加一次仓），照常", "c0", "持续|" + last_ep["date"]
    elif s == "集中大卖":
        act, cls, key = "国家队在集中卖出：在高位时要警惕（见组合信号\"高位撤离\"），照常", "c0", "平稳"
    else:
        act, cls, key = f"没有集中大买大卖（近 20 日净申购占市值 {(r20[i] or 0) * 1000:+.1f}‰，±2‰ 才算），照常", "c0", "平稳"
    lv = vols[-1] if vols else None
    vol_recent = bool(lv and days.index(lv["date"]) >= n - 5)
    hs, _ = S.get_series("hs300")
    hk = sorted(hs)
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": days[-1], "state": s, "acc": round(acc[i], 1), "pct": round(pct[i], 3), "r20": None if r20[i] is None else round(r20[i], 5), "big": BIG, "f4_20": round(sum(f4[-20:])),
                   "action": act, "cls": cls, "key": key, "episode": last_ep, "fresh": fresh, "hot": hot,
                   "vol_last": lv, "vol_recent": vol_recent, "pull": pull, "rush": rush},
        "rush_eps": reps,
        "groups": groups + [total],
        # 各指数每天净申购（亿元），2023 年起全部，给"国家队每天买了多少"图分指数堆叠用
        "gflow": {"from": days[0], "names": list(GROUPS),
                  "v": {g: [round(sum(flow[c][k] for c in cs), 1) for k in range(n)] for g, cs in GROUPS.items()}},
        "episodes": eps, "vols": vols, "stats": stats,
        "series": [[days[k], None if acc[k] is None else round(acc[k], 1), None if pct[k] is None else round(pct[k] * 100),
                    round(sum(f4[max(0, k - 19):k + 1])), hs[hk[max(0, bisect.bisect_right(hk, days[k]) - 1)]], round(f4[k], 1), None if cap[k] is None else round(cap[k])] for k in range(n)],
        "rule": {"short": SHORT, "long": LONG, "win": WIN, "hi": HI, "lo": LO, "vol": VOL},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{days[-1]} {s}（近 20 日占市值 {(r20[i] or 0) * 1000:+.1f}‰），{act}；"
          f"放量托底日最近 {lv['date'] if lv else '无'}")
    return data


if __name__ == "__main__":
    run()
