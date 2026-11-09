"""
轮动“平衡版”规则（创业板50 / 科创50 ÷ 红利低波100），回测与当前信号共用同一套模拟。

阈值：每年 1 月、7 月用过去 10 年（不足 10 年用全部历史）信号值的分位重算一次。
  中位数(50%) 以下每周买；25% 以下加大买；13% 以下翻倍买；89% / 94% / 98% 为三档卖出线。
买入：每周集中一次。进入某个区间要连续 3 个交易日在线下才算。
  暂停区（中位数以上）：每周定投款买红利低波100（闲钱放红利）。
  每周买入区：每周定投款买成长端。
  加大买入区 / 翻倍买入区：另外把红利仓位的 12% / 23% 转成成长端（相当于每天 1/40、1/20，按周集中）。
卖出（卖出的钱都转红利）：
  趋势确认：信号值过某档卖出线后，跌破信号 20 日均线时才卖这一档（1/3、再一半、全部）。
  目标止盈：成长端持仓盈利 ≥50% 卖 1/3，≥100% 再卖一半（信号值在中位数以上才执行）。
  红利打分联动：信号值在中位数以上且红利打分 ≥14（红利很便宜）时，卖 1/4 成长端。
  每段行情每条只触发一次，信号值回到中位数以下重新计数。
极低值：跌破翻倍线先把红利仓位的 1/3 转入成长端，之后每再跌 5% 转一批，共 3 批；
  上一批之后 4 周没有更低，就把剩下的全部转入。
成交：用前一交易日收盘的信号，在当天收盘价成交（不用未来数据）。
"""
import bisect
import datetime as dt

PCT = dict(mid=50, day=25, dbl=13, s1=89, s2=94, s3=98)
WIN = 3652          # 10 年
MIN_HIST = 244      # 至少 1 年历史才开始用分位
WEEKLY = 1000
FEE = 0.0005
SW = 0.001          # 红利 ⇄ 成长端 转换：卖出 + 买入两次费用
DIV_SCORE = 14
TIERS = (("s1", 1 / 3, "卖出 1/3"), ("s2", 0.5, "再卖剩下的一半"), ("s3", 1.0, "全部卖出"))
ZONE_NAME = {"dbl": "翻倍买入区", "day": "加大买入区", "wk": "每周买入区", "pause": "暂停区"}


def pctl(sorted_vals, q):
    k = (len(sorted_vals) - 1) * q / 100
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def thresholds(dates, r):
    """返回 (每天适用的阈值列表, 调整记录[(生效日, 阈值)])，只用生效日之前的数据。"""
    ords = [d.toordinal() for d in dates]
    th, hist, key, cur = [], [], None, None
    for i, d in enumerate(dates):
        k = (d.year, d.month >= 7)
        if k != key:
            key = k
            j = bisect.bisect_left(ords, d.toordinal() - WIN)
            w = sorted(r[j:i]) if i - j >= MIN_HIST else None
            cur = {n: round(pctl(w, p), 4) for n, p in PCT.items()} if w else None
            if cur:
                hist.append((d.isoformat(), cur, round((d - dates[j]).days / 365.25, 1)))
        th.append(cur)
    return th, hist


def ma(vals, n):
    out, s = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def zone_of(below):
    """below: 连续在线下的天数；连续 3 天才算进入"""
    for n in ("dbl", "day", "mid"):
        if below.get(n, 0) >= 3:
            return {"mid": "wk"}.get(n, n)
    return "pause"


