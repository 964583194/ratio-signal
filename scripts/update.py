# 探查：强制走备用接口，看能不能取到
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["FORCE_BACKUP"] = "1"; os.environ["SEC_PER_RUN"] = "0"
import divflow, secflow
divflow.SSE_PER_RUN = 0
divflow.run(); secflow.run()
