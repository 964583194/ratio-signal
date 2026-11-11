"""探测黄金模型要用的数据"""
import json, sys
sys.path.insert(0, "scripts")
import sources as S
out = {}
def tryit(name, fn):
    try:
        d = fn()
        ks = sorted(d)
        print(f"== {name}: {len(ks)} 条 {ks[0]} ~ {ks[-1]} 最新 {d[ks[-1]]}")
        out[name] = d
    except Exception as e:
        print(f"== {name} 失败 {e!r}")
for s in ("DFII10", "DTWEXBGS", "T10YIE"):
    tryit("fred_" + s, lambda s=s: S.fred(s))
import akshare as ak
def sge(sym, col="close"):
    df = ak.spot_hist_sge(symbol=sym)
    print(sym, list(df.columns)); return {str(r["date"])[:10]: float(r[col]) for _, r in df.iterrows()}
tryit("sge_au", lambda: sge("Au99.99"))
tryit("sge_ag", lambda: sge("Ag(T+D)"))
def fut(sym):
    df = ak.futures_main_sina(symbol=sym)
    print(sym, list(df.columns)); return {str(r["日期"])[:10]: float(r["收盘价"]) for _, r in df.iterrows()}
tryit("shfe_ag0", lambda: fut("AG0"))
def spdr():
    df = ak.macro_cons_gold()
    print("spdr", list(df.columns), df.tail(2).to_string())
    c = [x for x in df.columns if "库存" in x or "持仓" in x or "总" in x][0]
    return {str(r["日期"])[:10]: float(r[c]) for _, r in df.iterrows() if str(r[c]) not in ("nan", "")}
tryit("spdr", spdr)
def cftc():
    for fn in ("macro_usa_cftc_nc_holding", "macro_usa_cftc_c_holding", "macro_usa_cftc_merchant_goods_holding"):
        if not hasattr(ak, fn): continue
        try:
            df = getattr(ak, fn)()
            gc = [c for c in df.columns if "黄金" in c]
            print(fn, len(df), gc[:8])
            if gc:
                dcol = df.columns[0]
                return {str(r[dcol])[:10]: [float(r[c]) if str(r[c]) not in ("nan", "") else None for c in gc] for _, r in df.iterrows()} | {"_cols": gc}
        except Exception as e:
            print(fn, "失败", e)
    raise RuntimeError("没有黄金列")
tryit("cftc", cftc)
s = json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str)
for i in range(0, len(s), 1500):
    print(f"CHUNK{i // 1500:05d}:" + s[i:i + 1500])
print("CHUNKEND")
