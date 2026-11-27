"""国家队场景 + 短线（实验）：只作提醒，不改任何倍数和买卖规则。

一、大方向（看大额买卖，一波一波地看）
  集中段：7 个指数近 20 日净买入（卖出）≥ 沪深300 流通市值 2‰ 算开始，回到 2‰ 以内满 10 天算结束。
  大额日：单日净买入（卖出）≥ 市值 0.3‰；相隔 ≤5 个交易日的大额日算同一小波。
  加码：这一小波累计超过前面任何一小波（买入：同一集中段里；卖出：前一小波结束不到 40 天，任何位置都算）。
  节奏：近 5 天日均 vs 这一段平均，<一半算放缓，≤0 算停手（连续 2 天才算）。
  场景（按顺序取第一个）：
    卖出加码（任何位置）       ⚠ 不追加，到卖出线就卖，宁可早一点
    高位 · 买（护盘）          ⚠ 别追，不追加，按卖出线卖
    低位 / 中间 · 买 · 加码    ⚠（中间位置普通）规则让加码时别犹豫，备用金可以分批用
    低位 / 中间 · 买 · 放缓    继续照规则买，别急着卖
    低位 / 中间 · 买 · 首波    小跟：照规则买，先不动备用金（这一段大额合计 <1‰ 算小额，不提醒）
    高位 · 卖 · 首波 / 放缓    不追加；放缓了也别松懈
    其他                       照规则买
二、短线（用手里的仓位做 T，C 类基金最合适）
  加：沪深300 5 天跌 ≥2.5% + 当天国家队净买入 ≥ 市值 0.1‰ + 当天两市成交额 ≥ 前 20 天平均（不缩量）
      + 不在高位、不在"卖出加码" → 第二天 15:00 前加一点（≤ 仓位 5%）
  卖：加完第 5 个交易日卖回同样多；中途收盘涨 ≥3% 就第二天卖回。
回测都从 2023 年起（之前没有申赎数据）。
"""
import bisect
import csv
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ntfstage.json")
BAND, BIG, SMALL = 2.0, 0.3, 0.1          # ‰
SCEN = {  # key: (名称, 怎么做, 邮件级别)
    "sell_up": ("卖出加码", "⚠ 不追加，各板块到卖出线就卖，宁可早一点；常比顶部早几周", "重点"),
    "hi_buy": ("高位 · 买（护盘）", "⚠ 别追：不追加，按卖出线卖；高位护盘之后多数还要跌", "重点"),
    "buy_up": ("买 · 加码（一波比一波多）", "⚠ 跟着买：规则让加码时别犹豫，备用金可以分批用", "重点"),
    "buy_slow": ("买 · 放缓 / 减弱", "继续照规则买，别急着卖；买到后半段常常快涨了", "普通"),
    "buy_first": ("买 · 首波大额", "小跟：照规则买，先不动备用金；第一波之后常常还要跌", "普通"),
    "buy_small": ("买 · 小额", "不是大方向，照规则买", None),
    "sell_first": ("高位 · 卖 · 首波", "留意：不追加", "普通"),
    "sell_slow": ("高位 · 卖 · 放缓", "仍然不追加，别以为卖完了就安全", "普通"),
    "none": ("没有集中买卖", "照规则买", None),
}
LOC = ["低位", "低位", "中间", "高位", "高位"]


def _load(n):
    with open(os.path.join(ROOT, "data", n), encoding="utf-8") as fh:
        return json.load(fh)


def _amt():
    p = os.path.join(ROOT, "data", "raw", "mkt_amt.csv")
    out = {}
    try:
        with open(p, encoding="utf-8") as fh:
            for r in csv.reader(fh):
                if r and r[0][:2] == "20" and r[1] not in ("", "nan"):
                    out[r[0]] = float(r[1])
    except OSError:
        pass
    return out


