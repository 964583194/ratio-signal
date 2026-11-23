"""红利低波50（H30269）套用红利打分规则的回测，对照红利低波100（930955）。只打印结果，不改任何数据。"""
import contextlib, io, json, sys, datetime as dt
sys.path.insert(0, "scripts")
import sources as S, dividend as D

S.refresh_all = lambda: False
orig = S.get_series
cyb = orig("cyb50")[0]


def fetch(code, col):
    for name, f in ((f"中证官网", lambda: S.cs_perf(code, col, "20100101")),
                    ("东方财富", lambda: S.em_kline("2." + code, "19900101") if col == "close" else {})):
        try:
            d = f()
            if d and len(d) > 500:
                print(code, col, name, min(d), max(d), len(d)); return d
        except Exception as e:  # noqa: BLE001
            print(code, col, name, "失败", type(e).__name__, str(e)[:80])
    return {}


def run(close, tr, pe, tag):
    m = {"hl100": close, "hl100_tr": tr, "hl100_pe": pe}
    S.get_series = lambda k, min_days=None: (m[k], "probe") if k in m else orig(k, min_days)
    cap = {}
    oc, og, osim = D.confirm, D.gates, D.simulate
    D.confirm = lambda s, days=2: (cap.__setitem__("sc", list(s)), oc(s, days))[1]
    D.gates = lambda px: (cap.__setitem__("px", list(px)), og(px))[1]
    D.simulate = lambda d, t, s, mo, g=None: (cap.setdefault("dt", (d, t)), osim(d, t, s, mo, g))[1]
    D.OUT = f"/tmp/{tag}.json"
    with contextlib.redirect_stdout(io.StringIO()):
        D.run(cyb)
    D.confirm, D.gates, D.simulate = oc, og, osim
    dates, trs = cap["dt"]; eff = oc(cap["sc"]); g = og(cap["px"])
    out = {"score_start": str(dates[0])}
    for cut in ("2000-01-01", "2018-05-14"):
        k0 = next(i for i, d in enumerate(dates) if str(d) >= cut)
        sl = lambda a: a[k0:]
        row = {}
        for k, (gt, mode) in {"普通定投": (None, "plain"), "按评分每天买": (None, "score"), "攒着买（现规则）": (g, "score")}.items():
            r = osim(sl(dates), sl(trs), sl(eff), mode, sl(gt) if gt else None)
            row[k] = f"年化 {r['xirr']*100:.2f}% 回撤 {r['mdd']*100:.1f}%"
        sells = sum(1 for i in range(1, len(eff)) if eff[i-1] <= 6)
        row["评分≤6天数"] = sells; row["起点"] = str(dates[k0])
        out[cut[:4]] = row
    L = json.load(open(D.OUT))["latest"]
    out["现在"] = {"日期": L["date"], "评分": L["score"], "档位": L["tier"]}
    # 评分和指数的关系：越跌越买？
    print(tag, json.dumps(out, ensure_ascii=False, indent=1))
    return cap


c50, t50, p50 = fetch("H30269", "close"), fetch("H20269", "close"), fetch("H30269", "peg")
run(orig("hl100")[0], orig("hl100_tr")[0], orig("hl100_pe")[0], "红利低波100")
if c50 and t50 and p50:
    run(c50, t50, p50, "红利低波50")
    a = sorted(set(c50) & set(orig("hl100")[0]))[-2000:]
    import statistics as st
    h = orig("hl100")[0]
    r1 = [c50[a[i]] / c50[a[i-5]] - 1 for i in range(5, len(a), 5)]; r2 = [h[a[i]] / h[a[i-5]] - 1 for i in range(5, len(a), 5)]
    m1, m2 = st.mean(r1), st.mean(r2)
    print("周涨跌相关", round(sum((x-m1)*(y-m2) for x, y in zip(r1, r2)) / (len(r1) * st.pstdev(r1) * st.pstdev(r2)), 3), a[0], a[-1])
else:
    print("红利低波50 数据没拿全")
