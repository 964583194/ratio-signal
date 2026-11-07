#!/usr/bin/env python3
"""
拉取 创业板50(399673) 与 红利低波100(930955) 日线收盘价，
计算 比值 = 创业板50 ÷ 红利低波100，并生成统计、周定投回测，写入 data/ratio.json。

只用 Python 标准库，GitHub Actions 里直接运行即可。

本地手动数据：设置环境变量 CYB_CSV / HL_CSV 指向两列 CSV（date,close），
会跳过联网，直接用本地文件计算。
"""
import csv
import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ratio.json")

START = "20160923"   # 与原作者口径一致：2016-09-23 起
LO, HI = 0.16, 0.28  # 两条操作线
WEEKLY = 1000        # 每周定投额（元）
FEE = 0.0005         # 买入费率
CASH_YIELD = 0.015   # 现金池年化（货基）
DIV_CYB = 0.006      # 创业板50 股息率假设
DIV_HL = 0.05        # 红利低波100 股息率假设（价格指数不含分红，按年化加回）

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


# ---------------------------------------------------------------- 数据获取
def get_json(url, referer):
    req = urllib.request.Request(url, headers={**HEADERS, "Referer": referer})
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise last


def from_eastmoney(secid):
    """东方财富日K：0.399673 = 创业板50，2.930955 = 红利低波100"""
    q = urllib.parse.urlencode({
        "secid": secid, "fields1": "f1,f2,f3", "fields2": "f51,f52,f53",
        "klt": "101", "fqt": "0", "beg": "20140101", "end": "20500101",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    })
    j = get_json("https://push2his.eastmoney.com/api/qt/stock/kline/get?" + q,
                 "https://quote.eastmoney.com/")
    out = {}
    for line in (j.get("data") or {}).get("klines") or []:
        p = line.split(",")
        out[p[0]] = float(p[2])
    return out


def from_tencent(symbol):
    """腾讯日线，按年分段取，作为东方财富的备用源"""
    out = {}
    for y in range(2014, dt.date.today().year + 1):
        url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
               f"{symbol},day,{y}-01-01,{y}-12-31,400,")
        j = get_json(url, "https://gu.qq.com/")
        node = (j.get("data") or {}).get(symbol) or {}
        for row in node.get("day") or node.get("qfqday") or []:
            out[row[0]] = float(row[2])
    return out


