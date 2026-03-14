"""
Tests for Global Demand Solver and Machine Count Precision.
Status: ACCEPTED_DRAFT

目标：验证反向拓扑推导的数学准确性，捍卫严格向上取整规则、农业闭环比率以及 52 端口极限闭环真理。
执行方式：在项目根目录运行 `pytest src/tests/test_demand.py -v`
"""

import math
import pytest
from typing import Dict, Tuple, Any

from src.preprocess.demand_solver import (
    solve_demands, 
    generate_ceil_machine_counts, 
    generate_port_budget
)

# ============================================================================
# 测试夹具 (Fixtures)
# ============================================================================

@pytest.fixture
def solved_data() -> Tuple[Dict[str, float], Dict[str, float], Dict[str, int], Dict[str, Any]]:
    """一次性计算全场需求并提供给所有测试用例使用"""
    flows, fractional = solve_demands()
    counts = generate_ceil_machine_counts(fractional)
    budget = generate_port_budget(flows)
    return flows, fractional, counts, budget

# ============================================================================
# 核心断言测试 (Assertions)
# ============================================================================

def test_target_flows_accuracy(solved_data):
    """测试终极吞吐目标是否精确对齐业务要求"""
    flows, _, _, _ = solved_data
    # 3 条满速电池线 = 3 * 0.2 = 0.6/tick
    assert math.isclose(flows["valley_battery"], 0.6), "高容谷地电池吞吐率错误"
    # 2.75 条胶囊线 = 2.75 * 0.2 = 0.55/tick
    assert math.isclose(flows["qiaoyu_capsule"], 0.55), "精选荞愈胶囊吞吐率错误"

def test_fractional_to_ceil_rounding_rule(solved_data):
    """测试严格向上取整法则 (Ceil Rule)，不允许向下抹去算力，也不允许出现半台机器"""
    _, fractional, counts, _ = solved_data
    
    # 胶囊灌装机：理论需要 2.75 台
    assert math.isclose(fractional["filling_capsule"], 2.75)
    assert counts["filling_capsule"] == 3, "2.75 台灌装机必须被严格向上取整为 3 台"
    
    # 砂叶粉碎机：理论需要 10.5 台 (31.5需求 / 3.0单台产出)
    assert math.isclose(fractional["crusher_sandleaf"], 10.5)
    assert counts["crusher_sandleaf"] == 11, "10.5 台砂叶粉碎机必须被严格向上取整为 11 台"
    
    # 塑型机：理论需要 5.5 台
    assert math.isclose(fractional["molding_bottle"], 5.5)
    assert counts["molding_bottle"] == 6, "5.5 台塑型机必须被严格向上取整为 6 台"

def test_agricultural_closed_loop_conservation(solved_data):
    """测试农业自洽系统守恒律：种植机算力必须精确等于采种机算力的两倍"""
    _, fractional, _, _ = solved_data
    
    planter_bw = fractional["planter_buckwheat"]
    seed_collector_bw = fractional["seed_collector_buckwheat"]
    assert math.isclose(planter_bw, seed_collector_bw * 2.0), "荞花农业闭环比例失衡 (需 2:1)"
    
    planter_sl = fractional["planter_sandleaf"]
    seed_collector_sl = fractional["seed_collector_sandleaf"]
    assert math.isclose(planter_sl, seed_collector_sl * 2.0), "砂叶农业闭环比例失衡 (需 2:1)"

def test_the_52_port_miracle(solved_data):
    """测试原生边界口的硬性数学闭环 (52-Port Miracle)"""
    _, _, _, budget = solved_data
    b_info = budget["miracle_52_budget"]
    
    # 验证蓝铁矿需求是否准确传导到底层 (17台精炼钢块 -> 17蓝铁粉 + 17蓝铁粉(致密需求) = 34)
    assert math.isclose(b_info["blue_iron_ore_inputs_required"], 34.0), "蓝铁矿理论需求必须精确为 34"
    
    # 验证源矿需求是否准确传导到底层 (9台致密源石研磨 -> 18源石粉 -> 18源矿)
    assert math.isclose(b_info["source_ore_inputs_required"], 18.0), "源矿理论需求必须精确为 18"
    
    # 终极闭环验证：物理拓扑恰好 100% 吃满 46(原生) + 6(核心) = 52口
    assert math.isclose(b_info["total_boundary_and_core_ports_required"], 52.0)
    assert budget["status"] == "FEASIBLE", "原矿输入超出全场 52 口物理上限！"

def test_absolute_total_machine_count(solved_data):
    """
    测试物理排布刚体总数。
    任何会导致该数量不等于 219 的配方或逻辑改动，均意味着违背了 04 章冻结算力规模。
    """
    _, _, counts, _ = solved_data
    total_machines = sum(counts.values())
    
    assert total_machines == 219, f"严重越界：刚体总数异变为 {total_machines} 台！必须绝对锁定为 219 台。"
