"""综合信号（实验）：把几个已有指标联动起来，给一句"现在怎么做"。只作提醒，不改任何倍数和买卖规则。

五档（从上往下，先满足的算）：
  准备卖  市场温度在顶部，或 偏热 + 托底资金撤出
  别加钱  市场温度偏热，或 托底资金撤出（近 20 日份额 ≤ −15%），或 见顶灯 ≥2
  大胆买  市场温度在底部 / 偏冷，且（近 20 天出现过国家队急买，或 宽度、M1、信贷脉冲全部回升）
  放心买  市场温度在底部 / 偏冷
  照常买  其他
国家队急买：4 只沪深300 ETF 近 5 日净申购 ≥ 两市近 5 日成交额的 1%（2023 年起才有数据，之前只看方向）。
回测：各档之后 60 / 120 / 250 个交易日沪深300 的表现（2013 年起、2023 年起两段）。
"""
import bisect
import datetime as dt
import json
import os

import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "verdict.json")
LEVELS = ["大胆买", "放心买", "照常买", "别加钱", "准备卖"]
CLS = {"大胆买": "g2", "放心买": "g1", "照常买": "c0", "别加钱": "h1", "准备卖": "r1"}
ACT = {"大胆买": "按规则买；规则让加码时别犹豫，备用金可以用起来",
       "放心买": "按规则买；可能还要磨一段，备用金留足、分批用",
       "照常买": "按规则买，不用额外做什么",
       "别加钱": "按规则买，但不额外加钱，留意各板块的卖出信号",
       "准备卖": "不追加；各板块到卖出线就按规则卖"}
ZN = ["底部", "偏冷", "正常", "偏热", "顶部"]
RUSH = 0.01


def _load(n):
    with open(os.path.join(ROOT, "data", n), encoding="utf-8") as fh:
        return json.load(fh)


def level_of(z, out, top, low_plus):
    if z == 4 or (z == 3 and out):
        return "准备卖"
    if z == 3 or out or top >= 2:
        return "别加钱"
    if z <= 1:
        return "大胆买" if low_plus else "放心买"
    return "照常买"


def run():
    T = _load("temp.json")["series"]          # [日期, 区间 0~4, 沪深300, 见底灯, 见顶灯, 各灯, 方向]
    E = {x[0]: x[3] for x in _load("etf300.json")["series"]}
    NT = {x[0]: x[5] for x in _load("ntf.json")["series"] if len(x) > 5}
    try:
        mk = S.get_series("mkt_amt")[0]
    except Exception:  # noqa: BLE001
        mk = S.load_cache("mkt_amt")
    D, P, Z = [x[0] for x in T], [x[2] for x in T], [x[1] for x in T]
    n = len(D)
    ek = sorted(E)

    def shares(d):
        j = bisect.bisect_right(ek, d) - 1
        return E[ek[j]] if j >= 0 else None
    out, r5 = [False] * n, [None] * n
    for k in range(n):
        if k >= 20:
            a, b = shares(D[k]), shares(D[k - 20])
            out[k] = bool(a and b and a / b - 1 <= -0.15)
        if k >= 4 and all(d in NT for d in D[k - 4:k + 1]):
            a = sum(mk.get(d, 0) for d in D[k - 4:k + 1])
            r5[k] = sum(NT[d] for d in D[k - 4:k + 1]) / a if a else None
    rush = [x is not None and x >= RUSH for x in r5]
    rush20 = [any(rush[max(0, k - 19):k + 1]) for k in range(n)]
    dirup = [x[6] == "111" for x in T]
    L = [level_of(Z[k], out[k], T[k][4], rush20[k] or dirup[k]) for k in range(n)]

    def agg(idx):
        o = {"days": len(idx)}
        for h in (60, 120, 250):
            r = [P[k + h] / P[k] - 1 for k in idx if k + h < n]
            o[str(h)] = {"avg": round(sum(r) / len(r), 4), "up": round(sum(x > 0 for x in r) / len(r), 3), "n": len(r)} if r else None
        return o
    stats = {}
    for since in ("2013", "2023"):
        ks = [k for k in range(n) if D[k] >= since]
        stats[since] = {lv: agg([k for k in ks if L[k] == lv]) for lv in LEVELS}
        stats[since]["任意一天"] = agg(ks)
    chg = []
    for k in range(n):
        if not chg or chg[-1][1] != L[k]:
            chg.append([D[k], L[k]])
    i = n - 1
    lv = L[i]
    since = chg[-1][0]
    last = T[i]
    why = [
        {"name": "市场温度", "ok": Z[i] <= 1, "bad": Z[i] >= 3,
         "text": f"{ZN[Z[i]]}（见底灯 {last[3]} / 6，见顶灯 {last[4]} / 7）"},
        {"name": "国家队急买", "ok": rush20[i], "bad": False,
         "text": ("近 20 天出现过（" + next(D[k] for k in range(max(0, i - 19), i + 1) if rush[k]) + " 起）") if rush20[i]
         else f"近 20 天没有（现在近 5 日占成交额 {(r5[i] or 0) * 100:.2f}%，≥1% 算急买）"},
        {"name": "方向", "ok": dirup[i], "bad": False,
         "text": "宽度、M1、信贷脉冲全部回升" if dirup[i] else f"还没全部回升（{last[6].count('1')} / 3 回升）"},
        {"name": "托底资金撤出", "ok": False, "bad": out[i],
         "text": "国家队在撤（近 20 日份额 ≤ −15%）" if out[i] else "没有撤出"},
        {"name": "见顶灯", "ok": False, "bad": last[4] >= 2, "text": f"亮 {last[4]} 个（≥2 算偏热）"},
    ]
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": D[i], "level": lv, "cls": CLS[lv], "action": ACT[lv], "since": since, "why": why},
        "levels": LEVELS, "act": ACT, "cls": CLS, "stats": stats, "changes": chg[-12:],
        "series": [[D[k], LEVELS.index(L[k]), P[k]] for k in range(n)],
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{D[i]} {lv}（{since} 起）→ {ACT[lv]}")
    return data


if __name__ == "__main__":
    run()
