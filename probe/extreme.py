"""去掉极端情况再回测：红利低波50 / 100 套红利打分规则。只打印结果。"""
import contextlib, io, json, sys, time
sys.path.insert(0, "scripts")
import sources as S, dividend as D
S.refresh_all = lambda: False
orig = S.get_series
cyb = orig("cyb50")[0]


def fetch(code, col):
    for _ in range(4):
        try:
            d = S.cs_perf(code, col, "20100101")
            if d and len(d) > 500:
                return d
        except Exception as e:  # noqa: BLE001
            print(code, col, "失败", type(e).__name__)
        time.sleep(10)
    raise SystemExit(f"{code} 拿不到")


def clip(close, tr, q):
    """把涨跌最极端的 q（两头各 q/2）交易日的涨跌设为 0，价格和全收益同步"""
    ds = sorted(set(close) & set(tr)); r = [close[ds[i]] / close[ds[i-1]] - 1 for i in range(1, len(ds))]
    s = sorted(r); lo, hi = s[int(len(s) * q / 2)], s[-int(len(s) * q / 2) - 1]
    c2, t2 = {ds[0]: close[ds[0]]}, {ds[0]: tr[ds[0]]}
    n = 0
    for i in range(1, len(ds)):
        rc, rt = r[i-1], tr[ds[i]] / tr[ds[i-1]] - 1
        if rc < lo or rc > hi:
            rc = rt = 0.0; n += 1
        c2[ds[i]] = c2[ds[i-1]] * (1 + rc); t2[ds[i]] = t2[ds[i-1]] * (1 + rt)
    return c2, t2, n


def prep(close, tr, pe):
    m = {"hl100": close, "hl100_tr": tr, "hl100_pe": pe}
    S.get_series = lambda k, min_days=None: (m[k], "probe") if k in m else orig(k, min_days)
    cap = {}
    oc, og, osim = D.confirm, D.gates, D.simulate
    D.confirm = lambda s, days=2: (cap.__setitem__("sc", list(s)), oc(s, days))[1]
    D.gates = lambda px: (cap.__setitem__("px", list(px)), og(px))[1]
    D.simulate = lambda d, t, s, mo, g=None: (cap.setdefault("dt", (d, t)), osim(d, t, s, mo, g))[1]
    D.OUT = "/tmp/x.json"
    with contextlib.redirect_stdout(io.StringIO()):
        D.run(cyb)
    D.confirm, D.gates, D.simulate = oc, og, osim
    return cap["dt"][0], cap["dt"][1], oc(cap["sc"]), og(cap["px"])


def bt(dates, trs, eff, g, a=0, b=None):
    sl = lambda x: x[a:b]
    p = D.simulate(sl(dates), sl(trs), sl(eff), "plain"); s = D.simulate(sl(dates), sl(trs), sl(eff), "score", sl(g))
    return p, s


def show(tag, P):
    p, s = P
    print(f"  {tag:30s} 普通定投 {p['xirr']*100:5.2f}% / {p['mdd']*100:5.1f}%   攒着买 {s['xirr']*100:5.2f}% / {s['mdd']*100:5.1f}%   差 {(s['xirr']-p['xirr'])*100:+.2f}")


for name, (close, tr, pe) in {
        "红利低波50": (fetch("H30269", "close"), fetch("H20269", "close"), fetch("H30269", "peg")),
        "红利低波100": (orig("hl100")[0], orig("hl100_tr")[0], orig("hl100_pe")[0])}.items():
    print(f"\n==== {name} ====")
    dates, trs, eff, g = prep(close, tr, pe)
    ds = [str(d) for d in dates]
    show(f"原始（{ds[0][:7]} 起）", bt(dates, trs, eff, g))
    for cut, why in (("2016-03-01", "去掉 2015 股灾"), ("2019-01-01", "去掉 2018 熊市"), ("2021-01-01", "只看 2021 起")):
        k = next(i for i, d in enumerate(ds) if d >= cut)
        if k > 0: show(f"{why}（{cut[:7]} 起）", bt(dates, trs, eff, g, k))
    k = next((i for i, d in enumerate(ds) if d >= "2024-09-01"), None)
    if k: show("去掉 2024-09 起的大涨", bt(dates, trs, eff, g, 0, k))
    for q in (0.01, 0.02):
        c2, t2, n = clip(close, tr, q)
        d2, tr2, e2, g2 = prep(c2, t2, pe)
        show(f"去掉最极端 {q:.0%} 交易日（{n} 天）", bt(d2, tr2, e2, g2))
    # 滚动 3 年：攒着买比普通定投赚得多 / 回撤小的比例
    win, w_ret, w_dd, diffs = 244 * 3, 0, 0, []
    starts = list(range(0, len(dates) - win, 21))
    for a in starts:
        p, s = bt(dates, trs, eff, g, a, a + win)
        diffs.append(s["xirr"] - p["xirr"]); w_ret += s["xirr"] >= p["xirr"]; w_dd += s["mdd"] >= p["mdd"]
    diffs.sort()
    print(f"  滚动 3 年（{len(starts)} 段）：攒着买赚得更多 {w_ret/len(starts):.0%}，回撤更小 {w_dd/len(starts):.0%}；"
          f"年化差 中位 {diffs[len(diffs)//2]*100:+.2f}，最差 {diffs[0]*100:+.2f}，最好 {diffs[-1]*100:+.2f}")
