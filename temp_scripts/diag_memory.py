"""
诊断脚本: 确认求解器崩溃根因
- 记录内存使用到 diag_log.txt
- 捕获所有异常（Python 级和信号级）
"""
import sys, os, traceback, time, signal

# UTF-8 输出
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diag_log.txt")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)

def mem_gb():
    if HAS_PSUTIL:
        return f"{psutil.Process().memory_info().rss / 1024**3:.2f} GB"
    return "N/A (pip install psutil)"

# 注册退出钩子
import atexit
@atexit.register
def on_exit():
    log(f"[atexit] 进程正常退出, 内存={mem_gb()}")

log("=" * 60)
log("诊断脚本启动")
log(f"Python: {sys.version}")
log(f"PYTHONUTF8={os.environ.get('PYTHONUTF8', 'NOT SET')}")
log(f"sys.stdout.encoding={sys.stdout.encoding}")
log(f"初始内存: {mem_gb()}")
log(f"psutil 可用: {HAS_PSUTIL}")

from src.models.master_model import MasterPlacementModel, load_project_data
from src.models.cut_manager import CutManager, LBBDController
from src.search.outer_search import generate_candidate_sizes
from pathlib import Path

ROOT = Path(__file__).parent.parent
instances, pools, rules = load_project_data(ROOT)
candidates = generate_candidate_sizes()
area, w, h = candidates[0]
log(f"候选: {w}x{h}, area={area}")

# 构建模型
t0 = time.time()
master = MasterPlacementModel(instances, pools, rules, ghost_rect=(w, h), skip_power_coverage=True)
master.build()
log(f"模型构建: {time.time()-t0:.1f}s, 内存={mem_gb()}")

# 求解 (用 try/except 包裹全部)
cm = CutManager()
ctrl = LBBDController(master, cm, max_iterations=1, master_time_limit=1200.0)

try:
    log("开始求解...")
    result = ctrl.run()
    log(f"求解完成! 结果: {'有解' if result else '无解'}")
    log(f"求解后内存: {mem_gb()}")
except MemoryError as e:
    log(f"[致命] MemoryError: {e}")
    log(f"内存: {mem_gb()}")
except Exception as e:
    log(f"[异常] {type(e).__name__}: {e}")
    traceback.print_exc()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        traceback.print_exc(file=f)
except BaseException as e:
    log(f"[BaseException] {type(e).__name__}: {e}")
finally:
    log(f"finally块执行, 内存={mem_gb()}")
    log("=" * 60)