def xirr(cfs):
    d0 = cfs[0][0]
    f = lambda x: sum(a / (1 + x) ** ((d - d0).days / 365) for d, a in cfs)  # noqa: E731
    lo, hi = -0.99, 5.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(120):
        m = (lo + hi) / 2
        if f(lo) * f(m) <= 0:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def simulate(dates, g, hl, r, th, ma20, score, i0, div_g, g_name):
    """g 成长端价格，hl 红利低波100 全收益指数。返回 (回测结果, 期末状态, 每周记录, 交易记录)"""
    cy = pool = cost = 0.0
    nav = peak = 1.0
    mdd, prev = 0.0, 0.0
    cfs, weeks, trades = [], [], []
    ep, below = set(), {}
    bk, bl, bt = 0, None, None
    wk = None
    nsell = 0
    for i in range(i0, len(dates)):
        d = dates[i]
        if i > i0:
            cy *= g[i] / g[i - 1] * (1 + div_g / 244)
            pool *= hl[i] / hl[i - 1]
        cur = cy + pool
        if prev > 0:
            nav *= cur / prev
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
        x, T = r[i - 1], th[i - 1]
        if T is None:
            prev = cy + pool
            continue
        for n in ("dbl", "day", "mid"):
            below[n] = below.get(n, 0) + 1 if x < T[n] else 0
        z = zone_of(below)
        acts = []

        def to_g(amt, why):
            nonlocal pool, cy, cost
            amt = min(amt, pool)
            if amt > 1:
                pool -= amt
                cy += amt * (1 - SW)
                cost += amt
                acts.append(why)
                trades.append([d.isoformat(), why, round(amt)])

        def sell(frac, why):
            nonlocal pool, cy, cost, nsell
            if cy < 1:
                return
            s = cy * frac
            cy -= s
            cost *= 1 - frac
            pool += s * (1 - SW)
            nsell += 1
            acts.append(why)
            trades.append([d.isoformat(), why, -round(s)])

        if x < T["mid"]:
            ep -= {"s1", "s2", "s3", "as1", "as2", "as3", "tp1", "tp2", "dv"}
        new_week = d.isocalendar()[:2] != wk
        if new_week:
            wk = d.isocalendar()[:2]
            cfs.append((d, -WEEKLY))
            pool += WEEKLY * (1 - FEE)       # 定投款先进红利，买入区再转成长端
            if z == "pause":
                acts.append(f"{WEEKLY} 元买红利")
            else:
                to_g(WEEKLY, f"{WEEKLY} 元买{g_name}")
                if z in ("day", "dbl"):
                    k = 1 - (1 - (1 / 20 if z == "dbl" else 1 / 40)) ** 5
                    to_g(pool * k, f"红利转{g_name} {k:.0%}")
        # 极低值分批转入
        if pool > 1:
            if bk == 0 and below.get("dbl", 0) >= 3:
                to_g(pool / 3, "极低值第1批")
                bk, bl, bt = 1, x, d
            elif 0 < bk < 3 and (x <= bl * 0.95 or (d - bt).days >= 28):
                last = (d - bt).days >= 28
                to_g(pool if last else pool / (3 - bk), "极低值剩余全部转入" if last else f"极低值第{bk + 1}批")
                bk = 3 if last else bk + 1
                bl = min(bl, x)
                bt = bt if last else d
        if x > T["mid"] and bk >= 3:
            bk = 0
        # 趋势确认卖出
        for k, f, txt in TIERS:
            if x >= T[k]:
                ep.add("a" + k)
            if "a" + k in ep and k not in ep and x < ma20[i - 1]:
                sell(f, "卖出档" + k[1] + "：" + txt)
                ep.add(k)
        if x > T["mid"] and cost > 1:
            gain = cy / cost - 1
            if gain >= 0.5 and "tp1" not in ep:
                sell(1 / 3, "止盈：盈利≥50% 卖 1/3")
                ep.add("tp1")
            if gain >= 1.0 and "tp2" not in ep:
                sell(0.5, "止盈：盈利≥100% 再卖一半")
                ep.add("tp2")
            sc = score.get(dates[i - 1].isoformat())
            if sc is not None and sc >= DIV_SCORE and "dv" not in ep:
                sell(0.25, "红利打分联动：卖 1/4")
                ep.add("dv")
        if new_week:
            weeks.append([d.isoformat(), round(x, 4), z, "；".join(acts)])
        elif acts and weeks:
            weeks[-1][3] += ("；" if weeks[-1][3] else "") + "；".join(acts)
        prev = cy + pool
    final = cy + pool
    cfs.append((dates[-1], final))
    x = xirr(cfs)
    res = {"xirr": round(x, 4) if x is not None else None, "mdd": round(mdd, 4), "final": round(final),
           "invested": WEEKLY * (len(cfs) - 1), "pool": round(pool), "sells": nsell,
           "g_share": round(cy / final, 3) if final else 0}
    state = {"ep": sorted(ep), "batch": bk, "batch_low": bl, "batch_date": bt.isoformat() if bt else None,
             "below": below, "gain": round(cy / cost - 1, 3) if cost > 1 else None}
    return res, state, weeks, trades


