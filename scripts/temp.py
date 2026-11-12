"""市场温度：五档区间 + 方向。只作提醒，不改定投规则。

区间（按近 20 个交易日里最多亮几个灯，避免一天一变）：
  顶部  见顶信号灯 ≥3 个        偏热  见顶信号灯 2 个
  底部  见底信号灯 ≥4 个        偏冷  见底信号灯 2~3 个        其余：正常
见底信号灯 6 个，各自独立亮灯：
  破净率    破净率在近 10 年 85% 分位以上（便宜股多）
  股债利差  沪深300 盈利收益率 − 十年国债 在近 10 年 85% 分位以上
  地量      两市成交额 20 日均值在近 3 年最低 15%
  创业板便宜 创业板指市盈率在近 10 年最低 15%
  宽度低    站上 12 个月均线的股票 < 20%（月度，当月按至今计算）
  总市值低  巴菲特指标（总市值 ÷ GDP）在近 10 年最低 15%
方向（只在偏冷、底部区有参考意义）：
  宽度      本月站上年线的股票比例 比上个月高
  M1        M1 同比 比 3 个月前高（企业和个人的钱从“存着”变成“准备花”）
  信贷脉冲  近 12 个月新增人民币贷款合计的同比 比 3 个月前高（实体经济借钱的势头）
  3 个回升 = 转暖，1~2 个 = 走平，0 个 = 还在走弱
历史检验时宏观数据按“月底后约 45 天才看得到”处理，不偷看未来。
"""
import bisect
import datetime as dt
import json
import os
import statistics as st

import market as MK
import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "temp.json")
START = "2013-01-01"
ZONES = ["底部", "偏冷", "正常", "偏热", "顶部"]
BOT = ["破净率", "股债利差", "地量", "创业板便宜", "宽度低", "总市值低"]
BOT_DESC = {"破净率": "破净率在近 10 年 85% 分位以上（便宜股多）", "股债利差": "股债利差在近 10 年 85% 分位以上",
            "地量": "两市成交额在近 3 年最低 15%", "创业板便宜": "创业板市盈率在近 10 年最低 15%",
            "宽度低": "站上年线的股票不到 20%", "总市值低": "总市值 ÷ GDP 在近 10 年最低 15%"}
DIRS = ["宽度", "M1", "信贷脉冲"]
DIR_DESC = {"宽度": "站上年线的股票比例，比上个月高 = 回升", "M1": "M1 同比，比 3 个月前高 = 回升（钱开始活起来）",
            "信贷脉冲": "近 12 个月新增贷款的同比，比 3 个月前高 = 回升（借钱的势头）"}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def mback(mo, k):
    y, m = int(mo[:4]), int(mo[5:7]) - k
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"