def run():
    N = _load("ntf.json")
    G, S = N["gflow"], N["series"]
    L = len(G["v"][G["names"][0]])
    F = [sum(G["v"][g][k] or 0 for g in G["names"]) for k in range(L)]
    SS = S[-L:]
    D, P, cap = [r[0] for r in SS], [r[4] for r in SS], [r[6] if len(r) > 6 else None for r in SS]
    last_cap = next((c for c in reversed(cap) if c), None)
    cap = [c or last_cap for c in cap]
    x = [F[k] / cap[k] * 1000 for k in range(L)]                       # 每天占市值 ‰
    r20 = [sum(x[max(0, k - 19):k + 1]) for k in range(L)]             # 近 20 天 ‰（按当天市值近似）
    TT = {t[0]: t[1] for t in _load("temp.json")["series"]}
    zk = sorted(TT)

    def zone(d):
        j = bisect.bisect_right(zk, d) - 1
        return TT[zk[j]] if j >= 0 else 2
    A = _amt()
    ak = sorted(A)

    def vr(d):   # 当天成交额 ÷ 前 20 天平均
        j = bisect.bisect_left(ak, d)
        if j >= len(ak) or ak[j] != d or j < 20:
            return None
        return A[d] / (sum(A[ak[t]] for t in range(j - 20, j)) / 20)

    # ---- 集中段（±2‰，回到 2‰ 以内满 10 天才算结束）
    seg = [0] * L          # 当天属于哪个方向的集中段
    seg_a = [None] * L     # 这一段从哪天开始（第一次越过 2‰）
    cur, out_n, a = 0, 0, None
    for k in range(L):
        s = 1 if r20[k] >= BAND else -1 if r20[k] <= -BAND else 0
        if s and s != cur:
            cur, a, out_n = s, k, 0
        elif cur and s == cur:
            out_n = 0
        elif cur:
            out_n += 1
            if out_n >= 10:
                cur, a = 0, None
        seg[k], seg_a[k] = cur, a

    # ---- 小波（大额日相隔 ≤5 天），按方向分开
    def waves(sg):
        days = [k for k in range(L) if x[k] * sg >= BIG]
        cl = []
        for k in days:
            if cl and k - cl[-1][-1] <= 5:
                cl[-1].append(k)
            else:
                cl.append([k])
        return cl
    W = {1: waves(1), -1: waves(-1)}

    def wave_info(sg, k, a0):
        """截至第 k 天：这一段里的小波（只算到 k），当前小波是否加码（累计超过之前任何一小波）"""
        cls = [[d for d in c if d <= k] for c in W[sg]]
        cls = [c for c in cls if c and c[-1] >= a0]
        out, mx, up_day = [], 0, None
        for j, c in enumerate(cls):
            acc, up = 0, None
            for d in range(c[0], c[-1] + 1):
                acc += x[d] * sg
                if j and up is None and acc > mx:
                    up = d
            out.append({"from": D[c[0]], "to": D[c[-1]], "days": len(c), "sum": round(acc, 2),
                        "tag": "首波" if j == 0 else "加码" if up is not None else "减弱", "_c": c, "_up": up})
            mx = max(mx, acc)
        return out

    def pace(k, sg, a0):
        s0 = max(0, a0 - 19)
        seg_avg = sum(x[s0:k + 1]) / (k + 1 - s0)
        l5 = sum(x[max(0, k - 4):k + 1]) / 5
        if l5 * sg >= seg_avg * sg * 1.2:
            return "加码", l5
        if l5 * sg >= seg_avg * sg * 0.5:
            return "差不多", l5
        return ("放缓" if l5 * sg > 0 else "停手"), l5

    # 卖出加码（任何位置）：当前（或 20 天内结束的）卖出小波累计超过前一小波，且前一小波结束不到 40 天
    def sell_up(k):
        cls = [[d for d in c if d <= k] for c in W[-1]]
        cls = [c for c in cls if c]
        for j in range(len(cls) - 1, 0, -1):
            c, pc_ = cls[j], cls[j - 1]
            if k - c[-1] > 20:
                break
            if c[0] - pc_[-1] > 40:
                continue
            prev = -sum(x[d] for d in range(pc_[0], pc_[-1] + 1))
            acc = 0
            for d in range(c[0], c[-1] + 1):
                acc -= x[d]
                if acc > prev:
                    return D[d], round(acc, 2), round(prev, 2)
            return None
        return None

    def scen(k):
        z = zone(D[k])
        su = sell_up(k)
        if su:
            return "sell_up", {"since": su[0], "now": su[1], "prev": su[2]}
        sg, a0 = seg[k], seg_a[k]
        if not sg:
            return "none", {}
        wi = wave_info(sg, k, max(0, a0 - 19))
        p1, _ = pace(k, sg, a0)
        p0, _ = pace(k - 1, sg, a0) if k - 1 >= a0 else (p1, 0)
        slow = p1 in ("放缓", "停手") and p0 in ("放缓", "停手")
        if sg > 0:
            if z >= 3:
                return "hi_buy", {}
            tot = sum(w["sum"] for w in wi)
            if tot < 1:
                return "buy_small", {}
            lw = wi[-1] if wi else None
            if lw and lw["tag"] == "加码" and k - lw["_c"][-1] <= 5 and lw["_up"] is not None:
                return "buy_up", {}
            done = lw and k - lw["_c"][-1] > 5            # 最近一小波已经结束
            if slow or (len(wi) > 1 and done):
                return "buy_slow", {}
            if len(wi) > 1:                              # 新一小波还在进行、还没超过之前：先保持原来的场景，免得来回发
                pk = SC[k - 1][0] if SC[k - 1] else None
                return (pk if pk in ("buy_first", "buy_slow", "buy_up") else "buy_first"), {}
            return "buy_first", {}
        if z >= 3:
            lw = wi[-1] if wi else None
            done = lw and k - lw["_c"][-1] > 5
            return ("sell_slow" if slow or (len(wi) > 1 and done) else "sell_first"), {}
        return "none", {}

    start = 25
    SC = [None] * L
    for k in range(start, L):
        SC[k] = scen(k)

    def fw(k, h):
        return round((P[k + h] / P[k] - 1) * 100, 1) if k + h < L else None
    # 场景换了的那天就是一个节点；同一场景 10 天内反复进出只算一次
    events, last_key, last_at = [], None, {}
    for k in range(start, L):
        key = SC[k][0]
        if key != last_key:
            if SCEN[key][2] and k - last_at.get(key, -99) > 10:
                events.append({"date": D[k], "key": key, "name": SCEN[key][0], "loc": LOC[zone(D[k])], "level": SCEN[key][2],
                               "hs300": round(P[k]), "f20": fw(k, 20), "f60": fw(k, 60), "f120": fw(k, 120)})
            last_at[key] = k
            last_key = key
    stats = {}
    for key in SCEN:
        ev = [e for e in events if e["key"] == key]
        o = {"n": len(ev)}
        for h in ("f20", "f60", "f120"):
            r = [e[h] for e in ev if e[h] is not None]
            o[h] = {"avg": round(sum(r) / len(r), 1), "up": sum(v > 0 for v in r), "n": len(r)} if r else None
        stats[key] = o

    # ---- 短线
    def t_sig(k):
        if k < 5:
            return False
        v = vr(D[k])
        return (P[k] / P[k - 5] - 1) * 100 <= -2.5 and x[k] >= SMALL and v is not None and v >= 1.0 \
            and zone(D[k]) < 3 and SC[k] and SC[k][0] != "sell_up"
    trades, k, hold = [], start, None
    while k < L:
        if hold is None:
            if t_sig(k):
                hold = {"sig": D[k], "b": k + 1}
                k += 1
                continue
            k += 1
            continue
        b = hold["b"]
        if b >= L:
            break
        if k > b and (k - b >= 4 or P[k] / P[b] - 1 >= 0.03):   # 第 k 天收盘发现该卖了 → 第 k+1 天卖回
            e = k + 1
            if e >= L:
                break
            trades.append({"sig": hold["sig"], "buy": D[b], "sell": D[e], "ret": round((P[e] / P[b] - 1) * 100, 2)})
            hold = None
            k = e
            continue
        k += 1
    i = L - 1
    if hold is None and t_sig(i):
        sstate, sact = f"加仓|{D[i]}", "明天 15:00 前用手里的仓位加一点（不超过仓位 5%，C 类基金最好），加完第 5 个交易日卖回同样多"
    elif hold is not None and hold["b"] <= i and (i - hold["b"] >= 4 or P[i] / P[hold["b"]] - 1 >= 0.03):
        sstate, sact = f"卖回|{D[hold['b']]}", f"明天 15:00 前卖回 {D[hold['b']]} 加的那部分（沪深300 这几天 {(P[i] / P[hold['b']] - 1) * 100:+.1f}%）"
    elif hold is not None:
        sstate, sact = f"持有|{D[hold['b']] if hold['b'] < L else '明天'}", "拿着，到第 5 个交易日或涨 3% 再卖回"
    else:
        sstate, sact = "无", "没有短线信号"
    r = [t["ret"] for t in trades]
    sstats = {"n": len(r), "avg": round(sum(r) / len(r), 2) if r else None, "win": sum(v > 0 for v in r),
              "best": max(r) if r else None, "worst": min(r) if r else None}

    # ---- 最新一天的说明
    key, info = SC[i]
    sg, a0 = seg[i], seg_a[i]
    stage = None
    if sg:
        s0 = max(0, a0 - 19)
        wi = wave_info(sg, i, s0)
        p1, l5 = pace(i, sg, a0)
        tot = sum(x[s0:i + 1])
        stage = {"dir": "买" if sg > 0 else "卖", "from": D[s0], "days": i - s0 + 1, "sum_pm": round(tot, 1),
                 "sum_yi": round(sum(F[s0:i + 1])), "big_days": sum(1 for k in range(s0, i + 1) if x[k] * sg >= BIG),
                 "big_yi": round(cap[i] * BIG / 1000), "pace": p1, "l5_yi": round(l5 * cap[i] / 1000),
                 "hs_from": round(P[s0]), "hs_to": round(P[i]), "hs_chg": round((P[i] / P[s0] - 1) * 100, 1),
                 "waves": [{k_: v for k_, v in w.items() if not k_.startswith("_")} for w in wi]}
        sizes = []   # 和 2023 年以来各段比大小（按累计 ‰）
        k = 0
        while k < L:
            if seg[k] == sg:
                j = k
                while j + 1 < L and seg[j + 1] == sg and seg_a[j + 1] == seg_a[k]:
                    j += 1
                sizes.append(abs(sum(x[max(0, seg_a[k] - 19):j + 1])))
                k = j + 1
            else:
                k += 1
        stage["rank"] = sorted(sizes, reverse=True).index(abs(tot)) + 1 if abs(tot) in sizes else None
        stage["n_seg"] = len(sizes)
    name, act, lvl = SCEN[key]
    zi = zone(D[i])
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": D[i], "key": key, "name": name, "loc": LOC[zi], "act": act, "level": lvl, "info": info,
                   "stage": stage, "x": round(x[i], 2), "r20": round(r20[i], 2), "vr": round(vr(D[i]) or 0, 2),
                   "short": {"state": sstate, "act": sact, "hold": hold and {"sig": hold["sig"], "buy": D[hold["b"]] if hold["b"] < L else None}}},
        "scen": {k_: {"name": v[0], "act": v[1], "level": v[2]} for k_, v in SCEN.items()},
        "events": events, "stats": stats,
        "short": {"trades": trades, "stats": sstats},
        "rule": {"band": BAND, "big": BIG, "small": SMALL},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{D[i]} {LOC[zi]} · {name}；短线 {sstate}；节点 {len(events)} 个，短线 {len(trades)} 次")
    return data


if __name__ == "__main__":
    run()
