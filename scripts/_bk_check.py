"""逐个调用备用源（跳过主源），走和正式更新一样的核对逻辑"""
import sys, datetime as dt, time
sys.path.insert(0, "scripts")
import sources as S
for key in ("pe300", "pe_a500", "hl100_pe", "cn10y", "pb_below", "margin", "m1", "loan", "ag0"):
    name, need, cands = S.CATALOG[key]
    cache = S.load_cache(key)
    since = (dt.date.fromisoformat(max(cache)) - dt.timedelta(days=S.INCR_DAYS)).isoformat()
    for label, fn in cands[1:]:
        t = time.time()
        try:
            new = fn(since)
            why = S._check(key, new, cache, True)
            ks = sorted(new)
            print(f"{'OK  ' if not why else '拒绝'} {name:<14} {label:<14} {len(new):4d} 条 最新 {ks[-1]} {new[ks[-1]]:.4f}（缓存 {cache[max(cache)]:.4f}） {why or ''} {time.time()-t:.0f}s")
        except Exception as e:
            print(f"失败 {name:<14} {label:<14} {type(e).__name__} {str(e)[:120]}")
