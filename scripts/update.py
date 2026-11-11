#!/usr/bin/env python3
"""
拉取 创业板50(399673) 与 红利低波100(930955) 日线收盘价，
计算 比值 = 创业板50 ÷ 红利低波100，并生成统计、周定投回测，写入 data/ratio.json。

只用 Python 标准库，GitHub Actions 里直接运行即可。

现行规则（平衡版）见 plan.py；这里保留旧版固定线轮动，只用作回测对比。
"""
import csv
import datetime as dt
import json
import os
import statistics
import sys

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ratio.json")

START = "20160923"   # 与原作者口径一致：2016-09-23 起
LO, HI = 0.16, 0.28  # 两条操作线
SELLS = ((0.32, 1 / 3), (0.36, 0.5), (0.40, 1.0))  # 高位分档卖出：比值≥阈值时把成长端持仓的该比例转到红利
KC_LO, KC_HI = 0.09, 0.15                         # 科创50 ÷ 红利低波100 的两条操作线
KC_SELLS = ((0.16, 1 / 3), (0.17, 0.5), (0.18, 1.0))
DIV_KC = 0.004
WEEKLY = 1000        # 每周定投额（元）
FEE = 0.0005         # 买入费率
CASH_YIELD = 0.015   # 现金池年化（货基）
DIV_CYB = 0.006      # 创业板50 股息率假设
DIV_HL = 0.038       # 红利低波100 股息率（全收益指数比价格指数年均多 3.8%），只用于旧版对比



# ---------------------------------------------------------------- 数据获取
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


def backtest(dates, cyb, hl, ratio, mode, lo=LO, hi=HI, sells=(), div_g=DIV_CYB):
    """
    每周第一个交易日定投 WEEKLY 元。cyb 为成长端指数（创业板50 或 科创50）。
    mode: rot 轮动(中间区进现金池，进低/高区时一次性回补) | cyb | hl | mix
    sells: 分档卖出 [(阈值, 比例)]，每段行情每档只触发一次，比值回到高区线以下重置
    返回 xirr、最大回撤(剔除申购的时间加权净值)、期末市值、累计投入、低/中/高周数
    """
    vc = vh = pool = 0.0
    nav, peak, mdd = 1.0, 1.0, 0.0
    cfs, invested = [], 0.0
    weeks = {"l": 0, "m": 0, "h": 0}
    last_week = None
    prev_total = 0.0
    hit = set()
    for i, d in enumerate(dates):
        if i > 0:
            vc *= cyb[i] / cyb[i - 1] * (1 + div_g / 252)
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
                if r < hi:
                    hit.clear()
                for th, frac in sells:
                    if r >= th and th not in hit and vc > 0:
                        amt = vc * frac
                        vc -= amt
                        vh += amt * (1 - FEE) ** 2
                        hit.add(th)
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


def build(g_raw, g_src, hl_raw, hl_src, out, lo, hi, sells, div_g, start, g_name, tr_raw, score):
    """生成一组比值轮动数据（成长端 ÷ 红利低波100）。现行规则见 plan.py（平衡版）；字段名沿用 cyb 表示成长端。"""
    import plan as PL
    allc = sorted(set(g_raw) & set(hl_raw) & set(tr_raw))
    D_all = [dt.date.fromisoformat(d) for d in allc]
    r_all = [g_raw[d] / hl_raw[d] for d in allc]
    th_all, th_hist = PL.thresholds(D_all, r_all)
    ma_all = PL.ma(r_all, 20)
    i0 = next(i for i, d in enumerate(allc) if d >= start and th_all[i] and ma_all[i - 1])
    common = allc[i0:]
    if len(common) < 300:
        raise SystemExit(f"两个指数重合的交易日太少：{len(common)}")
    dates = D_all[i0:]
    cyb = [g_raw[d] for d in common]
    hl = [hl_raw[d] for d in common]
    ratio = r_all[i0:]
    g_all = [g_raw[d] for d in allc]
    gm = PL.ma(g_all, 250)
    hot = HOT[0]
    res, state, weeks, trades = PL.simulate(D_all, g_all, [tr_raw[d] for d in allc],
                                            r_all, th_all, ma_all, score, i0, div_g, g_name, hot, gm)
    hot_now = hot(allc[-1])
    bear_now = gm[-1] is not None and g_all[-1] < gm[-1] and not hot_now
    plan = PL.latest_plan(D_all, r_all, th_all, ma_all, score, state, g_name, hot_now, bear_now, gm[-1] or 0)
    plan.update({"hot": hot_now, "bear": bear_now, "g_close": g_all[-1], "g_ma250": round(gm[-1] or 0, 2)})
    T = th_all[-1]

    s = sorted(ratio)
    n = len(ratio)
    i_min = min(range(n), key=lambda i: ratio[i])
    i_max = max(range(n), key=lambda i: ratio[i])
    recent = ratio[-1500:]
    now = ratio[-1]
    stats = {
        "days": n, "start": common[0],
        "min": round(ratio[i_min], 4), "min_date": common[i_min],
        "max": round(ratio[i_max], 4), "max_date": common[i_max],
        "mean": round(statistics.fmean(ratio), 4), "median": round(statistics.median(ratio), 4),
        "std": round(statistics.pstdev(ratio), 4),
        "p10": round(pct(s, .10), 4), "p25": round(pct(s, .25), 4),
        "p75": round(pct(s, .75), 4), "p90": round(pct(s, .90), 4),
        "mean_1500": round(statistics.fmean(recent), 4),
        "pctile_1500": round(sum(r < now for r in recent) / len(recent), 4),
        "pctile_all": round(sum(r < now for r in ratio) / n, 4),
    }
    kw = dict(lo=lo, hi=hi, div_g=div_g)
    bt = {"plan": res, "sell": backtest(dates, cyb, hl, ratio, "rot", sells=sells, **kw),
          "cyb": backtest(dates, cyb, hl, ratio, "cyb", **kw), "hl": backtest(dates, cyb, hl, ratio, "hl", **kw)}

    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "sources": {"cyb": g_src, "hl": hl_src},
        "params": {"th": T, "th_date": th_hist[-1][0], "th_years": th_hist[-1][2], "pct": PL.PCT,
                   "old": {"lo": lo, "hi": hi, "sells": [[a, round(b, 4)] for a, b in sells]},
                   "weekly": WEEKLY, "fee": FEE, "div_cyb": div_g},
        "latest": {"date": common[-1], "cyb": cyb[-1], "hl": hl[-1], "ratio": round(now, 4),
                   "prev_ratio": round(ratio[-2], 4), "zone": plan["zone"]},
        "plan": plan,
        "th_hist": [[d, t, y] for d, t, y in th_hist][-12:],
        "stats": stats,
        "backtest": bt,
        "trades": trades[-20:],
        "weekly": weeks[-60:],
        "series": [[d, round(r, 4)] for d, r in zip(common, ratio)],
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {out}：{common[-1]} 信号值 {now:.4f}（{plan['zone_name']}），平衡版回测年化 {res['xirr']}")


