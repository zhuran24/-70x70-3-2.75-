> [!NOTE]
> **ACCEPTED_DRAFT — 本文件已与 `src/models/master_model.py` 对齐。以下标注 `[竣工图]` 的段落反映了代码实际实现与原始设计的差异。**

# 07 主摆放运筹学模型 (Master Placement Model)

## 7.1 文档目的与模型边界
本文档给出了《明日方舟：终末地》基地极值排布工程中**主问题 (Master Problem)** 的绝对代数公式化。 本模型采用 0-1 整数线性规划 / 约束编程 (ILP / CP) 范式。在"外层降序枚举 + 内层精确判定"的架构下，本模型接收外层传入的固定空地尺寸 $w \times h$，在 $70 \times 70$ 的网格中为 326 个候选刚体以及"幽灵空地"寻找一个**绝对不重叠、且 100% 满足供电覆盖**的合法坐标组合。
**【模型边界声明】**：
*   **包含域**：实体几何绝对防碰撞、幽灵空地禁区占位、供电网络闭环覆盖、同构机器对称性破除。
*   **不包含域**：**本模型绝对不计算传送带的具体走向！** 传送带路由属于子问题 (Subproblem, 见 09 章)。主问题只负责给出一个"宏观上能放下"的刚体摆放图，然后将其移交给路由子问题去验证连通性。
---

## 7.2 集合与输入参数 (Sets and Parameters)

本模型直接继承 02、05 和 06 章的静态编译数据：
*   $\mathcal{C}$：全场 4900 个可用二维网格坐标点集 $(c \in \mathcal{C})$。
*   $\mathcal{I}_{\text{man}}$：强制必选实例集合（$N=266$，包含 219台机器、1座核心、46个边界口）。
*   $\mathcal{I}_{\text{opt}}$：可选实例集合（$N=60$，包含 50个供电桩、10个协议箱）。
*   $\mathcal{I} = \mathcal{I}_{\text{man}} \cup \mathcal{I}_{\text{opt}}$：全体实体实例集合。
*   $\mathcal{P}_i$：实例 $i \in \mathcal{I}$ 的合法离散候选位姿字典（由 06 章几何引擎生成）。
*   $\mathcal{R}_{w,h}$：外层 Python 传入的，尺寸为 $w \times h$ 的幽灵空地在全图的所有合法候选位置集合（由 06 章动态生成接口提供）。
*   $\text{Occ}(p)$：位姿 $p$ 在地面层占据的绝对格子集合 $\subset \mathcal{C}$。
*   $\text{Cov}(p)$：（仅供电桩有效）位姿 $p$ 提供的 $12 \times 12$ 供电覆盖绝对格子集合 $\subset \mathcal{C}$。
---

## 7.3 系统决策变量 (Decision Variables)

模型被高度压缩为极其纯粹的 0-1 二元决策变量 (Binary Variables)，彻底消灭连续浮点坐标系：
1.  **刚体摆放变量 $z_{i,p} \in \{0, 1\}$**
    对于 $\forall i \in \mathcal{I}$, $\forall p \in \mathcal{P}_i$。当且仅当实例 $i$ 决定坐在候选坑位 $p$ 上时，值为 1。
2.  **可选实体激活变量 $x_i \in \{0, 1\}$**
    对于 $\forall i \in \mathcal{I}_{\text{opt}}$。当且仅当可选实例 $i$（如供电桩/协议箱）被系统认为有必要修建并激活时，值为 1。
    *(注：对于 $\forall i \in \mathcal{I}_{\text{man}}$，其激活状态恒等于 1，直接作为常量代入方程。)*
3.  **幽灵空地落位变量 $u_r \in \{0, 1\}$**
    对于 $\forall r \in \mathcal{R}_{w,h}$。当且仅当空地禁区最终落在候选位置 $r$ 时，值为 1。
---

## 7.4 核心绝对约束 (Hard Constraints)

### 7.4.1 存在性与唯一性约束 (Assignment Constraints)
对于强制必选的 266 个实体，它们**必须且只能**在字典里挑一个坑位：
$$ \sum_{p \in \mathcal{P}_i} z_{i,p} = 1 \quad \forall i \in \mathcal{I}_{\text{man}} $$

对于可选的 60 个供电桩和协议箱，只有当它被激活时，才能挑唯一一个坑位；若未被激活，则所有坑位变量均锁死为 0：
$$ \sum_{p \in \mathcal{P}_i} z_{i,p} = x_i \quad \forall i \in \mathcal{I}_{\text{opt}} $$

幽灵空地矩形（作为绝对不可侵犯的巨型障碍物禁区）必须且只能在地图上选定一个位置：
$$ \sum_{r \in \mathcal{R}_{w,h}} u_r = 1 $$

