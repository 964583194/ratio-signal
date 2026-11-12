"""综合判断（实验）：各指标独立给“偏多 / 偏空 / 不表态”，再按票数综合。只作实验对比，不进规则。

六个指标（各自回测过方向，只在有用的一边投票）：
  见底灯     近 20 日最多亮 ≥2 个 → 偏多
  见顶灯     近 20 日最多亮 ≥2 个 → 偏空
  方向       宽度、M1、信贷脉冲全部回升 → 偏多（全部走弱之后并不差，不投空票）
  托底撤出   托底资金近 20 日份额 ≤ −15% → 偏空
  国家队加速 流入在加速 → 偏多（2023 年起；加速流出之后只是略弱，不投票）
  放量托底   近 20 个交易日出现过放量托底日 → 偏多（2023 年起）
综合：偏多票 − 偏空票 ≥2 积极、1 偏积极、0 照常、−1 偏谨慎、≤−2 谨慎。
对比“只看区间”：各档之后沪深300 的表现，以及按档调倍数（1.5 / 1.25 / 1 / 0.75 / 0.5）每周定投沪深300 的收益。
"""
import datetime as dt
import json
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "combo.json")
LEVELS = ["积极", "偏积极", "照常", "偏谨慎", "谨慎"]
MULT = {"积极": 1.5, "偏积极": 1.25, "照常": 1, "偏谨慎": 0.75, "谨慎": 0.5}
CLS = {"积极": "g2", "偏积极": "g1", "照常": "c0", "偏谨慎": "h1", "谨慎": "r1"}
ZL = {0: "积极", 1: "偏积极", 2: "照常", 3: "偏谨慎", 4: "谨慎"}
IND = [("见底灯", "近 20 日最多亮 ≥2 个 → 偏多"), ("见顶灯", "近 20 日最多亮 ≥2 个 → 偏空"),
       ("方向", "宽度、M1、信贷脉冲全部回升 → 偏多"), ("托底撤出", "托底资金近 20 日份额 ≤ −15% → 偏空"),
       ("国家队加速", "国家队流入在加速 → 偏多（2023 年起）"), ("放量托底", "近 20 日出现过放量托底日 → 偏多（2023 年起）")]
OLD = ["见底灯", "见顶灯", "方向", "托底撤出"]          # 2013 年起就有数据的四个


def _load(n):
    with open(os.path.join(ROOT, "data", n), encoding="utf-8") as fh:
        return json.load(fh)


def vote(x, keys):
    s = sum(x[k] for k in keys)
    return "积极" if s >= 2 else "偏积极" if s == 1 else "照常" if s == 0 else "偏谨慎" if s == -1 else "谨慎"


def run():
    T, E, N = _load("temp.json")["series"], _load("etf300.json")["series"], _load("ntf.json")
    chg = {r[0]: r[3] / E[i - 20][3] - 1 for i, r in enumerate(E) if i >= 20}
    nin = {r[0]: r[2] is not None and r[2] >= 90 for r in N["series"]}
    nd = [r[0] for r in N["series"]]
    vset = {v["date"] for v in N["vols"]}
    vnear = {d: any(x in vset for x in nd[max(0, i - 19):i + 1]) for i, d in enumerate(nd)}
    days, cl, n = [r[0] for r in T], [r[2] for r in T], len(T)
    b20 = [max(T[j][3] for j in range(max(0, i - 19), i + 1)) for i in range(n)]
    t20 = [max(T[j][4] for j in range(max(0, i - 19), i + 1)) for i in range(n)]

    def ind(i):
        d = days[i]
        k = [c for c in (T[i][6] if len(T[i]) > 6 else "") if c != "x"]
        return {"见底灯": 1 if b20[i] >= 2 else 0, "见顶灯": -1 if t20[i] >= 2 else 0,
                "方向": 1 if k and all(c == "1" for c in k) else 0, "托底撤出": -1 if chg.get(d, 0) <= -0.15 else 0,
                "国家队加速": 1 if nin.get(d) else 0, "放量托底": 1 if vnear.get(d) else 0}
    I = [ind(i) for i in range(n)]

    def fwd(i, h):
        return cl[i + h] / cl[i] - 1 if i + h < n else None

    def agg(ids):
        o = {"days": len(ids)}
        for h in (60, 120):
            xs = [fwd(i, h) for i in ids if fwd(i, h) is not None]
            o[str(h)] = {"avg": round(st.mean(xs), 4), "up": round(sum(x > 0 for x in xs) / len(xs), 3)} if xs else None
        return o

    def since(y):
        return [i for i in range(n) if days[i] >= y]

    # 每个指标自己的回测：亮的时候 vs 平时
    ind_stats = {}
    for k, _ in IND:
        ks = since("2023-01-01" if k in ("国家队加速", "放量托底") else "2013-01-01")
        ind_stats[k] = {"on": agg([i for i in ks if I[i][k] != 0]), "base": agg(ks), "from": days[ks[0]][:4]}

    def test(fn, y):
        ks = since(y)
        lab = [fn(i) for i in ks]
        lv = {L: agg([ks[j] for j in range(len(ks)) if lab[j] == L]) for L in LEVELS}
        wk = range(0, len(ks), 5)
        c = sum(MULT[lab[j]] for j in wk)
        v = sum(MULT[lab[j]] * cl[-1] / cl[ks[j]] for j in wk)
        v0 = sum(cl[-1] / cl[ks[j]] for j in wk)
        return {"levels": lv, "dca": round(v / c - 1, 4), "flat": round(v0 / len(wk) - 1, 4)}
    zone = lambda i: ZL[T[i][1]]  # noqa: E731
    v4 = lambda i: vote(I[i], OLD)  # noqa: E731
    v6 = lambda i: vote(I[i], [k for k, _ in IND])  # noqa: E731
    tests = {"2013": {"只看区间": test(zone, "2013-01-01"), "独立投票（4 个）": test(v4, "2013-01-01")},
             "2023": {"只看区间": test(zone, "2023-01-01"), "独立投票（4 个）": test(v4, "2023-01-01"), "独立投票（6 个）": test(v6, "2023-01-01")}}
    i = n - 1
    lv = v6(i)
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": days[i], "ind": I[i], "level": lv, "cls": CLS[lv], "bull": sum(v > 0 for v in I[i].values()),
                   "bear": sum(v < 0 for v in I[i].values()), "zone_level": zone(i), "v4": v4(i)},
        "ind": [{"name": k, "rule": r} for k, r in IND], "ind_stats": ind_stats,
        "levels": LEVELS, "mult": MULT, "cls": CLS, "test": tests,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{days[i]} 独立投票 {lv}（偏多 {data['latest']['bull']}、偏空 {data['latest']['bear']}），只看区间 {zone(i)}")
    return data


if __name__ == "__main__":
    run()
