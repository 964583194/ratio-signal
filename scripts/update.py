# 探查分支：只跑行业 ETF 抓取
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SEC_PER_RUN"] = "120"
import secflow
secflow.run()