### 7.4.2 降维终极防撞约束 (Ultimate Set Packing Equation)
**这是本模型的心脏。** 我们反转传统碰撞计算的视角，站在"网格"的角度立规矩：
对于基地里的**每一个绝对格子坐标** $c \in \mathcal{C}$，企图占据该格子的所有刚体位姿，加起来最多只能有 1 个。无论是实体机器、供电桩本体，还是空地禁区，一律平等被作互斥占有：
$$ \sum_{i \in \mathcal{I}} \sum_{\substack{p \in \mathcal{P}_i \\ c \in \text{Occ}(p)}} z_{i,p} \ + \sum_{\substack{r \in \mathcal{R}_{w,h} \\ c \in \text{Occ}(r)}} u_r \le 1 \quad \forall c \in \mathcal{C} $$

### 7.4.3 供电网络强制覆盖蕴含约束 (Power Coverage Implication)
对于任何带有 `needs_power = true` 属性的实例 $i$（包含所有 219 台制造机与被激活的协议箱），如果它被放在了位置 $p$（即 $z_{i,p}=1$），那么**全场至少要有 1 个**被激活的供电桩 $j$ 的覆盖范围 $\text{Cov}(q)$，能与其本体 $\text{Occ}(p)$ 产生几何交集（哪怕只蹭到 1 格）。
定义布尔蕴含方程 (Indicator Constraint)：
$$ z_{i,p} \le \sum_{j \in \mathcal{I}_{\text{poles}}} \ \sum_{\substack{q \in \mathcal{P}_j \\ (\text{Occ}(p) \cap \text{Cov}(q)) \neq \emptyset}} z_{j,q} \quad \forall i \in \mathcal{I}_{\text{powered}}, \ \forall p \in \mathcal{P}_i $$

> [!NOTE]
> **[竣工图]** 代码中使用辅助变量 `powered_cell[c]` 方案替代直接蕴含。对每个格子 c 创建 `powered[c] = max(所有覆盖 c 的供电桩位姿变量)`，然后约束 `z[i,p] → powered[c]=1` for all c ∈ Occ(p)。复杂度从 O(10^9) 降至 O(78M)。并提供 `skip_power_coverage` 标志供 CI 测试。

---

## 7.5 指数级加速：对称性破除约束 (Symmetry Breaking)

必须引入**绝对字典序排列约束 (Lexicographical Ordering)**：
由于在 06 章生成的位姿字典 $\mathcal{P}_i$ 已经天然具有一个固定的数组索引 $\text{Index}(p)$。
对于任何属于同一种类模板、且担任同种配方任务的一组实例集合（如 $G_{\text{blue\_crusher}}$），对于其中相邻的实例 $k$ 与 $k+1$，强制要求：
$$ \sum_{p \in \mathcal{P}_k} \text{Index}(p) \cdot z_{k, p} \ < \ \sum_{q \in \mathcal{P}_{k+1}} \text{Index}(q) \cdot z_{k+1, q} \quad \forall k \in [1, |G|-1] $$

> [!NOTE]
> **[竣工图]** 代码中使用 CP-SAT IntVar + OnlyEnforceIf 编码：为每个实例创建 `idx_var`，通过 `OnlyEnforceIf(z)` 约束其值，然后用 `idx_k < idx_{k+1}` 实现严格字典序。数学等价但编码方式不同。

同理，对于所有可选的供电桩，强制瀑布式激活：
$$ x_k \ge x_{k+1} $$

---

## 7.6 极值下界全局割平面 (Global Valid Inequalities)

全场 219 台必选机器的总占地面积为 3325 格。单个供电桩最大不重叠覆盖面积为 $12 \times 12 = 144$ 格。
因此，覆盖全场所需的最少供电桩数量理论下界为 $\lceil 3325 / 144 \rceil = 24$。
添加全局强迫约束：
$$ \sum_{j \in \mathcal{I}_{\text{poles}}} x_j \ge 24 $$

---

## 7.7 子问题接口与 Benders 切平面预留 (Subproblem Interface)

主摆放模型本身**不求解**任何传送带的走向。它的输出是一张填满确定坐标的"答题卡"。
一旦求解引擎找到一个 Satisfiable (YES) 的可行摆放组合，它将向 **08/09 章的子问题** 发送以下刚性常量：

1. **占据网格面罩 (Occupancy Mask)**：明确告知子问题哪些格子已被刚体本体占据。
2. **绝对端口坐标字典 (Absolute Ports Dictionary)**：精确告知子问题，哪些格子的法向敞开。

如果子问题发现布线死锁，将返回 **Benders 冲突切平面 (No-good Cut)**：
$$ \sum_{i \in C} z_{i, p_i^*} \le |C| - 1 $$
主模型将收纳此切平面作为新增约束，并跳转去寻找下一个数学可行解。