HOT = [lambda d: False]


def div_score():
    try:
        with open(os.path.join(ROOT, "data", "dividend.json"), encoding="utf-8") as f:
            return dict(json.load(f)["series"])
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- 主流程
def main():
    changed = S.refresh_all()
    outputs = ["market.json", "ratio.json", "kc.json", "dividend.json", "a500.json", "hs300.json", "ndx.json", "gold.json", "bond.json", "topsig.json", "temp.json", "myfunds.json", "goldmodel.json"]
    missing = [f for f in outputs if not os.path.exists(os.path.join(ROOT, "data", f))]
    if not changed and not missing and os.environ.get("FORCE") != "1":
        print("数据没有变化（非交易日或接口还没更新），跳过计算")
        S.write_health()
        return

    tr = lambda: S.get_series("hl100_tr")[0]  # noqa: E731
    import market as MK

    def mk():
        MK.run()
        HOT[0] = MK.hot_lookup(MK.pb_hot_series())
    jobs = [   # 红利打分、见底评分先算，轮动要用（破净率）；托底资金 → 见顶信号灯 → 市场温度 依次要用前一项的结果
        ("托底资金（国家队）", lambda: __import__("etf300").run()),
        ("见顶信号灯", lambda: __import__("topsig").run()),   # 要读 etf300.json
        ("见底评分", mk),
        ("市场温度", lambda: __import__("temp").run()),        # 要读 topsig.json
        ("红利打分", lambda: __import__("dividend").run(S.get_series("cyb50")[0])),
        ("创业板50 轮动", lambda: build(*S.get_series("cyb50"), *S.get_series("hl100"), OUT, LO, HI, SELLS, DIV_CYB,
                                       f"{START[:4]}-{START[4:6]}-{START[6:]}", "创业板50", tr(), div_score())),
        ("科创50 轮动", lambda: build(*S.get_series("kc50"), *S.get_series("hl100"),
                                     os.path.join(ROOT, "data", "kc.json"), KC_LO, KC_HI, KC_SELLS, DIV_KC,
                                     "2021-01-01", "科创50", tr(), div_score())),
        ("中证A500 / 沪深300 / 纳指100 / 黄金", lambda: __import__("value").run()),
        ("海外小仓位", lambda: __import__("overseas").run()),   # 要读 ndx.json，放在后面
        ("黄金分析", lambda: __import__("goldmodel").run()),   # 要读 gold.json
        ("我的基金", lambda: __import__("myfunds").run()),     # 要读 temp.json 和各页签结果，放最后
    ]
    for name, job in jobs:
        try:
            job()
        except BaseException as e:  # noqa: BLE001  某一项失败时保留它的旧数据，不影响其他项
            print(f"{name} 计算失败，保留旧数据：{e}")

    ok = S.write_health()
    print("数据源体检：" + ("正常" if ok else "有数据超过 12 天没更新，请检查 data/health.json"))


if __name__ == "__main__":
    sys.exit(main())
