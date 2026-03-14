"""
Pydantic V2 Models for Canonical Rules & Facility Templates.
Status: ACCEPTED_DRAFT (Frozen semantic mapping for src/rules)

目标：提供 JSON 静态规则底座到 Python 运行时的强类型、不可变反序列化映射。
禁止包含任何实例数量推导逻辑、启发式参数或非静态运行时属性。
"""

from typing import Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat

# -----------------------------------------------------------------------------
# 1. Base Configurations
# -----------------------------------------------------------------------------

class StrictBaseModel(BaseModel):
    """全局基类：严格拒绝任何未知字段注入，并保证加载后实例绝对不可变。"""
    model_config = ConfigDict(
        extra="forbid",
        frozen=True
    )

# -----------------------------------------------------------------------------
# 2. Globals & Environment Constants
# -----------------------------------------------------------------------------

class GridConfig(StrictBaseModel):
    width: int = Field(..., ge=1)
    height: int = Field(..., ge=1)

class TimeConfig(StrictBaseModel):
    tick_interval_seconds: PositiveFloat

class LogisticsConfig(StrictBaseModel):
    belt_capacity_per_tick: PositiveFloat
    port_max_throughput_per_tick: PositiveFloat
    machine_min_clearance_cells: int = Field(..., ge=0)

class GlobalsConfig(StrictBaseModel):
    grid: GridConfig
    time: TimeConfig
    logistics: LogisticsConfig

# -----------------------------------------------------------------------------
# 3. Routing Rules
# -----------------------------------------------------------------------------

class LayersConfig(StrictBaseModel):
    ground: Literal[0] = 0
    elevated: Literal[1] = 1

class BridgeMechanicsConfig(StrictBaseModel):
    can_overlap_solid: bool
    can_overlap_straight_belt: bool
    can_overlap_curved_belt: bool
    can_overlap_splitter_merger: bool
    can_turn: bool

class RoutingRulesConfig(StrictBaseModel):
    layers: LayersConfig
    bridge_mechanics: BridgeMechanicsConfig

# -----------------------------------------------------------------------------
# 4. Facility Templates
# -----------------------------------------------------------------------------

class Dimensions(StrictBaseModel):
    w: int = Field(..., ge=1)
    h: int = Field(..., ge=1)

class CoreLimits(StrictBaseModel):
    max_outputs: int = Field(..., ge=0)
    max_inputs: int = Field(..., ge=0)

PortRuleType = Literal[
    "opposite_parallel_sides",
    "long_sides",
    "core_specific",
    "omni_wireless",
    "none",
    "inward_facing"
]

class FacilityTemplate(StrictBaseModel):
    """
    定义设施模板的物理包围盒与能力限制。
    必须与 canonical_rules.schema.json 定义完美契合。
    """
    dimensions: Dimensions
    rotatable: bool
    needs_power: bool
    is_solid_z: bool
    port_rule: PortRuleType
    
    # 针对特定 port_rule 或特定设施的扩展字段
    core_limits: Optional[CoreLimits] = None
    power_coverage_radius: Optional[int] = Field(default=None, ge=0)
    placement_rule: Optional[Literal["left_or_bottom_boundary"]] = None

# -----------------------------------------------------------------------------
# 5. Recipes
# -----------------------------------------------------------------------------

class Recipe(StrictBaseModel):
    """
    定义制造配方的理论吞吐周期与 IO 速率。
    inputs 与 outputs 的 value 强制为正数 (PositiveFloat)。
    """
    template: str
    ticks_per_cycle: int = Field(..., ge=1)
    
    # 默认允许空字典 {} 的传入，完美契合农业设施内部闭环无输入的物理设定。
    inputs: Dict[str, PositiveFloat] = Field(default_factory=dict)
    outputs: Dict[str, PositiveFloat] = Field(default_factory=dict)

# -----------------------------------------------------------------------------
# 6. Root Canonical Rules Document
# -----------------------------------------------------------------------------

class MetadataConfig(StrictBaseModel):
    version: str
    description: str

class CanonicalRulesDocument(StrictBaseModel):
    """
    代表已解析完毕的 rules/canonical_rules.json 的根对象。
    调用 CanonicalRulesDocument.model_validate_json(json_str) 实例化。
    """
    # 兼容 JSON 文件头部的 Schema 声明导入
    schema_url: Optional[str] = Field(default=None, alias="$schema")
    
    metadata: MetadataConfig
    globals: GlobalsConfig
    routing_rules: RoutingRulesConfig
    facility_templates: Dict[str, FacilityTemplate]
    recipes: Dict[str, Recipe]