def run():
    hs, _ = S.get_series("hs300")
    pbk, pb = (lambda d: (sorted(d), d))(S.get_series("pb_below")[0])
    pe, _ = S.get_series("pe300")
    y, _ = S.get_series("cn10y")
    am, _ = S.get_series("mkt_amt")
    cpe, _ = S.get_series("pe_cyb")
    try:
        bf, _ = S.get_series("buffett")
    except Exception:  # noqa: BLE001
        bf = {}
    m1 = {}
    loan = {}
    for key, dst in (("m1", m1), ("loan", loan)):
        try:
            dst.update({k[:7]: v for k, v in S.get_series(key)[0].items()})
        except Exception as e:  # noqa: BLE001
            print(f"市场温度：{key} 取不到（{e}），方向里先不算它")
    B = _load(os.path.join(ROOT, "data", "raw", "breadth_monthly.json"), {})
    T = _load(os.path.join(ROOT, "data", "topsig.json"), {})
    top_cnt = {r[0]: r[1] for r in T.get("series", [])}

    yk, pk = sorted(y), sorted(pe)
    erp = {}
    for d in pk:
        j = bisect.bisect_right(yk, d) - 1
        if j >= 0 and pe[d] > 0:
            erp[d] = 100 / pe[d] - y[yk[j]]
    ek = sorted(erp)
    ak = sorted(am)
    am20 = MK.ma(am, ak, 20)
    a2k = sorted(am20)
    ck, bk = sorted(cpe), sorted(bf)

    # 信贷脉冲：近 12 个月新增贷款合计 ÷ 上一年同期 − 1
    def roll12(mo):
        xs = [loan.get(mback(mo, k)) for k in range(12)]
        return None if None in xs else sum(xs)
    imp = {}
    for mo in sorted(loan):
        a, b = roll12(mo), roll12(mback(mo, 12))
        if a and b:
            imp[mo] = a / b - 1

    def wid(mo):
        return (B.get(mo) or {}).get("ma12")

    def seen(d):          # 交易日 d 当时能看到的最新宏观月份（月底后约 45 天公布）
        t = dt.date.fromisoformat(d) - dt.timedelta(days=45)
        return f"{t.year}-{t.month:02d}"

    def up(src, mo, k=3):
        a, b = src.get(mo), src.get(mback(mo, k))
        return None if a is None or b is None else a > b

    days = [d for d in sorted(hs) if d >= START]
    n = len(days)
    cl = [hs[d] for d in days]
    rows = []
    for d in days:
        p_pb = MK.pct_at(pbk, pb, d, 10)
        p_erp = MK.pct_at(ek, erp, d, 10)
        p_amt = MK.pct_at(a2k, am20, d, 3)
        p_pe = MK.pct_at(ck, cpe, d, 10, 50)
        p_bf = MK.pct_at(bk, bf, d, 10, 500) if bk else None
        w = wid(d[:7])
        v = [p_pb, p_erp, p_amt, p_pe, w, p_bf]
        lit = [p_pb is not None and p_pb >= .85, p_erp is not None and p_erp >= .85, p_amt is not None and p_amt <= .15,
               p_pe is not None and p_pe <= .15, w is not None and w < .20, p_bf is not None and p_bf <= .15]
        mo = seen(d)
        wp = wid(mback(d[:7], 1))
        dirs = [None if w is None or wp is None else w > wp, up(m1, mo), up(imp, mo)]
        rows.append({"d": d, "lit": lit, "v": v, "top": top_cnt.get(d, 0), "dir": dirs})
    for i, r in enumerate(rows):
        b = max(sum(x["lit"]) for x in rows[max(0, i - 19):i + 1])
        t = max(x["top"] for x in rows[max(0, i - 19):i + 1])
        r["z"] = 4 if t >= 3 else 3 if t == 2 else 0 if b >= 4 else 1 if b >= 2 else 2

    def fwd(i, h):
        return cl[i + h] / cl[i] - 1 if i + h < n else None

    def stat(ks):
        o = {"days": len(ks)}
        for h in (120, 250):
            xs = [fwd(i, h) for i in ks if fwd(i, h) is not None]
            o[str(h)] = {"avg": round(st.mean(xs), 4), "up": round(sum(x > 0 for x in xs) / len(xs), 3)} if xs else None
        dd = [min(cl[i + 1:min(n, i + 121)]) / cl[i] - 1 for i in ks if i + 1 < n]
        o["dd"] = round(st.mean(dd), 4) if dd else None      # 之后半年里平均最多再跌
        return o
    zstats = {}
    for z in range(5):
        ks = [i for i in range(n) if rows[i]["z"] == z]
        runs, c = [], 0
        for i in range(n):
            if rows[i]["z"] == z:
                c += 1
            elif c:
                runs.append(c)
                c = 0
        if c:
            runs.append(c)
        zstats[ZONES[z]] = {**stat(ks), "segs": len(runs), "avg_len": round(st.mean(runs)) if runs else 0}
    cold = [i for i in range(n) if rows[i]["z"] <= 1]
    dstats = {}
    for k, name in enumerate(DIRS):
        dstats[name] = {"up": stat([i for i in cold if rows[i]["dir"][k] is True]),
                        "down": stat([i for i in cold if rows[i]["dir"][k] is False])}

    # ---- 现在：方向用已经公布的最新数据（不再按 45 天延后）
    L = rows[-1]
    mo_now = L["d"][:7]
    m1k, ik = sorted(m1), sorted(imp)
    w_now, w_prev = wid(mo_now), wid(mback(mo_now, 1))
    dnow = []
    dnow.append({"name": "宽度", "up": None if w_now is None or w_prev is None else w_now > w_prev,
                 "now": w_now, "prev": w_prev, "now_m": mo_now, "prev_m": mback(mo_now, 1), "fmt": "pct",
                 "partial": bool((B.get(mo_now) or {}).get("partial"))})
    if m1k:
        a = m1k[-1]
        dnow.append({"name": "M1", "up": up(m1, a), "now": m1[a], "prev": m1.get(mback(a, 3)), "now_m": a, "prev_m": mback(a, 3), "fmt": "num"})
    if ik:
        a = ik[-1]
        dnow.append({"name": "信贷脉冲", "up": up(imp, a), "now": round(imp[a], 4), "prev": round(imp.get(mback(a, 3)), 4) if imp.get(mback(a, 3)) is not None else None,
                     "now_m": a, "prev_m": mback(a, 3), "fmt": "pct"})
    known = [x for x in dnow if x["up"] is not None]
    nup = sum(x["up"] for x in known)
    dlab = "转暖" if known and nup == len(known) else "还在走弱" if nup == 0 else "走平"
    z = L["z"]
    zn = ZONES[z]
    if z == 4:
        act = "分批止盈要果断，宽基少买，别追加"
    elif z == 3:
        act = "不额外加钱"
    elif z == 2:
        act = "按规则正常执行"
    elif dlab == "转暖":
        act = "按规则分批买，可以按节奏走" if z == 1 else "底部在确认，分批买可以加快"
    elif dlab == "走平":
        act = "按规则分批买，节奏别快" if z == 1 else "分批买，留足子弹"
    else:
        act = "按规则买，慢一点，留足子弹" if z == 1 else "分批买，可能还要磨一段，留足子弹"
    up_names = [x["name"] for x in known if x["up"]]
    dn_names = [x["name"] for x in known if not x["up"]]
    dtext = (f"{'、'.join(up_names)}回升" if up_names else "") + ("，" if up_names and dn_names else "") + \
            (f"{'、'.join(dn_names)}还在走弱" if dn_names else "")
    bl = [BOT[k] for k in range(6) if L["lit"][k]]
    verdict = f"{zn}区" + (f"，方向{dlab}（{dtext}）" if z <= 1 else "") + f" → {act}"
    cls = "g1" if z <= 1 else "c0" if z == 2 else "h1" if z == 3 else "r1"
    pv = L["v"]
    data = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "latest": {"date": L["d"], "zone": zn, "z": z, "cls": cls, "action": act, "verdict": verdict,
                   "bottom": {"count": sum(L["lit"]), "lit": bl, "values": {BOT[k]: (None if pv[k] is None else round(pv[k], 4)) for k in range(6)}},
                   "top": {"count": L["top"], "lit": (T.get("latest") or {}).get("lit", [])},
                   "dir": {"label": dlab, "n_up": nup, "n": len(known), "items": dnow, "text": dtext},
                   "month_partial": bool((B.get(mo_now) or {}).get("partial"))},
        "zones": ZONES, "bot_names": BOT, "bot_desc": BOT_DESC, "dir_desc": DIR_DESC,
        "series": [[r["d"], r["z"], cl[i], sum(r["lit"]), r["top"], "".join("1" if x else "0" for x in r["lit"]),
                    "".join("x" if x is None else "1" if x else "0" for x in r["dir"])] for i, r in enumerate(rows)],   # 最后一项：方向（宽度、M1、信贷脉冲）
        "macro": [[mo, m1.get(mo), None if imp.get(mo) is None else round(imp[mo], 4)] for mo in sorted(set(m1) | set(imp)) if mo >= "2012-01"],
        "zone_stats": zstats, "dir_stats": dstats,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"写入 {OUT}：{L['d']} {verdict}；见底灯 {sum(L['lit'])}/6 {bl}，见顶灯 {L['top']}/7")
    return data


if __name__ == "__main__":
    run()
