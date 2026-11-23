"""
红利低波100 · 每日定投打分（0~20 分），写入 data/dividend.json。

四个维度（分越高越便宜）：
  估值面 15%：PE 在历史全部交易日中的位置，比现在更贵的天数占比
  技术面 50%：RSI(70) 与布林 %B(100)，跌得越狠、离上轨越远分越高
  利差   25%：股息率 − 十年国债，0~4pp 线性，4pp 以上满分
  风格   10%：红利÷创业板50 强弱的历史分位，越拥挤分越低
总分 = 20 × 加权分 / 100

数据：930955 收盘与 PE、H20955 全收益（推算股息率）来自中证指数官网；
十年国债收益率来自东方财富数据中心。所有分位都只用当日及之前的数据，回测没有未来函数。
"""
import bisect
import datetime as dt
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "dividend.json")

BASE = 200            # 每个交易日基数（元）
FEE = 0.0005          # 买卖费率
CASH = 0.017          # 现金池 / 卖出池年化
W = {"val": .15, "tech": .50, "spread": .25, "style": .10}
TIERS = [(18, 5, "加码"), (16, 4, "加码"), (14, 3, "加码"), (12, 2, "多买 · 买回"),
         (10, 1, "正常"), (8, .5, "少买")]
SELLS = [(6, .25), (4, 1 / 3), (2, .5)]
WARMUP = 250          # 分位至少需要的历史交易日



# ---------------------------------------------------------------- 指标
def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def rsi_wilder(closes, n=70):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0)
        losses += max(-ch, 0)
    ag, al = gains / n, losses / n
    out[n] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(ch, 0)) / n
        al = (al * (n - 1) + max(-ch, 0)) / n
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def pct_b(closes, n=100):
    out = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        out[i] = 0.5 if sd == 0 else (closes[i] - (m - 2 * sd)) / (4 * sd)
    return out


def expanding_share(values, cmp):
    """逐日计算：历史（含当日）中满足 cmp 的占比。cmp='ge' 表示 >= 当前值的占比"""
    hist, out = [], []
    for v in values:
        if v is None:
            out.append(None)
            continue
        bisect.insort(hist, v)
        n = len(hist)
        if n < WARMUP:
            out.append(None)
            continue
        if cmp == "ge":
            out.append((n - bisect.bisect_left(hist, v)) / n)
        else:  # 'lt'：严格小于当前值的占比
            out.append(bisect.bisect_left(hist, v) / n)
    return out


def tier(score):
    for th, mult, name in TIERS:
        if score >= th:
            return mult, name
    if score <= 2:
        return 0, "减仓 50%"
    if score <= 4:
        return 0, "减仓 33%"
    if score <= 6:
        return 0, "减仓 25%"
    return 0, "空仓"


def confirm(scores, days=2):
    """换档要连续 2 天落在新档位才算，避免在 8 分、10 分线上下来回跳（回测：年化 8.59% → 8.62%，换档次数 389 → 209）。
    返回“执行用的分数”：没确认前沿用上一个确认过的分数。"""
    out, cur, pend = [], None, 0
    for x in scores:
        if cur is None or tier(x)[0] == tier(cur)[0]:    # 只看倍数：减仓线照常当天生效
            cur, pend = x, 0
        else:
            pend += 1
            if pend >= days:
                cur, pend = x, 0
        out.append(cur)
    return out


def xirr(cfs):
    d0 = cfs[0][0]

    def npv(r):
        return sum(a / (1 + r) ** ((d - d0).days / 365.0) for d, a in cfs)
    lo, hi = -0.9, 3.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


DOWN = 2   # 攒着一起买：红利低波100 连续跌 DOWN 个交易日后，第二天把攒着的一起买


def gates(px):
    """第 i 天是不是下单日：前 DOWN 个交易日都收跌（下单前就知道）"""
    return [i >= DOWN and all(px[i - j] < px[i - j - 1] for j in range(1, DOWN + 1)) for i in range(len(px))]


