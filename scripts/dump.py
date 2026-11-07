import update as U
c,_=U.fetch("c",[("东财",lambda:U.from_eastmoney("0.399673")),("腾讯",lambda:U.from_tencent("sz399673"))])
k,_=U.fetch("k",[("东财",lambda:U.from_eastmoney("1.000688")),("腾讯",lambda:U.from_tencent("sh000688"))])
h,_=U.fetch("h",[("中证",lambda:U.from_csindex("930955"))])
print("CSVSTART")
for d in sorted(set(c)&set(k)&set(h)): print(f"ROW,{d},{c[d]},{k[d]},{h[d]}")
