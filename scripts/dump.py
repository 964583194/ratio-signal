import update as U
c,_=U.fetch("c",[("东财",lambda:U.from_eastmoney("0.399673")),("腾讯",lambda:U.from_tencent("sz399673"))])
h,_=U.fetch("h",[("中证",lambda:U.from_csindex("930955"))])
for d in sorted(set(c)&set(h)):
    if d>="2016-09-23": print(f"ROW,{d},{c[d]},{h[d]}")