def simulate(dates, tr, scores, mode, gate=None):
    """预算中性：外部每天投入 BASE，少投的进现金池；多投从现金池出，池子不够就投池子里有的。
    gate：下单日列表（攒着一起买）；不是下单日时，当天该买的金额先记着，到下单日一起买。"""
    owed = 0.0
    hold = pool = sell_pool = 0.0
    nav, peak, mdd, prev = 1.0, 1.0, 0.0, 0.0
    hit, cfs = set(), []
    for i, d in enumerate(dates):
        if i > 0:
            hold *= tr[i] / tr[i - 1]
            pool *= 1 + CASH / 252
            sell_pool *= 1 + CASH / 252
        cur = hold + pool + sell_pool
        if prev > 0:
            nav *= cur / prev
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
        pool += BASE
        cfs.append((d, -BASE))
        if mode == "plain":
            hold += pool * (1 - FEE)
            pool = 0.0
        elif i > 0:
            s = scores[i - 1]   # 用前一天收盘的评分：当天的评分收盘后才知道，场外基金只能按当天 15:00 前已知的信号下单
            for th, frac in SELLS:
                if s <= th and th not in hit:
                    amt = hold * frac
                    hold -= amt
                    sell_pool += amt * (1 - FEE)
                    hit.add(th)
            if s >= 12:
                hit.clear()
                if sell_pool > 0:
                    hold += sell_pool * (1 - FEE)
                    sell_pool = 0.0
            mult, _ = tier(s)
            owed += BASE * mult
            if gate is None or gate[i]:
                amt = min(owed, pool)
                hold += amt * (1 - FEE)
                pool -= amt
                owed = 0.0
        prev = hold + pool + sell_pool
    final = hold + pool + sell_pool
    cfs.append((dates[-1], final))
    x = xirr(cfs)
    return {"xirr": round(x, 4) if x is not None else None, "mdd": round(mdd, 4),
            "calmar": round(x / -mdd, 2) if x and mdd < 0 else None,
            "final": round(final), "invested": BASE * len(dates),
            "pool": round(pool + sell_pool), "hold": round(hold)}


def autocorr20(closes):
    r = [math.log(closes[i] / closes[i - 20]) for i in range(20, len(closes), 20)]
    m = sum(r) / len(r)
    num = sum((r[i] - m) * (r[i - 1] - m) for i in range(1, len(r)))
    den = sum((x - m) ** 2 for x in r)
    return num / den if den else 0.0


def max_dd(closes):
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    return mdd


