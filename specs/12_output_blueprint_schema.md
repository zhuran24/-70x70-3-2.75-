> [!NOTE]
> **ACCEPTED_DRAFT — 本文件已与 `src/render/blueprint_exporter.py` 对齐。**

# 12 终极蓝图输出规范与数据契约 (Ultimate Blueprint Output Schema)

## 12.1 文档目的与适用范围

本文档是《明日方舟：终末地》基地极值排布工程的**最终交付数据契约 (Data Contract)**。
当全局流水线 (11 章) 宣告寻得全局最优解后，必须将内存中数以百万计的运筹学 0-1 决策变量，逆向解析并序列化为一份绝对标准化的 JSON 蓝图文件。

本文档严格定义了该 JSON 文件的嵌套结构、字段命名与枚举空间。任何下游应用（如二维 ASCII 渲染器、三维游戏内自动建造 Mod、或者网页版布局规划器）均必须且只能依据本规范解析数据。

---

## 12.2 全局 JSON 骨架结构 (Global Skeleton)

输出文件强制命名为 `optimal_blueprint.json`，存储于 `data/blueprints/` 目录下。
其根节点必须包含四大核心域：

```json
{
  "metadata": { },
  "objective_achieved": { },
  "facilities": [ ],
  "routing_network": { }
}
```

---

## 12.3 元数据与目标极值域 (Metadata & Objective)

记录该极值蓝图的全局业务得分、求解耗时以及最核心的"幽灵空地"战果。

```json
{
  "metadata": {
    "version": "1.0.0",
    "solve_time_seconds": 12450.5,
    "benders_iterations": 84
  },
  "objective_achieved": {
    "empty_rect": {
      "w": 16,
      "h": 10,
      "anchor_x": 35,
      "anchor_y": 40,
      "score": 161.0
    }
  }
}
```

---

## 12.4 绝对刚体花名册域 (Facilities Domain)

包含所有被激活实体（266个必选机组 + 被 07 章主模型激活的供电桩/协议箱）的 Array。所有坐标均严格遵循 02 章的**旋转后包围盒左下角锚定法**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `instance_id` | string | 全局唯一实例标识 |
| `facility_type` | string | 设施模板名称 |
| `anchor` | `{x, y}` | 旋转后包围盒左下角绝对坐标 |
| `orientation` | int (0-3) | 旋转状态 |
| `port_mode` | string | 端口分配模式 |
| `active_ports` | array | 由 09 章微观路由决定的真正接管端口 |

每个 `active_ports` 元素：

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | `"input"` / `"output"` | 端口方向 |
| `x`, `y` | int | 端口绝对坐标 |
| `dir` | `"N"/"S"/"E"/"W"` | 对外法向量 |
| `commodity` | string | 承载物料名称 |

---

## 12.5 真三维物流路由网格域 (Routing Network Domain)

由 09 章 SAT 求解器逐格铺设的离散物流骨架。分为地面层 (`L0_ground`) 与高架层 (`L1_elevated`)，采用以坐标字符串 `"x,y"` 为 Key 的 Hash Map 结构。

每个路由格元素：

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | `"belt"/"splitter"/"merger"/"bridge"` | 物流组件类型 |
| `commodity` | string | 承载物料名称 |
| `flow_in` | array of `"N"/"S"/"E"/"W"` | 物料流入本格的方向 |
| `flow_out` | array of `"N"/"S"/"E"/"W"` | 物料流出本格的方向 |

> [!NOTE]
> 高架层 `L1_elevated` 中 `type` 强制为 `"bridge"`，且 `flow_in` 与 `flow_out` 必为绝对反向（物流桥不可转弯）。

---

## 12.6 数据合法性后验断言 (Validation Postulates)

在最终序列化前，11 章的总控引擎必须执行三重断言：

1. **左下角越界断言**：所有 `anchor` 的 `x` 与 `y` $\ge 0$。包围盒最远端 $\le 69$。
2. **绝对防撞断言**：`facilities` 中所有实体占据格集合与 `empty_rect` 占据格集合，两两交集为空。
3. **路由悬空断言**：`L1_elevated` 中任意坐标在 `L0_ground` 中必须为空或为直线传送带。
