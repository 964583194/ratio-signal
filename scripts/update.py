# 探查分支：只跑行业 ETF 抓取
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SEC_PER_RUN"] = "0"; os.environ["SEC_SZ_PER_RUN"] = "24"
import secflow
secflow.run()
