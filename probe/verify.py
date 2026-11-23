"""核实文章说法：中证红利 vs 创业板指 / 科创50，2020-2026。只打印。"""
import sys, time, statistics as st
sys.path.insert(0, "scripts")
import sources as S
def get(f, *a):
    for _ in range(3):
        try:
            d = f(*a)
            if d and len(d) > 300: return d
        except Exception as e: print("失败", a[0], type(e).__name__)
        time.sleep(8)
    return {}
D = {"中证红利": get(S.cs_perf, "000922", "close", "20150101"), "中证红利全收益": get(S.cs_perf, "H00922", "close", "20150101"),
     "创业板指": get(S.cs_perf, "399006", "close", "20150101") or get(S.em_kline, "0.399006", "20150101"),
     "科创50": get(S.cs_perf, "000688", "close", "20150101") or get(S.em_kline, "1.000688", "20150101"),
     "红利低波100全收益": get(S.cs_perf, "H20955", "close", "20150101")}
for k, v in D.items(): print(k, len(v), min(v) if v else None, max(v) if v else None)
A = "2020-01-01"
def yr(s, y):
    ks = sorted(k for k in s if k < f"{y+1}-01-01"); p = sorted(k for k in s if k < f"{y}-01-01")
    return s[ks[-1]] / s[p[-1]] - 1 if ks and p else None
print("年份", *D)
for y in range(2020, 2027): print(y, *[f"{yr(v, y)*100:+.1f}%" if v and yr(v, y) is not None else "—" for v in D.values()])
def mdd(s, a=A):
    pk = None; m = 0
    for k in sorted(s):
        if k < a: continue
        v = s[k]; pk = v if pk is None else max(pk, v); m = min(m, v / pk - 1)
    return m
def ann(s, a=A):
    ks = [k for k in sorted(s) if k >= a]; p = max(k for k in s if k < a)
    import datetime as dt
    yrs = (dt.date.fromisoformat(ks[-1]) - dt.date.fromisoformat(p)).days / 365.25
    return (s[ks[-1]] / s[p]) ** (1 / yrs) - 1, p, ks[-1]
for k, v in D.items():
    if v: a, p, e = ann(v); print(f"{k}: {p}~{e} 年化 {a*100:.2f}%  最大回撤 {mdd(v)*100:.1f}%")
def comove(x, y, step, a=A):
    ks = [k for k in sorted(set(x) & set(y)) if k >= a][::step]
    rx = [x[ks[i]] / x[ks[i-1]] - 1 for i in range(1, len(ks))]; ry = [y[ks[i]] / y[ks[i-1]] - 1 for i in range(1, len(ks))]
    same = sum(1 for p, q in zip(rx, ry) if p * q > 0) / len(rx)
    mx, my = st.mean(rx), st.mean(ry)
    c = sum((p-mx)*(q-my) for p, q in zip(rx, ry)) / (len(rx) * st.pstdev(rx) * st.pstdev(ry))
    return same, c, len(rx)
for b in ("创业板指", "科创50"):
    for step, nm in ((1, "日"), (5, "周"), (21, "月")):
        if D["中证红利"] and D[b]:
            s, c, n = comove(D["中证红利"], D[b], step); print(f"中证红利 vs {b} 按{nm}：同涨同跌 {s:.0%}，相关系数 {c:.2f}（{n} 个）")
# 滚动 60 日相关的分布
x, y = D["中证红利"], D["创业板指"]
ks = [k for k in sorted(set(x) & set(y)) if k >= A]
r1 = [x[ks[i]] / x[ks[i-1]] - 1 for i in range(1, len(ks))]; r2 = [y[ks[i]] / y[ks[i-1]] - 1 for i in range(1, len(ks))]
cs = []
for i in range(60, len(r1)):
    a, b = r1[i-60:i], r2[i-60:i]; ma, mb = st.mean(a), st.mean(b)
    cs.append(sum((p-ma)*(q-mb) for p, q in zip(a, b)) / (60 * st.pstdev(a) * st.pstdev(b)))
print(f"滚动 60 日相关：为正的时间 {sum(c>0 for c in cs)/len(cs):.0%}，最低 {min(cs):.2f}，最近 {cs[-1]:.2f}")
