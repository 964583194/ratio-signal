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
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "dividend.json")

FETCH_START = "20130101"
BASE = 200            # 每个交易日基数（元）
FEE = 0.0005          # 买卖费率
CASH = 0.017          # 现金池 / 卖出池年化
W = {"val": .15, "tech": .50, "spread": .25, "style": .10}
TIERS = [(18, 5, "加码"), (16, 4, "加码"), (14, 3, "加码"), (12, 2, "多买 · 买回"),
         (10, 1, "正常"), (8, .5, "少买")]
SELLS = [(6, .25), (4, 1 / 3), (2, .5)]
WARMUP = 250          # 分位至少需要的历史交易日

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


def get_json(url, referer):
    req = urllib.request.Request(url, headers={**HEADERS, "Referer": referer})
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise last


def csindex(code):
    end = dt.date.today().strftime("%Y%m%d")
    url = ("https://www.csindex.com.cn/csindex-home/perf/index-perf"
           f"?indexCode={code}&startDate={FETCH_START}&endDate={end}")
    rows = get_json(url, "https://www.csindex.com.cn/").get("data") or []
    out = {}
    for r in rows:
        d = str(r["tradeDate"])
        if r.get("close") is None:
            continue
        out[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = (float(r["close"]),
                                             float(r["peg"]) if r.get("peg") else None)
    return out


def cgb10():
    out, page = {}, 1
    while page < 40:
        q = urllib.parse.urlencode({
            "reportName": "RPTA_WEB_TREASURYYIELD", "columns": "SOLAR_DATE,EMM00166466",
            "sortColumns": "SOLAR_DATE", "sortTypes": "-1", "pageNumber": page,
            "pageSize": "500", "source": "WEB", "client": "WEB"})
        j = get_json("https://datacenter.eastmoney.com/api/data/v1/get?" + q,
                     "https://data.eastmoney.com/")
        data = (j.get("result") or {}).get("data") or []
        if not data:
            break
        for r in data:
            if r.get("EMM00166466") is not None:
                out[r["SOLAR_DATE"][:10]] = float(r["EMM00166466"])
        if data[-1]["SOLAR_DATE"][:4] < FETCH_START[:4]:
            break
        page += 1
    return out


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


def simulate(dates, tr, scores, mode):
    """预算中性：外部每天投入 BASE，少投的进现金池；多投从现金池出，池子不够就投池子里有的。"""
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
        else:
            s = scores[i]
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
            amt = min(BASE * mult, pool)
            hold += amt * (1 - FEE)
            pool -= amt
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
    px = csindex("930955")
    tr = csindex("H20955")
    y10 = cgb10()
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

    bt_dates = [dobj[r["i"]] for r in rows]
    bt_tr = [tri[r["i"]] for r in rows]
    bt_sc = [r["score"] for r in rows]
    plain = simulate(bt_dates, bt_tr, bt_sc, "plain")
    scored = simulate(bt_dates, bt_tr, bt_sc, "score")

    last = rows[-1]
    mult, name = tier(last["score"])
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
            "sub": {"val": r1(last["val"]), "tech": r1(last["tech"]),
                    "spread": r1(last["spread"]), "style": r1(last["style"])},
            "rsi": round(last["rsi"], 1), "pb": round(last["pb"], 2),
            "pe_dear": round(last["pe_dear"], 3), "sty_pct": round(last["sty_pct"], 3),
            "score_pctile": round(bisect.bisect_left(scores_sorted, last["score"]) / len(bt_sc), 3),
        },
        "stats": {"days": len(rows), "start": rows[0]["date"],
                  "max": round(hi_r["score"], 1), "max_date": hi_r["date"],
                  "min": round(lo_r["score"], 1), "min_date": lo_r["date"]},
        "backtest": {"plain": plain, "score": scored},
        "personality": {
            "hl": {"ac20": round(autocorr20(close), 3), "mdd": round(max_dd(close), 3)},
            "cyb": {"ac20": round(autocorr20(cyb_close), 3), "mdd": round(max_dd(cyb_close), 3)},
            "since": dates[0],
        },
        "series": [[r["date"], round(r["score"], 2)] for r in rows],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{last['date']} 评分 {last['score']:.2f}（{name}），回测 {len(rows)} 天")
