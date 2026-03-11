"""
规则数据模型 (Rules Data Models)
对应规格书：03_rule_canonicalization
用于解析、校验 canonical_rules.json 并为后续 05/06/07 章提供强类型对象接口。
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Literal, Tuple, Union
from typing_extensions import Annotated
from pydantic import BaseModel, Field, ConfigDict, model_validator

# ==========================================
# 1. 基础字面量 (Literals)
# ==========================================

Baseline = Literal["left", "bottom"]
Edge = Literal["left", "right", "bottom", "top"]
Direction = Literal["north", "south", "east", "west"]
PortRole = Literal["input", "output"]
FacilityCategory = Literal["core", "power", "boundary_io", "storage", "manufacturing"]
PowerMode = Literal["required", "not_required", "required_only_for_wireless"]

# ==========================================
# 2. 基础几何与嵌套结构 (Geometry & Base Structs)
# ==========================================

class Footprint(BaseModel):
    width: int = Field(..., ge=1)
    height: int = Field(..., ge=1)

class FootprintMode(Footprint):
    baseline: Baseline

class PlacementConstraints(BaseModel):
    inside_grid_only: Optional[bool] = None
    must_attach_to_baseline: Optional[bool] = None
    allowed_baselines: Optional[List[Baseline]] = None
    must_attach_long_edge_to_baseline: Optional[bool] = None
    max_per_baseline: Optional[int] = Field(None, ge=0)
    allow_corner_overlap: Optional[bool] = None

class ExpandOffsets(BaseModel):
    left: int = Field(..., ge=0)
    right: int = Field(..., ge=0)
    bottom: int = Field(..., ge=0)
    top: int = Field(..., ge=0)

class CoverageSpec(BaseModel):
    type: Literal["expanded_rectangle_from_footprint"]
    expand: ExpandOffsets
    powered_if_any_overlap_cell: bool

class BufferBinding(BaseModel):
    type: Literal["manufacturing", "protocol_storage_box"]

# ==========================================
# 3. 端口模式多态定义 (Polymorphic Ports Pattern)
# ==========================================

class SlotGroup(BaseModel):
    role: PortRole
    edge: Edge
    indices: List[int] = Field(..., min_length=1)

class PortsPatternNone(BaseModel):
    pattern: Literal["none"]

class PortsPatternSingleMiddle(BaseModel):
    pattern: Literal["single_middle_cell"]
    allow_unused_ports: bool

class PortsPatternCustomEdge(BaseModel):
    pattern: Literal["custom_edge_slots"]
    rotate_with_body: bool
    allow_unused_ports: bool
    slots: List[SlotGroup]

class PortsPatternSelectParallel(BaseModel):
    pattern: Literal["select_parallel_pair"]
    allowed_parallel_pairs: List[Tuple[Edge, Edge]]
    ports_per_selected_side: int = Field(..., ge=1)
    homogeneous_within_side: bool
    allow_unused_ports: bool
    multi_belt_attach_allowed: Optional[bool] = None

class PortsPatternLongSides(BaseModel):
    pattern: Literal["long_sides_only"]
    input_output_on_opposite_long_sides: bool
    ports_per_selected_side_rule: Literal["long_side_length"]
    homogeneous_within_side: bool
    allow_unused_ports: bool

# 使用 Pydantic 的 Annotated 和 Field(discriminator) 实现极其优雅的多态解析
PortsPattern = Annotated[
    Union[
        PortsPatternNone,
        PortsPatternSingleMiddle,
        PortsPatternCustomEdge,
        PortsPatternSelectParallel,
        PortsPatternLongSides
    ],
    Field(discriminator="pattern")
]

# ==========================================
# 4. 设施模板与目录 (Facility Templates & Catalog)
# ==========================================

class FacilityTemplate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    category: FacilityCategory
    display_name_zh: str
    
    footprint: Optional[Footprint] = None
    footprint_modes: Optional[List[FootprintMode]] = None
    
    solid: bool
    movable: bool
    rotatable: bool
    power_mode: PowerMode
    placement_constraints: Optional[PlacementConstraints] = None
    ports: PortsPattern
    coverage: Optional[CoverageSpec] = None
    buffers: Optional[BufferBinding] = None

    @model_validator(mode='after')
    def validate_footprint_xor_modes(self) -> 'FacilityTemplate':
        """语义校验：footprint 和 footprint_modes 必须恰好存在一个"""
        if self.footprint is None and self.footprint_modes is None:
            raise ValueError(f"Template '{self.display_name_zh}' must define either footprint or footprint_modes")
        if self.footprint is not None and self.footprint_modes is not None:
            raise ValueError(f"Template '{self.display_name_zh}' cannot define both footprint and footprint_modes")
        return self

class FacilityCatalogEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_name_zh: str
    template: str
    recipes_ref: Optional[str] = None

# ==========================================
# 5. 物流组件 (Logistics Components)
# ==========================================

class BeltSpec(BaseModel):
    size: Footprint
    requires_power: bool
    allowed_direction_pairs: List[Tuple[Direction, Direction]]

class BridgeSpec(BaseModel):
    size: Footprint
    requires_power: bool
    can_overlap_crossed_ground_belt: bool
    crossable_ground_component_types: List[str]
    requires_takeoff_or_landing_cells: bool
    can_chain_continuously: bool
    cannot_overlap_solid_entities: bool

class SplitterMergerSpec(BaseModel):
    size: Footprint
    requires_power: bool
    arity_in: int = Field(..., ge=1)
    arity_out: int = Field(..., ge=1)
    dispatch_policy: str
    modeling_hint: str

class ItemGateSpec(BaseModel):
    size: Footprint
    requires_power: bool
    unidirectional: bool
    item_filtering_supported: bool
    quantity_limit_supported: bool

class LogisticsComponentsConfig(BaseModel):
    routing_layers: List[Literal["ground", "elevated"]]
    belt: BeltSpec
    bridge: BridgeSpec
    splitter: SplitterMergerSpec
    merger: SplitterMergerSpec
    item_gate: ItemGateSpec

# ==========================================
# 6. 各项全局规则配置模块
# ==========================================

class MetaConfig(BaseModel):
    schema_name: str
    schema_version: str
    source_spec: str
    language: str

class EdgeIndexingConfig(BaseModel):
    bottom: str
    top: str
    left: str
    right: str

class LocalCoordinatesConfig(BaseModel):
    origin: Literal["bottom_left"]
    edge_indexing: EdgeIndexingConfig

class ConventionsConfig(BaseModel):
    grid_origin: Literal["bottom_left"]
    x_positive: Literal["right"]
    y_positive: Literal["up"]
    cell_unit: Literal["grid_cell"]
    tick_seconds: float = Field(..., gt=0)
    throughput_unit: Literal["items_per_tick"]
    local_coordinates: LocalCoordinatesConfig

class GridConfig(BaseModel):
    width: int = Field(..., ge=1)
    height: int = Field(..., ge=1)
    boundary_baselines: List[Baseline]
    entities_must_be_inside_grid: bool

class GlobalFlagsConfig(BaseModel):
    allow_global_dispatch_port_pooling: bool
    allow_global_intermediate_pooling: bool
    allow_unbounded_protocol_storage_boxes: bool
    fractional_machine_demand_allowed_before_rounding: bool
    machine_count_rounding_mode: Literal["ceil"]
    allow_fully_enclosed_empty_rectangle: bool
    allow_continuous_elevated_bridge: bool
    agriculture_is_self_sustained: bool
    protocol_core_extra_outputs_must_not_be_prebound_to_underclocked_capsule_line: bool

class PlacementRulesConfig(BaseModel):
    corner_overlap_allowed: bool
    solid_entities_cannot_overlap: bool
    logistics_cannot_overlap_solid_entities: bool
    boundary_storage_ports_are_inside_grid: bool
    boundary_storage_port_max_per_baseline: int

class ConnectivityRulesConfig(BaseModel):
    direct_machine_port_to_machine_port_forbidden: bool
    minimum_intermediate_logistics_cells_between_machine_ports: int
    logistics_components_can_directly_connect_to_facility_ports: bool
    same_side_ports_are_homogeneous: bool
    unused_ports_allowed: bool

class ThroughputRulesConfig(BaseModel):
    global_items_per_second_cap_per_port: float
    global_items_per_tick_cap_per_port: float
    global_items_per_second_cap_per_belt: float
    global_items_per_tick_cap_per_belt: float
    global_items_per_second_cap_inside_machine: float
    global_items_per_tick_cap_inside_machine: float
    throughput_recovery_after_blockage_is_capped: bool

class PowerRulesConfig(BaseModel):
    coverage_test: str
    power_required_categories: List[FacilityCategory]
    wireless_protocol_storage_box_requires_power: bool
    logistics_require_power: bool

class MfgBufferConfig(BaseModel):
    input_slots_rule: str
    output_slots: int
    slot_capacity: int
    manual_input_allowed: bool
    full_input_slot_blocks_matching_inbound_item_lines: bool
    full_output_slot_immediately_stops_machine: bool

class WirelessExportConfig(BaseModel):
    requires_power: bool
    interval_seconds: float
    interval_ticks: int
    destination: str
    toggle_allowed: bool

class ProtocolBoxBufferConfig(BaseModel):
    slots: int
    slot_capacity: int
    wireless_export: WirelessExportConfig

class BufferRulesConfig(BaseModel):
    manufacturing: MfgBufferConfig
    protocol_storage_box: ProtocolBoxBufferConfig

class ResourceRulesConfig(BaseModel):
    final_products_may_exit_via_any_legal_sink: bool
    protocol_storage_box_count_unbounded: bool
    protocol_storage_box_wireless_export_is_legal_final_sink: bool
    global_dispatch_ports_are_pooled: bool
    global_intermediate_products_are_pooled: bool

class AgricultureRulesConfig(BaseModel):
    self_sustained_without_external_inputs: bool
    community_blueprint_may_not_be_used_as_fixed_macro: bool

class RoundingRulesConfig(BaseModel):
    machine_count_rounding_mode: Literal["ceil"]
    fractional_machine_instances_forbidden: bool
    idle_machines_due_to_backpressure_allowed: bool

class ObjectiveRelatedFlagsConfig(BaseModel):
    empty_rectangle_may_be_fully_enclosed: bool

# ==========================================
# 7. 终极聚合入口: CanonicalRules (Root Model)
# ==========================================

class CanonicalRules(BaseModel):
    """
    终末地基建规则数据类 (Root)
    解析 canonical_rules.json 的唯一入口。
    """
    model_config = ConfigDict(extra='forbid')

    meta: MetaConfig
    conventions: ConventionsConfig
    grid: GridConfig
    global_flags: GlobalFlagsConfig
    placement_rules: PlacementRulesConfig
    connectivity_rules: ConnectivityRulesConfig
    throughput_rules: ThroughputRulesConfig
    power_rules: PowerRulesConfig
    buffer_rules: BufferRulesConfig
    
    facility_templates: Dict[str, FacilityTemplate]
    facility_catalog: Dict[str, FacilityCatalogEntry]
    logistics_components: LogisticsComponentsConfig
    
    resource_rules: ResourceRulesConfig
    agriculture_rules: AgricultureRulesConfig
    rounding_rules: RoundingRulesConfig
    objective_related_flags: ObjectiveRelatedFlagsConfig
    feasibility_requirements: List[str]

    @classmethod
    def load_from_file(cls, filepath: Union[str, Path]) -> "CanonicalRules":
        """工厂方法：从 JSON 文件加载并强制执行全部结构与语义验证"""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"规则文件未找到: {path}")
            
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # 1. 实例化并触发 Pydantic 结构级校验
        instance = cls.model_validate(data)
        # 2. 触发二次物理几何语义校验
        instance.run_semantic_validations()
        
        return instance

    def run_semantic_validations(self):
        """
        执行所有不适合写在静态 JSON Schema 中的复杂二次几何/语义校验。
        确保后续模块拿到的数据在物理上绝对自洽。
        """
        self._validate_protocol_core_ports()
        self._validate_power_pole_coverage()

    def _validate_protocol_core_ports(self):
        """几何校验：协议核心的预设端口槽位索引决不能越出 9x9 的范围"""
        core = self.facility_templates.get("protocol_core")
        if core and core.footprint and isinstance(core.ports, PortsPatternCustomEdge):
            for slot in core.ports.slots:
                max_index = core.footprint.width - 1 if slot.edge in ["bottom", "top"] else core.footprint.height - 1
                for idx in slot.indices:
                    if idx < 0 or idx > max_index:
                        raise ValueError(f"协议核心端口索引 {idx} 超出了边 {slot.edge} 的几何上限 (最大 {max_index})。")

    def _validate_power_pole_coverage(self):
        """几何校验：供电桩 2x2 本体 + 上下左右各外延 5 格必须严格等于 12x12"""
        pole = self.facility_templates.get("power_pole")
        if pole and pole.coverage and pole.footprint:
            exp = pole.coverage.expand
            total_w = pole.footprint.width + exp.left + exp.right
            total_h = pole.footprint.height + exp.top + exp.bottom
            if total_w != 12 or total_h != 12:
                raise ValueError(f"供电桩覆盖区域理论上必须是 12x12，但当前几何参数计算结果为 {total_w}x{total_h}。")