import sources as S
d={}
for nm,f in [("东方财富",lambda:S.em_kline("1.000300","20050101")),("中证",lambda:S.cs_perf("000300","close","20050101")),("腾讯",lambda:S.tx_kline("sh000300",2005))]:
    try:
        d=f()
        if len(d)>4000: print("SRC",nm,len(d)); break
    except Exception as e: print("ERR",nm,e)
for k in sorted(d): print(f"ROW,{k},{d[k]}")