def from_csindex(code):
    """中证指数官网日线（930955 官方口径）"""
    end = dt.date.today().strftime("%Y%m%d")
    url = ("https://www.csindex.com.cn/csindex-home/perf/index-perf"
           f"?indexCode={code}&startDate={START}&endDate={end}")
    j = get_json(url, "https://www.csindex.com.cn/")
    out = {}
    for row in j.get("data") or []:
        d = str(row["tradeDate"])
        out[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = float(row["close"])
    return out


def from_csv(path):
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if not row or not row[0][:1].isdigit():
                continue
            d = row[0].strip().replace("/", "-")
            if len(d) == 8:
                d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            out[d] = float(row[1])
    return out


def fetch(name, tries):
    errors = []
    for label, fn in tries:
        try:
            data = fn()
            if len(data) > 500:
                print(f"{name}: {label} 取到 {len(data)} 天")
                return data, label
            errors.append(f"{label}: 只有 {len(data)} 天")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: {e}")
    raise SystemExit(f"{name} 取数失败 -> " + " | ".join(errors))


# ---------------------------------------------------------------- 计算工具
def pct(sorted_vals, q):
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def xirr(cashflows):
    """cashflows: [(date, amount)]，投入为负，期末市值为正"""
    d0 = cashflows[0][0]

    def npv(r):
        return sum(a / (1 + r) ** ((d - d0).days / 365.0) for d, a in cashflows)

    lo, hi = -0.99, 5.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def backtest(dates, cyb, hl, ratio, mode, lo=LO, hi=HI):
    """
    每周第一个交易日定投 WEEKLY 元。
    mode: rot 轮动(中间区进现金池，进低/高区时一次性回补) | cyb | hl | mix
    返回 xirr、最大回撤(剔除申购的时间加权净值)、期末市值、累计投入、低/中/高周数
    """
    vc = vh = pool = 0.0
    nav, peak, mdd = 1.0, 1.0, 0.0
    cfs, invested = [], 0.0
    weeks = {"l": 0, "m": 0, "h": 0}
    last_week = None
    prev_total = 0.0
    for i, d in enumerate(dates):
        if i > 0:
            vc *= cyb[i] / cyb[i - 1] * (1 + DIV_CYB / 252)
            vh *= hl[i] / hl[i - 1] * (1 + DIV_HL / 252)
            pool *= 1 + CASH_YIELD / 252
        before = vc + vh + pool
        if prev_total > 0:
            nav *= before / prev_total
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
        wk = d.isocalendar()[:2]
        if wk != last_week:
            last_week = wk
            invested += WEEKLY
            cfs.append((d, -WEEKLY))
            r = ratio[i]
            z = "l" if r < lo else ("h" if r >= hi else "m")
            weeks[z] += 1
            if mode == "cyb":
                vc += WEEKLY * (1 - FEE)
            elif mode == "hl":
                vh += WEEKLY * (1 - FEE)
            elif mode == "mix":
                vc += WEEKLY / 2 * (1 - FEE)
                vh += WEEKLY / 2 * (1 - FEE)
            else:
                pool += WEEKLY
                if z == "l":
                    vc += pool * (1 - FEE)
                    pool = 0.0
                elif z == "h":
                    vh += pool * (1 - FEE)
                    pool = 0.0
        prev_total = vc + vh + pool
    final = vc + vh + pool
    cfs.append((dates[-1], final))
    x = xirr(cfs)
    return {
        "xirr": round(x, 4) if x is not None else None,
        "mdd": round(mdd, 4),
        "final": round(final),
        "invested": round(invested),
        "pool": round(pool),
        "weeks": weeks,
    }


# ---------------------------------------------------------------- 主流程
def main():
    if os.environ.get("CYB_CSV") and os.environ.get("HL_CSV"):
        cyb_raw, cyb_src = from_csv(os.environ["CYB_CSV"]), "本地CSV"
        hl_raw, hl_src = from_csv(os.environ["HL_CSV"]), "本地CSV"
    else:
        cyb_raw, cyb_src = fetch("创业板50", [
            ("东方财富", lambda: from_eastmoney("0.399673")),
            ("腾讯", lambda: from_tencent("sz399673")),
        ])
        hl_raw, hl_src = fetch("红利低波100", [
            ("中证指数官网", lambda: from_csindex("930955")),
            ("东方财富", lambda: from_eastmoney("2.930955")),
        ])

    common = sorted(set(cyb_raw) & set(hl_raw))
    common = [d for d in common if d >= f"{START[:4]}-{START[4:6]}-{START[6:]}"]
    if len(common) < 500:
        raise SystemExit(f"两个指数重合的交易日太少：{len(common)}")

    dates = [dt.date.fromisoformat(d) for d in common]
    cyb = [cyb_raw[d] for d in common]
    hl = [hl_raw[d] for d in common]
    ratio = [c / h for c, h in zip(cyb, hl)]

    s = sorted(ratio)
    n = len(ratio)
    i_min = min(range(n), key=lambda i: ratio[i])
    i_max = max(range(n), key=lambda i: ratio[i])
    recent = ratio[-1500:]
    now = ratio[-1]
    zone_of = lambda r: "l" if r < LO else ("h" if r >= HI else "m")  # noqa: E731

    stats = {
        "days": n,
        "start": common[0],
        "min": round(ratio[i_min], 4), "min_date": common[i_min],
        "max": round(ratio[i_max], 4), "max_date": common[i_max],
        "mean": round(statistics.fmean(ratio), 4),
        "median": round(statistics.median(ratio), 4),
        "std": round(statistics.pstdev(ratio), 4),
        "p10": round(pct(s, .10), 4), "p25": round(pct(s, .25), 4),
        "p75": round(pct(s, .75), 4), "p90": round(pct(s, .90), 4),
        "mean_1500": round(statistics.fmean(recent), 4),
        "pctile_1500": round(sum(r < now for r in recent) / len(recent), 4),
        "pctile_all": round(sum(r < now for r in ratio) / n, 4),
        "share": {z: round(sum(zone_of(r) == z for r in ratio) / n, 4) for z in "lmh"},
    }

    bt = {m: backtest(dates, cyb, hl, ratio, m) for m in ("rot", "cyb", "hl", "mix")}
    grid_lo = [0.14, 0.15, 0.16, 0.17, 0.18]
    grid_hi = [0.26, 0.28, 0.30, 0.32]
    grid = [[backtest(dates, cyb, hl, ratio, "rot", a, b)["xirr"] for b in grid_hi]
            for a in grid_lo]

    # 每周首个交易日的信号，最近 26 周
    weekly, seen = [], set()
    for i, d in enumerate(dates):
        wk = d.isocalendar()[:2]
        if wk not in seen:
            seen.add(wk)
            weekly.append([common[i], round(ratio[i], 4), zone_of(ratio[i])])

    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "sources": {"cyb": cyb_src, "hl": hl_src},
        "params": {"lo": LO, "hi": HI, "weekly": WEEKLY, "fee": FEE, "cash": CASH_YIELD,
                   "div_cyb": DIV_CYB, "div_hl": DIV_HL},
        "latest": {"date": common[-1], "cyb": cyb[-1], "hl": hl[-1],
                   "ratio": round(now, 4), "zone": zone_of(now),
                   "prev_ratio": round(ratio[-2], 4)},
        "stats": stats,
        "backtest": bt,
        "grid": {"lo": grid_lo, "hi": grid_hi, "xirr": grid},
        "weekly": weekly[-26:],
        "series": [[d, round(r, 4)] for d, r in zip(common, ratio)],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{common[-1]} 比值 {now:.4f}，共 {n} 天")

    # 红利低波100 每日打分：失败时保留上一次的 dividend.json，不影响比值数据
    if not os.environ.get("CYB_CSV"):
        try:
            import dividend
            dividend.run(cyb_raw)
        except Exception as e:  # noqa: BLE001
            print(f"红利打分更新失败，保留旧数据：{e}")


if __name__ == "__main__":
    sys.exit(main())
