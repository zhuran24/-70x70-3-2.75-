"""验证 OPT-01: 模板级池化供电蕴含构建时间。"""
import sys, time
sys.path.insert(0, ".")
from src.models.master_model import MasterPlacementModel, load_project_data
from pathlib import Path

root = Path(".")
instances, pools, rules = load_project_data(root)

print("=" * 60)
print("OPT-01 验证：模板级池化供电蕴含")
print("=" * 60)

t0 = time.time()
model = MasterPlacementModel(instances, pools, rules, skip_power_coverage=False)
model.build()
elapsed = time.time() - t0

print(f"\n✅ 模型构建完成！总耗时: {elapsed:.1f}s")
print(f"   powered格数: {len(model.powered_cell)}")
if elapsed < 60:
    print("🎉 OPT-01 成功: 构建时间 < 1 分钟!")
elif elapsed < 120:
    print("✅ 显著改善 (< 2 min)")
else:
    print(f"⚠️ 仍需优化 ({elapsed:.0f}s)")
