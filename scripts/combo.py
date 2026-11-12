"""综合判断（实验）：把市场温度页上的指标加成一个分数，和“只看区间”做对比。只作实验，不进规则。

打分（每个交易日）：
  区间   底部 +2 / 偏冷 +1 / 正常 0 / 偏热 −1 / 顶部 −2
  方向   只在偏冷、底部区算：宽度、M1、信贷脉冲全部回升 +1，全部走弱 −1
  托底   托底资金近 20 日份额 ≤ −15%（撤出中）−1
  加速   国家队流入在加速 +1，流出在加速 −1（2023 年起才有数据）
  放量   近 20 个交易日出现过放量托底日 +1（2023 年起）
分数 → 五档：≥2 积极、1 偏积极、0 照常、−1 偏谨慎、≤−2 谨慎。
对比几种组合：各档之后沪深300 的表现，以及按档调倍数（1.5 / 1.25 / 1 / 0.75 / 0.5）每周定投沪深300 的收益。
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
ZS = {0: 2, 1: 1, 2: 0, 3: -1, 4: -2}
VARIANTS = [("只看区间", []), ("区间 + 方向", ["dir"]), ("区间 + 方向 + 托底撤出", ["dir", "etf"]),
            ("全部（再加国家队加速、放量）", ["dir", "etf", "ntf", "vol"])]


def _load(n):
    with open(os.path.join(ROOT, "data", n), encoding="utf-8") as fh:
        return json.load(fh)


def lab(s):
    return "积极" if s >= 2 else "偏积极" if s == 1 else "照常" if s == 0 else "偏谨慎" if s == -1 else "谨慎"


def run():
    T, E, N = _load("temp.json")["series"], _load("etf300.json")["series"], _load("ntf.json")
    chg = {r[0]: r[3] / E[i - 20][3] - 1 for i, r in enumerate(E) if i >= 20}
    nst = {r[0]: None if r[2] is None else "in" if r[2] >= 90 else "out" if r[2] <= 10 else "flat" for r in N["series"]}
    nd = [r[0] for r in N["series"]]
    vset = {v["date"] for v in N["vols"]}
    vnear = {d: any(x in vset for x in nd[max(0, i - 19):i + 1]) for i, d in enumerate(nd)}
    days, cl, n = [r[0] for r in T], [r[2] for r in T], len(T)

    def parts(i):
        r, d = T[i], T[i][0]
        k = [c for c in (r[6] if len(r) > 6 else "") if c != "x"]
        dirv = (1 if k and all(c == "1" for c in k) else -1 if k and all(c == "0" for c in k) else 0) if r[1] <= 1 else 0
        return {"zone": ZS[r[1]], "dir": dirv, "etf": -1 if chg.get(d, 0) <= -0.15 else 0,
                "ntf": {"in": 1, "out": -1}.get(nst.get(d), 0), "vol": 1 if vnear.get(d) else 0}

    P = [parts(i) for i in range(n)]
    score = lambda i, use: P[i]["zone"] + sum(P[i][k] for k in use)  # noqa: E731

    def fwd(i, h):
        return cl[i + h] / cl[i] - 1 if i + h < n else None

    def test(use, since):
        ks = [i for i in range(n) if days[i] >= since]
        lv = {}
        for L in LEVELS:
            ids = [i for i in ks if lab(score(i, use)) == L]
            o = {"days": len(ids)}
            for h in (60, 120):
                xs = [fwd(i, h) for i in ids if fwd(i, h) is not None]
                o[str(h)] = {"avg": round(st.mean(xs), 4), "up": round(sum(x > 0 for x in xs) / len(xs), 3)} if xs else None
            lv[L] = o
        c = v = v0 = 0
        wk = ks[::5]
        for i in wk:
            m = MULT[lab(score(i, use))]
            c, v, v0 = c + m, v + m * cl[-1] / cl[i], v0 + cl[-1] / cl[i]
        return {"levels": lv, "dca": round(v / c - 1, 4), "flat": round(v0 / len(wk) - 1, 4), "money": round(c / len(wk), 2)}

    i = n - 1
    now = {name: {"score": score(i, use), "level": lab(score(i, use))} for name, use in VARIANTS}
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": days[i], "parts": P[i], "now": now, "level": now[VARIANTS[-1][0]]["level"], "cls": CLS[now[VARIANTS[-1][0]]["level"]]},
        "variants": [v[0] for v in VARIANTS], "levels": LEVELS, "mult": MULT,
        "test": {"2013": {name: test(use, "2013-01-01") for name, use in VARIANTS[:3]},
                 "2023": {name: test(use, "2023-01-01") for name, use in VARIANTS}},
        "series": [[days[k], score(k, VARIANTS[1][1]), score(k, VARIANTS[-1][1]) if days[k] >= "2023-01-01" else None, cl[k]] for k in range(n)],
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{days[i]} " + "，".join(f"{k} {v['level']}（{v['score']:+d}）" for k, v in now.items()))
    return data


if __name__ == "__main__":
    run()