# ---------------------------------------------------------------- 主流程
def run(cyb_raw):
    import sources as S
    close, _ = S.get_series("hl100", 2500)
    pe_raw, _ = S.get_series("hl100_pe", 2000)
    tr_raw, _ = S.get_series("hl100_tr", 2500)
    y10, _ = S.get_series("cn10y", 2500)
    px = {d: (v, pe_raw.get(d)) for d, v in close.items()}
    # 全收益指数偶尔比价格晚几天（中证停更、东方财富没有）：缺的几天按价格涨跌补上（几天内分红影响可忽略）
    # 中间缺的日子（比如 11-12 没发、11-13 又有了）也一样补，不然那天会从评分里掉出去
    t0, prev = min(tr_raw), None
    for d in sorted(x for x in close if x >= t0):
        if d in tr_raw:
            prev = d
        elif prev is not None and prev in close:
            tr_raw[d] = tr_raw[prev] * close[d] / close[prev]
            prev = d
    tr = {d: (v, None) for d, v in tr_raw.items()}
    print(f"红利低波100：价格 {len(px)} 天、全收益 {len(tr)} 天；十年国债 {len(y10)} 天")
    if len(px) < 1000 or len(tr) < 1000 or len(y10) < 1000:
        raise RuntimeError("红利打分所需数据不足")

    dates = sorted(set(px) & set(tr))
    close = [px[d][0] for d in dates]
    tri = [tr[d][0] for d in dates]
    pe, last_pe = [], None
    for d in dates:
        last_pe = px[d][1] or last_pe
        pe.append(last_pe)

    # 股息率：近 12 个月全收益涨幅 ÷ 价格涨幅 − 1
    dy = []
    j = 0
    dobj = [dt.date.fromisoformat(d) for d in dates]
    for i, d in enumerate(dobj):
        while dobj[j] < d - dt.timedelta(days=365):
            j += 1
        dy.append(None if (d - dobj[j]).days < 350 else
                  (tri[i] / tri[j]) / (close[i] / close[j]) - 1)

    yk = sorted(y10)
    y_on = []
    for d in dates:
        k = bisect.bisect_right(yk, d) - 1
        y_on.append(y10[yk[k]] if k >= 0 else None)

    ck = sorted(cyb_raw)
    style_ratio = []
    for i, d in enumerate(dates):
        k = bisect.bisect_right(ck, d) - 1
        style_ratio.append(close[i] / cyb_raw[ck[k]] if k >= 0 and (d >= ck[0]) else None)

    rsi = rsi_wilder(close)
    pb = pct_b(close)
    pe_dear = expanding_share(pe, "lt")          # 比现在更便宜（PE 更低）的天数占比 = “比历史 x% 的时间都贵”
    sty_pct = expanding_share(style_ratio, "lt")  # 红利/创业板 强弱分位

    rows = []
    for i, d in enumerate(dates):
        if None in (rsi[i], pb[i], pe_dear[i], sty_pct[i], dy[i], y_on[i]):
            continue
        v = 100 * (1 - pe_dear[i])
        t = 100 * (clip((70 - rsi[i]) / 40) + clip(1 - pb[i])) / 2
        sp = dy[i] * 100 - y_on[i]
        s = 100 * clip(sp / 4)
        f = 100 * (1 - sty_pct[i])
        score = 20 * (W["val"] * v + W["tech"] * t + W["spread"] * s + W["style"] * f) / 100
        rows.append({"i": i, "date": d, "score": score, "val": v, "tech": t, "spread": s,
                     "style": f, "rsi": rsi[i], "pb": pb[i], "pe": pe[i], "pe_dear": pe_dear[i],
                     "dy": dy[i], "y10": y_on[i], "sp": sp, "sty_pct": sty_pct[i]})
    if not rows:
        raise RuntimeError("没有算出任何评分")

    # ------------------------------------------------ 红利位置（实验，只作参考，不改买卖）
    # 股息率、股债利差各自在近 5 年（约 1220 个交易日）里高于多少比例的日子，取平均：越高 = 股息越丰厚 = 越便宜。
    # 回测（2012-12 起）：便宜（≥80%）之后一年 94% 上涨、一年内平均最多再跌 5.5%；偏贵（20~40%）之后半年平均 −3.1%、最多再跌 15%。
    def _p5(x, i, win=1220, minn=480):
        h = [v for v in x[max(0, i - win + 1):i + 1] if v is not None]
        return None if x[i] is None or len(h) < minn else sum(1 for v in h if v < x[i]) / len(h)
    sp_all = [None if dy[i] is None or y_on[i] is None else dy[i] * 100 - y_on[i] for i in range(len(dates))]
    pos = []
    for i in range(len(dates)):
        a_, b_ = _p5(sp_all, i), _p5(dy, i)
        pos.append(None if a_ is None or b_ is None else (a_ + b_) / 2)
    POSZ = [(.8, "便宜", "可以坚定按规则买，有余钱可以多加"), (.6, "偏便宜", "按规则买，可以放心"),
            (.4, "中间", "按规则买"), (.2, "偏贵", "按规则买，别额外加钱"), (-1, "贵", "按规则买，别额外加钱")]
    zone_of = lambda v: next(z for z in POSZ if v >= z[0])
    # 每档之后的表现（全收益指数），随数据自动更新
    pos_stats = []
    for k_, (lo, nm, _) in enumerate(POSZ):
        hi = POSZ[k_ - 1][0] if k_ else 2
        idx = [i for i, v in enumerate(pos) if v is not None and lo <= v < hi and i + 244 < len(dates)]
        if not idx:
            pos_stats.append({"zone": nm, "n": 0}); continue
        r6 = [tri[i + 122] / tri[i] - 1 for i in idx]; r12 = [tri[i + 244] / tri[i] - 1 for i in idx]
        dd = [min(tri[i:i + 245]) / tri[i] - 1 for i in idx]
        pos_stats.append({"zone": nm, "n": len(idx), "r6": round(sum(r6) / len(r6), 4), "r12": round(sum(r12) / len(r12), 4),
                          "up12": round(sum(x > 0 for x in r12) / len(r12), 3), "dd": round(sum(dd) / len(dd), 4)})
    pos_week, wk_prev = [], None
    for i, d in enumerate(dates):
        if pos[i] is None:
            continue
        wk = dobj[i].isocalendar()[:2]
        item = [d, round(tri[i], 2), round(dy[i] * 100, 2), round(sp_all[i], 2), round(pos[i], 3)]
        if pos_week and wk == wk_prev:
            pos_week[-1] = item
        else:
            pos_week.append(item)
        wk_prev = wk
    pz = zone_of(pos[-1]) if pos[-1] is not None else None
    pos_now = None if pz is None else {"value": round(pos[-1], 3), "sp_pct": round(_p5(sp_all, len(dates) - 1), 3),
                                       "dy_pct": round(_p5(dy, len(dates) - 1), 3), "zone": pz[1], "advice": pz[2], "date": dates[-1]}

    # ------------------------------------------------ 关键价位：指数在 20 个交易日内匀速涨/跌到某个点位时，评分会落到哪条线
    pe_hist = sorted(v for v in pe if v is not None)
    sty_hist = sorted(v for v in style_ratio if v is not None)
    last_i = rows[-1]["i"]

    def score_after(k, days=20):
        path = [close[last_i] * k ** ((t + 1) / days) for t in range(days)]
        cl = close[:last_i + 1] + path
        rr = rsi_wilder(cl[-400:])[-1]
        b = pct_b(cl[-100:])[-1]
        pe_n = pe[last_i] * k
        dy_n = dy[last_i] / k
        st_n = style_ratio[last_i] * k
        v = 100 * (1 - bisect.bisect_left(pe_hist, pe_n) / len(pe_hist))
        t = 100 * (clip((70 - rr) / 40) + clip(1 - b)) / 2
        s = 100 * clip((dy_n * 100 - y_on[last_i]) / 4)
        f = 100 * (1 - bisect.bisect_left(sty_hist, st_n) / len(sty_hist))
        return 20 * (W["val"] * v + W["tech"] * t + W["spread"] * s + W["style"] * f) / 100

    lines = []
    for target, label in [(14, "加码线"), (12, "多买 · 买回线"), (10, "正常线"), (8, "少买线"),
                          (6, "减仓 25%"), (4, "减仓 33%"), (2, "减仓 50%")]:
        lo_k, hi_k = 0.5, 2.0
        if not (score_after(hi_k) <= target <= score_after(lo_k)):
            lines.append({"score": target, "label": label, "price": None, "chg": None})
            continue
        for _ in range(50):
            mid = (lo_k + hi_k) / 2
            if score_after(mid) > target:
                lo_k = mid
            else:
                hi_k = mid
        k = (lo_k + hi_k) / 2
        lines.append({"score": target, "label": label, "price": round(close[last_i] * k, 0),
                      "chg": round(k - 1, 4)})
    print("关键价位：" + "，".join(f"{x['label']} {x['price']}" for x in lines))

    # 历史检验：评分处于各区间时，之后 60 / 120 个交易日全收益指数的平均涨幅
    def fwd(cond, h):
        xs = [tri[r["i"] + h] / tri[r["i"]] - 1 for r in rows if cond(r["score"]) and r["i"] + h < len(tri)]
        return (round(sum(xs) / len(xs), 4), len(xs)) if xs else (None, 0)
    zones = [("≤6 减仓区", lambda x: x <= 6), ("6~8 空仓", lambda x: 6 < x < 8), ("8~12 少买/正常", lambda x: 8 <= x < 12),
             ("≥12 多买/加码", lambda x: x >= 12), ("全部交易日", lambda x: True)]
    fwd_stats = [{"zone": z, "f60": fwd(c, 60)[0], "f120": fwd(c, 120)[0], "n": fwd(c, 60)[1]} for z, c in zones]
    print("分区后续收益：", fwd_stats)

    bt_dates = [dobj[r["i"]] for r in rows]
    bt_tr = [tri[r["i"]] for r in rows]
    bt_sc = [r["score"] for r in rows]
    eff = confirm(bt_sc)
    bt_px = [close[r["i"]] for r in rows]
    gate = gates(bt_px)
    plain = simulate(bt_dates, bt_tr, eff, "plain")
    daily = simulate(bt_dates, bt_tr, eff, "score")            # 对照：每天买
    scored = simulate(bt_dates, bt_tr, eff, "score", gate)     # 现行：攒着一起买
    # 每天的“攒着 / 下单”：owed 是到当天收盘为止攒着没买的钱（按每天 BASE 元），buy 是当天下单买了多少
    # 第 k 天该记的钱按前一天收盘的评分（和回测、邮件里“明天下单 X 元”一致）
    owed, ledger = 0.0, []
    for k in range(len(eff)):
        owed += BASE * tier(eff[k - 1])[0] if k else 0
        if gate[k]:
            ledger.append((round(owed), 0))
            owed = 0.0
        else:
            ledger.append((0, round(owed)))
    # 减仓：和回测一样，第 k 天按前一天评分卖；每条线（6 / 4 / 2）一段行情只卖一次，评分回到 12 以上重新计
    def sell_step(sc, hit):
        out = [frac for th, frac in SELLS if sc <= th and th not in hit]
        hit.update(th for th, frac in SELLS if sc <= th)
        if sc >= 12:
            hit.clear()
        return out
    hit, sells = set(), [0]
    for k in range(1, len(eff)):
        fr = sell_step(eff[k - 1], hit)
        sells.append(round(fr[-1], 4) if fr else 0)      # 一天跨过几条线时按最深那条
    nxt_sell = sell_step(eff[-1], set(hit))
    # 明天是不是下单日：今天、昨天都收跌
    nxt = len(bt_px) >= 3 and all(bt_px[-j] < bt_px[-j - 1] for j in range(1, DOWN + 1))
    owed_now = ledger[-1][1] + BASE * tier(eff[-1])[0]     # 下个交易日下单要买的：攒着的 + 下个交易日自己的（按今天收盘的评分）
    nd = dt.date.fromisoformat(rows[-1]["date"])
    next_label = "下周一" if nd.weekday() >= 4 else "明天"     # 数据是周五的：下一个交易日是周一（节假日另算）

    last = rows[-1]
    mult, name = tier(eff[-1])
    scores_sorted = sorted(bt_sc)
    hi_r = max(rows, key=lambda r: r["score"])
    lo_r = min(rows, key=lambda r: r["score"])

    cyb_dates = [d for d in ck if d >= dates[0]]
    cyb_close = [cyb_raw[d] for d in cyb_dates]
    r1 = lambda x: round(x, 1)  # noqa: E731
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "params": {"base": BASE, "fee": FEE, "cash": CASH, "weights": W},
        "latest": {
            "date": last["date"], "close": close[last["i"]], "pe": last["pe"],
            "dy": round(last["dy"], 4), "y10": last["y10"], "spread": round(last["sp"], 2),
            "score": round(last["score"], 2), "tier": name, "amount": BASE * mult,
            "eff": round(eff[-1], 2), "pending": tier(last["score"])[0] != tier(eff[-1])[0],   # 新档位还没连续 2 天，先按上一档
            "owed": ledger[-1][1], "buy_next": nxt, "buy_amt": round(owed_now) if nxt else 0, "next_label": next_label,     # 攒着一起买
            "sell_next": round(nxt_sell[-1], 4) if nxt_sell else 0,      # 下个交易日要减仓的比例（0 = 不减）
            "pos": pos_now,        # 实验：红利位置（股息率、利差在近 5 年里的位置），只作参考
            "sub": {"val": r1(last["val"]), "tech": r1(last["tech"]),
                    "spread": r1(last["spread"]), "style": r1(last["style"])},
            "rsi": round(last["rsi"], 1), "pb": round(last["pb"], 2),
            "pe_dear": round(last["pe_dear"], 3), "sty_pct": round(last["sty_pct"], 3),
            "score_pctile": round(bisect.bisect_left(scores_sorted, last["score"]) / len(bt_sc), 3),
        },
        "stats": {"days": len(rows), "start": rows[0]["date"],
                  "max": round(hi_r["score"], 1), "max_date": hi_r["date"],
                  "min": round(lo_r["score"], 1), "min_date": lo_r["date"]},
        "backtest": {"plain": plain, "score": scored, "daily": daily},
        "personality": {
            "hl": {"ac20": round(autocorr20(close), 3), "mdd": round(max_dd(close), 3)},
            "cyb": {"ac20": round(autocorr20(cyb_close), 3), "mdd": round(max_dd(cyb_close), 3)},
            "since": dates[0],
        },
        "lines": lines,
        "forward": fwd_stats,
        "pos_week": pos_week,       # [日期, 全收益, 股息率%, 利差(百分点), 位置 0~1]（实验，每周一条）
        "pos_stats": pos_stats,     # 各档位置之后半年 / 一年的表现
        "series": [[r["date"], round(r["score"], 2), round(close[r["i"]], 2), round(e, 2), b, o, sl] for r, e, (b, o), sl in zip(rows, eff, ledger, sells)],   # 日期、评分、红利低波100、执行用分数、当天买、攒着、当天减仓比例
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{last['date']} 评分 {last['score']:.2f}（{name}），回测 {len(rows)} 天")
