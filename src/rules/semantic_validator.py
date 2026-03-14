"""
Semantic Validator for Canonical Rules.
Status: ACCEPTED_DRAFT

目标：执行 JSON Schema 和 Pydantic 无法原生处理的跨字段与跨对象逻辑校验。
拦截违反《明日方舟：终末地》冻结物理法则的非法静态数据设定。
"""

from typing import List
from src.rules.models import CanonicalRulesDocument

class SemanticValidationError(ValueError):
    """当静态规则底座违反跨字段业务语义或冻结真理时抛出。"""
    pass

class CanonicalSemanticValidator:
    def __init__(self, doc: CanonicalRulesDocument):
        self.doc = doc
        self.errors: List[str] = []

    def validate(self) -> None:
        """执行所有语义级校验，若有违反则合并报错并抛出异常。"""
        self.errors.clear()
        
        self._check_frozen_constants()
        self._check_recipe_template_references()
        self._check_manufacturing_power_requirements()
        self._check_port_rule_dependencies()
        self._check_recipe_io_sanity()

        if self.errors:
            error_msg = "\n".join([f"  - {err}" for err in self.errors])
            raise SemanticValidationError(
                f"规则字典未通过深层语义校验，发现 {len(self.errors)} 个致命冲突:\n{error_msg}"
            )

    def _check_frozen_constants(self):
        """规则 1：硬性物理常数校验。确保加载的 JSON 没有篡改 PROJECT_LOCK.md 中的真理。"""
        if self.doc.globals.grid.width != 70 or self.doc.globals.grid.height != 70:
            self.errors.append("违反冻结真理：主基地必须为 70x70 离散网格。")
        
        if self.doc.globals.time.tick_interval_seconds != 2.0:
            self.errors.append("违反冻结真理：基础时间单位必须为 1 tick = 2.0 秒。")

        bridge = self.doc.routing_rules.bridge_mechanics
        if not bridge.can_overlap_straight_belt:
            self.errors.append("违反冻结真理：物流桥必须允许真三维重叠跨越直线传送带 (can_overlap_straight_belt 必须为 True)。")
        if bridge.can_turn:
            self.errors.append("违反冻结真理：物流桥在空中绝对不可转弯 (can_turn 必须为 False)。")

        for tpl_id, tpl in self.doc.facility_templates.items():
            if tpl.port_rule == "core_specific" and not tpl.rotatable:
                self.errors.append(f"违反冻结真理：协议核心必须可移动、可旋转。模板 '{tpl_id}' 的 rotatable 为 False。")

    def _check_recipe_template_references(self):
        """规则 2：外键一致性。配方引用的 template 必须在 facility_templates 中真实存在。"""
        templates = self.doc.facility_templates
        for recipe_id, recipe in self.doc.recipes.items():
            if recipe.template not in templates:
                self.errors.append(
                    f"外键冲突：配方 '{recipe_id}' 引用了不存在的模板 '{recipe.template}'。"
                )

    def _check_manufacturing_power_requirements(self):
        """规则 3：冻结真理执行。所有被配方（制造单位）引用的设施模板，必须强制要求供电。"""
        templates = self.doc.facility_templates
        for recipe_id, recipe in self.doc.recipes.items():
            tpl = templates.get(recipe.template)
            if tpl and not tpl.needs_power:
                self.errors.append(
                    f"违反冻结真理：配方 '{recipe_id}' 引用的制造设施模板 '{recipe.template}' "
                    f"被标记为不需要供电 (needs_power=False)。所有制造单位必须供电。"
                )

    def _check_port_rule_dependencies(self):
        """规则 4：互斥字段依赖。特定 port_rule 必须与特定的扩展字段严格绑定。"""
        for tpl_id, tpl in self.doc.facility_templates.items():
            # 协议核心判定
            if tpl.port_rule == "core_specific":
                if tpl.core_limits is None:
                    self.errors.append(f"字段约束冲突：模板 '{tpl_id}' 指定了 'core_specific' 端口规则，但缺失 'core_limits' 字段。")
            else:
                if getattr(tpl, "core_limits", None) is not None:
                    self.errors.append(f"字段约束冲突：模板 '{tpl_id}' 的端口规则不是 'core_specific'，但错误地携带了 'core_limits' 字段。")

            # 供电设施不耗电判定
            if getattr(tpl, "power_coverage_radius", None) is not None:
                if tpl.needs_power:
                    self.errors.append(f"违反冻结真理：模板 '{tpl_id}' 提供了供电半径，但其自身要求供电 (needs_power=True)。供电/物流设施不需要供电。")

            # 边界口判定
            if getattr(tpl, "placement_rule", None) == "left_or_bottom_boundary":
                if tpl.port_rule != "inward_facing":
                    self.errors.append(
                        f"字段约束冲突：模板 '{tpl_id}' 位于边界 (left_or_bottom_boundary)，"
                        f"必须强制配置为向内侧开放端口 (inward_facing)。"
                    )

    def _check_recipe_io_sanity(self):
        """规则 5：配方合理性。配方可以无输入（农业闭环），但必须有输出。"""
        for recipe_id, recipe in self.doc.recipes.items():
            if not recipe.outputs:
                self.errors.append(f"配方死环：配方 '{recipe_id}' 没有任何输出，违反了节点连通性。")
            
            overlap = set(recipe.inputs.keys()).intersection(set(recipe.outputs.keys()))
            if overlap:
                self.errors.append(f"配方死锁：配方 '{recipe_id}' 存在自循环的同名物品 {overlap}，将导致无限死锁。")

def validate_canonical_document(doc: CanonicalRulesDocument) -> None:
    """提供给外层的快捷校验入口"""
    validator = CanonicalSemanticValidator(doc)
    validator.validate()