def latest_plan(dates, r, th, ma20, score, state, g_name):
    """按最新收盘信号，给出下一次操作。"""
    x, T = r[-1], th[-1]
    below = {n: (state["below"].get(n, 0) + 1 if x < T[n] else 0) for n in ("dbl", "day", "mid")}
    z = zone_of(below)
    ep = set(state["ep"])
    if x < T["mid"]:
        ep -= {"s1", "s2", "s3", "as1", "as2", "as3", "tp1", "tp2", "dv"}
    acts, warn = [], []
    if z == "pause":
        acts.append(f"本周定投款买红利低波100（暂停买{g_name}）")
    else:
        acts.append(f"本周定投款买{g_name}")
        if z in ("day", "dbl"):
            k = 1 - (1 - (1 / 20 if z == "dbl" else 1 / 40)) ** 5
            acts.append(f"另外把这部分的红利仓位转 {k:.0%} 到{g_name}")
    sell_now = []
    for k, f, txt in TIERS:
        armed = x >= T[k] or "a" + k in ep
        if armed and k not in ep:
            if x < ma20[-1]:
                sell_now.append(f"{txt}{g_name}转红利（第{k[1]}档）")
            else:
                warn.append(f"已过第{k[1]}档卖出线 {T[k]}，等信号值跌破 20 日均线 {ma20[-1]:.4f} 再卖")
    sc = score.get(dates[-1].isoformat()) if score else None
    if x > T["mid"] and sc is not None and sc >= DIV_SCORE and "dv" not in ep:
        sell_now.append(f"红利打分 {sc:.1f}（很便宜），卖 1/4 {g_name}转红利")
    bk = state["batch"]
    batch = None
    if 0 < bk < 3:
        batch = f"极低值转仓进行中：已转 {bk} 批，信号值跌到 {state['batch_low'] * 0.95:.4f} 转下一批，" \
                f"{(dt.date.fromisoformat(state['batch_date']) + dt.timedelta(days=28)).isoformat()} 前没有更低就全部转入"
    elif bk == 0 and below["dbl"] >= 3:
        batch = f"跌破翻倍线：把红利仓位的 1/3 转入{g_name}（第 1 批）"
    elif x < T["dbl"]:
        batch = f"跌破翻倍线 {below['dbl']} 天，连续 3 天后开始分批把红利转入{g_name}"
    code = "sell" if sell_now else ("armed" if warn else z)
    if z == "pause" and below["mid"] > 0:
        warn.append(f"已在中位数 {T['mid']} 以下 {below['mid']} 天，连续 3 天后开始每周买{g_name}")
    return {"zone": code, "zone_name": "卖出" if sell_now else ("卖出预警" if code == "armed" else ZONE_NAME[z]),
            "buy_zone": z, "actions": sell_now + ([batch] if batch else []) + acts, "warn": warn,
            "ma20": round(ma20[-1], 4), "score": sc, "below": below,
            "tp_rule": "自己的持仓盈利 ≥50% 卖 1/3、≥100% 再卖一半（信号值在中位数以上时）",
            "sold": [k for k in ("s1", "s2", "s3", "tp1", "tp2", "dv") if k in ep]}
