"""
Tests for Canonical Rules, Schema, Models, and Semantic Validator.
Status: ACCEPTED_DRAFT

目标：验证静态规则底座的合法性，并确保越权或违背物理真理的设定会被无情拦截。
执行方式：在项目根目录运行 `pytest src/tests/test_rules.py -v`
"""

import json
import copy
from pathlib import Path
import pytest
from jsonschema import validate, ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from src.rules.models import CanonicalRulesDocument
from src.rules.semantic_validator import validate_canonical_document, SemanticValidationError

# ============================================================================
# 测试环境与路径准备
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RULES_JSON_PATH = PROJECT_ROOT / "rules" / "canonical_rules.json"
SCHEMA_JSON_PATH = PROJECT_ROOT / "rules" / "canonical_rules.schema.json"

@pytest.fixture
def raw_rules_dict() -> dict:
    """提供纯净的、原始的 JSON 字典"""
    assert RULES_JSON_PATH.exists(), f"找不到规则字典: {RULES_JSON_PATH}"
    with open(RULES_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def raw_schema_dict() -> dict:
    """提供纯净的 JSON Schema 字典"""
    assert SCHEMA_JSON_PATH.exists(), f"找不到 Schema 文件: {SCHEMA_JSON_PATH}"
    with open(SCHEMA_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def valid_document(raw_rules_dict) -> CanonicalRulesDocument:
    """提供已成功解析的 Pydantic 文档对象"""
    return CanonicalRulesDocument.model_validate(raw_rules_dict)

# ============================================================================
# 第一防线：JSON Schema 语法校验测试
# ============================================================================

def test_json_matches_schema(raw_rules_dict, raw_schema_dict):
    """测试原生的 canonical_rules.json 必须 100% 吻合 Schema 定义"""
    try:
        validate(instance=raw_rules_dict, schema=raw_schema_dict)
    except JsonSchemaValidationError as e:
        pytest.fail(f"规范 JSON 未能通过 Schema 校验: {e.message}")

def test_schema_rejects_unknown_fields(raw_rules_dict, raw_schema_dict):
    """测试 additionalProperties: false 的防御力：夹带私货必须被拦截"""
    mutated_dict = copy.deepcopy(raw_rules_dict)
    # 试图注入一个非法字段，比如所谓的机器数量临时上限
    mutated_dict["facility_templates"]["manufacturing_3x3"]["illegal_max_count"] = 50
    
    with pytest.raises(JsonSchemaValidationError) as exc_info:
        validate(instance=mutated_dict, schema=raw_schema_dict)
    assert "illegal_max_count" in exc_info.value.message

# ============================================================================
# 第二防线：Pydantic 强类型解析测试
# ============================================================================

def test_pydantic_parsing(raw_rules_dict):
    """测试合法 JSON 必须能被 Pydantic 无损加载为强类型对象"""
    doc = CanonicalRulesDocument.model_validate(raw_rules_dict)
    assert doc.globals.grid.width == 70
    assert doc.routing_rules.bridge_mechanics.can_turn is False
    assert "hydroponics_basic" in doc.recipes

def test_pydantic_frozen_immutability(valid_document):
    """测试内存模型是否绝对不可变 (Frozen)，防止运行时业务代码篡改静态规则"""
    with pytest.raises(PydanticValidationError):
        # Pydantic V2 对 frozen 模型的修改会抛出 ValidationError
        valid_document.globals.grid.width = 999 

def test_pydantic_forbids_extra_fields(raw_rules_dict):
    """测试 extra='forbid' 机制是否生效"""
    mutated_dict = copy.deepcopy(raw_rules_dict)
    mutated_dict["globals"]["sneaky_heuristic_flag"] = True
    
    with pytest.raises(PydanticValidationError) as exc_info:
        CanonicalRulesDocument.model_validate(mutated_dict)
    assert "Extra inputs are not permitted" in str(exc_info.value)

# ============================================================================
# 第三防线：Semantic Validator 跨字段与物理真理校验测试
# ============================================================================

def test_semantic_validation_passes(valid_document):
    """合法原配规则必须顺利通过深度业务校验"""
    # 不抛异常即为通过
    validate_canonical_document(valid_document)

def test_semantic_grid_size_violation(raw_rules_dict):
    """物理真理拦截：篡改 70x70 网格尺寸"""
    mutated = copy.deepcopy(raw_rules_dict)
    mutated["globals"]["grid"]["width"] = 71
    doc = CanonicalRulesDocument.model_validate(mutated)
    
    with pytest.raises(SemanticValidationError, match="必须为 70x70"):
        validate_canonical_document(doc)

def test_semantic_manufacturing_power_violation(raw_rules_dict):
    """物理真理拦截：制造设施模板没有供电需求"""
    mutated = copy.deepcopy(raw_rules_dict)
    # 将水泵的模板（被配方引用）改为不需要供电
    mutated["facility_templates"]["manufacturing_5x5"]["needs_power"] = False
    doc = CanonicalRulesDocument.model_validate(mutated)
    
    with pytest.raises(SemanticValidationError, match="所有制造单位必须供电"):
        validate_canonical_document(doc)

def test_semantic_recipe_invalid_template(raw_rules_dict):
    """外键拦截：配方引用了不存在的实体"""
    mutated = copy.deepcopy(raw_rules_dict)
    mutated["recipes"]["water_pump_basic"]["template"] = "ghost_template"
    doc = CanonicalRulesDocument.model_validate(mutated)
    
    with pytest.raises(SemanticValidationError, match="外键冲突"):
        validate_canonical_document(doc)

def test_semantic_bridge_physics_violation(raw_rules_dict):
    """物理真理拦截：物流桥在空中转弯"""
    mutated = copy.deepcopy(raw_rules_dict)
    mutated["routing_rules"]["bridge_mechanics"]["can_turn"] = True
    doc = CanonicalRulesDocument.model_validate(mutated)
    
    with pytest.raises(SemanticValidationError, match="绝对不可转弯"):
        validate_canonical_document(doc)

def test_semantic_agricultural_closed_loop(valid_document):
    """闭环验证：确保农业无输入是合法的（无异常抛出）"""
    hydro = valid_document.recipes.get("hydroponics_basic")
    assert hydro is not None
    assert len(hydro.inputs) == 0  # 验证 inputs 为空字典

def test_semantic_recipe_no_outputs(raw_rules_dict):
    """配方逻辑拦截：配方没有任何输出（黑洞）"""
    mutated = copy.deepcopy(raw_rules_dict)
    mutated["recipes"]["smelter_steel"]["outputs"] = {}
    doc = CanonicalRulesDocument.model_validate(mutated)
    
    with pytest.raises(SemanticValidationError, match="没有任何输出"):
        validate_canonical_document(doc)

def test_semantic_recipe_self_loop(raw_rules_dict):
    """配方逻辑拦截：配方输入和输出存在同名物品（死锁）"""
    mutated = copy.deepcopy(raw_rules_dict)
    mutated["recipes"]["smelter_steel"]["inputs"]["steel_ingot"] = 1.0
    doc = CanonicalRulesDocument.model_validate(mutated)
    
    with pytest.raises(SemanticValidationError, match="无限死锁"):
        validate_canonical_document(doc)

def test_semantic_core_limits_dependency(raw_rules_dict):
    """字段依赖拦截：非 core_specific 的机器错误携带了 core_limits 字段"""
    mutated = copy.deepcopy(raw_rules_dict)
    mutated["facility_templates"]["manufacturing_3x3"]["core_limits"] = {"max_outputs": 1, "max_inputs": 1}
    doc = CanonicalRulesDocument.model_validate(mutated)
    
    with pytest.raises(SemanticValidationError, match="错误地携带了 'core_limits' 字段"):
        validate_canonical_document(doc)
