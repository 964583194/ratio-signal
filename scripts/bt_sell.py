"""临时回测：比值轮动加卖点（比值高位把创业板50 部分转到红利低波100）"""
import datetime as dt
import update as U

cyb_raw, _ = U.fetch("创业板50", [("东方财富", lambda: U.from_eastmoney("0.399673")),
                                 ("腾讯", lambda: U.from_tencent("sz399673"))])
hl_raw, _ = U.fetch("红利低波100", [("中证", lambda: U.from_csindex("930955"))])
common = [d for d in sorted(set(cyb_raw) & set(hl_raw)) if d >= "2016-09-23"]
dates = [dt.date.fromisoformat(d) for d in common]
cyb = [cyb_raw[d] for d in common]
hl = [hl_raw[d] for d in common]
ratio = [c / h for c, h in zip(cyb, hl)]
FEE = U.FEE


def run(sell_tiers=(), buy_tiers=(), lo=0.16, hi=0.28):
    """sell_tiers: [(比值阈值, 转出比例)]，比值 >= 阈值时把创业板50 持仓的该比例转到红利，每段行情每档只触发一次，比值回到 hi 以下重置
       buy_tiers: [(比值阈值, 转出比例)]，比值 <= 阈值时把红利持仓的该比例转到创业板50，比值回到 lo 以上重置"""
    vc = vh = pool = 0.0
    nav = peak = 1.0
    mdd = 0.0
    prev = 0.0
    cfs = []
    last_wk = None
    hit_s, hit_b = set(), set()
    switches = 0
    for i, d in enumerate(dates):
        if i:
            vc *= cyb[i] / cyb[i - 1] * (1 + U.DIV_CYB / 252)
            vh *= hl[i] / hl[i - 1] * (1 + U.DIV_HL / 252)
            pool *= 1 + U.CASH_YIELD / 252
        cur = vc + vh + pool
        if prev > 0:
            nav *= cur / prev
            peak = max(peak, nav)
            mdd = min(mdd, nav / peak - 1)
        r = ratio[i]
        wk = d.isocalendar()[:2]
        if wk != last_wk:  # 每周首个交易日看信号
            last_wk = wk
            cfs.append((d, -U.WEEKLY))
            pool += U.WEEKLY
            if r < lo:
                vc += pool * (1 - FEE)
                pool = 0.0
            elif r >= hi:
                vh += pool * (1 - FEE)
                pool = 0.0
            if r < hi:
                hit_s.clear()
            if r > lo:
                hit_b.clear()
            for th, frac in sell_tiers:
                if r >= th and th not in hit_s and vc > 0:
                    amt = vc * frac
                    vc -= amt
                    vh += amt * (1 - FEE) ** 2
                    hit_s.add(th)
                    switches += 1
            for th, frac in buy_tiers:
                if r <= th and th not in hit_b and vh > 0:
                    amt = vh * frac
                    vh -= amt
                    vc += amt * (1 - FEE) ** 2
                    hit_b.add(th)
                    switches += 1
        prev = vc + vh + pool
    final = vc + vh + pool
    cfs.append((dates[-1], final))
    x = U.xirr(cfs)
    return x, mdd, final, -sum(a for _, a in cfs[:-1]), switches, vc / final, vh / final


def show(name, res):
    x, mdd, final, inv, sw, wc, wh = res
    print(f"{name:<34} 年化 {x*100:6.2f}%  回撤 {mdd*100:6.1f}%  期末 {final:>9,.0f}/{inv:,.0f}  "
          f"转换 {sw:>2} 次  当前持仓 创业板 {wc*100:4.1f}% 红利 {wh*100:4.1f}%")


print(f"区间 {common[0]} ~ {common[-1]}，{len(common)} 天，最新比值 {ratio[-1]:.4f}")
show("A 原规则（不卖）", run())
for th in (0.32, 0.35, 0.38, 0.40):
    show(f"B 比值≥{th} 转出一半创业板", run([(th, 0.5)]))
for th in (0.32, 0.35, 0.38):
    show(f"C 比值≥{th} 全部转出创业板", run([(th, 1.0)]))
show("D 分档 0.32转1/3、0.36转1/2、0.40全转", run([(0.32, 1 / 3), (0.36, 0.5), (0.40, 1.0)]))
show("E 双向：≥0.35转出半仓创业板，≤0.14转半仓红利", run([(0.35, 0.5)], [(0.14, 0.5)]))
show("F 双向：≥0.35全转红利，≤0.14全转创业板", run([(0.35, 1.0)], [(0.14, 1.0)]))

# 卖点检验：比值处于各区间时，之后 26 周创业板50 相对红利低波100 的超额
print("\n比值所在区间 → 之后 26 周（约 126 个交易日）创业板50 跑赢红利低波100 的平均幅度")
for lo_, hi_ in [(0, .16), (.16, .22), (.22, .28), (.28, .32), (.32, .36), (.36, .40), (.40, 1)]:
    xs = [(cyb[i + 126] / cyb[i]) / (hl[i + 126] / hl[i]) - 1 for i in range(len(ratio) - 126)
          if lo_ <= ratio[i] < hi_]
    if xs:
        print(f"  {lo_:.2f}~{hi_:.2f}: {sum(xs)/len(xs)*100:+6.1f}%  （{len(xs)} 天，跑赢概率 {sum(x>0 for x in xs)/len(xs)*100:.0f}%）")
