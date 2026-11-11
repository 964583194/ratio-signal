import sys
sys.path.insert(0, "scripts")
import sources as S
for key, code in (("pe300", "000300"), ("pe_a500", "000510")):
    new = S.csi_value(code)(None); old = S.load_cache(key)
    pr = S.cs_perf(code, "peg", "20261001")
    for d in sorted(new):
        print(key, d, "日度指标", new[d], "缓存", old.get(d), "官网现在", pr.get(d), "比例", round(old[d] / new[d], 4) if old.get(d) else None)
