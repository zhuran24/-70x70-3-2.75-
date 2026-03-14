> [!NOTE]
> **ACCEPTED_DRAFT — 本文件已与 `src/models/routing_subproblem.py` 对齐。变量体系已简化为 CP-SAT BoolVar 编码。MUC 提取接口已预留但返回 None ([TBD])。**

# 09 逐格精确路由子问题 (Exact Grid Routing Subproblem)

## 9.1 文档目的与模型边界

本文档确立了逻辑型 Benders 分解 (LBBD) 架构中的**第二级验证子问题 (Second-Stage Exact Subproblem)**，即最终的微观物理布线阶段。

当主摆放模型 (07 章) 给定实体布局 $\mathbf{z}^*$，且该布局通过了宏观拓扑流 (08 章) 的可行性粗筛后，本模型将接管全场的离散网格。本模型的任务是：在真实游戏物理规则下，为所有激活的物理端口铺设一条或多条离散的、有向的、不相撞的、满足容量与桥接规则的 $1 \times 1$ 物流组件（传送带、分流器、汇流器、物流桥）网络。

**【模型边界声明】**：
*   **包含域**：单向带方向连续性、多商品微观不相交路径 (Disjoint Paths)、真三维高架桥连续跨越、制造单位出入口至少 1 格缓冲强制规则、公共资源池的端到端精确定位。
*   **不包含域**：**绝对不再更改任何刚体实体的位置！** 机器、供电桩、边界口、空地禁区在本模型中已被视作具有无穷高 Z 轴属性的绝对刚体障碍物。

---

## 9.2 真 3D 离散路由张量域 (3D Routing Tensor Space)

### 9.2.1 物理路由层级 ($\mathcal{L}$)
依据 02 章定义，路由空间为 $\mathcal{C} \times \mathcal{L}$，其中 $\mathcal{C}$ 为 $70 \times 70$ 网格，层级 $L \in \{0, 1\}$：
*   $L = 0$：地面层 (Ground Level)。承载普通传送带、分流器、汇流器、准入口。
*   $L = 1$：高架层 (Elevated Level)。仅承载连续拼接的物流桥。

### 9.2.2 离散路由决策变量 (Routing Variables)
对于每一个网格点 $c \in \mathcal{C}$，层级 $L \in \{0,1\}$，方向 $d \in \{N, S, E, W\}$，商品类别 $k \in \mathcal{K}$，引入极其纯粹的离散 0-1 变量：
$$ r_{c, L, d_{\text{in}}, d_{\text{out}}}^k \in \{0, 1\} $$
**语义**：当且仅当在格子 $c$ 的层级 $L$ 上，放置了一个物流设施，使得商品 $k$ 从方向 $d_{\text{in}}$ 流入，并从方向 $d_{\text{out}}$ 流出时，该变量为 1。
*(约束：传送带必须有明确的进出，强制 $d_{\text{in}} \neq d_{\text{out}}$，天然涵盖了 4 种直带和 8 种弯带。起终点接入机器时，允许 $d_{\text{in}}$ 或 $d_{\text{out}}$ 为空 $\emptyset$。)*

---

## 9.3 核心微观物理法则约束 (Micro-Physics Hard Constraints)

本模型采用极度严苛的布尔可满足性 (SAT) 约束，一比一复刻游戏内部的建造限制。

### 9.3.1 实体刚体绝对排斥规则 (Solid Obstacle Exclusion)
设 $\Omega_{\text{solid}}$ 为 07 章主模型 $\mathbf{z}^*$ 确定的所有刚体占据的绝对坐标集合。对于 $\forall c \in \Omega_{\text{solid}}$，该坐标的地面与高架层**全部锁死**：
$$ \sum_{L \in \{0,1\}} \sum_{k \in \mathcal{K}} \sum_{d_{\text{in}}, d_{\text{out}}} r_{c, L, d_{\text{in}}, d_{\text{out}}}^k = 0 \quad \forall c \in \Omega_{\text{solid}} $$

### 9.3.2 离散信道单占与防撞约束 (Capacity & Collision-Free)
每一层级的每一个独立格子，最多只能铺设一种方向组合、运送一种商品的一条带子：
$$ \sum_{k \in \mathcal{K}} \sum_{d_{\text{in}} \neq d_{\text{out}}} r_{c, L, d_{\text{in}}, d_{\text{out}}}^k \le 1 \quad \forall c \notin \Omega_{\text{solid}}, \forall L \in \{0, 1\} $$

### 9.3.3 真 3D 物流桥高架规则 (Elevated Bridge Mechanics)
物流桥可以在 $L=1$ 层连续拼接，但必须遵守其对 $L=0$ 层的投影依赖关系：
1. **直线强制律**：高架层 $L=1$ 的路由变量仅允许 $d_{\text{in}}$ 与 $d_{\text{out}}$ 相对的形态（如南北直行、东西直行）。**物流桥严禁转弯。**
2. **高架悬空合法性**：若某格子 $L=1$ 层有桥，则其正下方 $L=0$ 层要么为空，要么只能是一条**直线传送带 (Straight Belt)**。
3. **无缝起降合法性**：物流桥的两端必须能与 $L=0$ 层的非实体格子发生无缝层级接驳，无需占用额外的起降坡道格子。

### 9.3.4 微观流体方向连续性定律 (Directional Continuity)
对于除了物理端口之外的所有自由物流格子，必须满足方向匹配的基尔霍夫定律：
如果格子 $c$ 在 $L$ 层向 $d_{\text{out}}$ 方向输出物料 $k$，则相邻格 $c'$ 在接驳层级 $L'$ 必须存在一个接收该物料、且流入方向 $d_{\text{in}} = \text{Opp}(d_{\text{out}})$ 的组件。

### 9.3.5 机器出入口至少相隔1格规则 (The 1-Cell Minimum Gap Rule)
依据 03 章 3.6.3 节规则，制造单位的出口与任何单位的入口不可实现"零距离"面对面硬连：
所有的管线，从机器物理边界离开后，必须至少踩中 1 个属于 $\mathcal{V}_{\text{free}}$ 的物流格子，才能再次进入下一台机器的物理边界。

---

## 9.4 端口度数履行与公共资源池寻路 (Port Adherence & Pooling)

### 9.4.1 端口度数强制履行 (Degree Adherence)
04 章 4.8 节下达的机器度数矩阵必须被绝对执行：
若 07 章规定实例 $i$ 的某条输出边分配了 $N$ 个出口，则该边上的物理边缘节点向外发射的路由变量总和必须**精确等于** $N$。

### 9.4.2 全局资源软连接 (Global Pooling Soft-Matching)
在本路由子问题中，彻底兑现 03 章关于"不硬绑定专线"的承诺。
**路由引擎的终极任务**：在 $\mathcal{C} \times \mathcal{L}$ 的张量网格中，为所有物流带找到无交集、无方向冲突的连通子图。求解器自动计算出最顺畅的连接拓扑。

---

## 9.5 失败提取与微观组合切平面 (MUC & Benders Cuts)

### 9.5.1 极小不可满足核 (MUC / IIS) 提取
现代 SAT 求解器在返回 UNSAT 时，能够回溯推导并提取出导致无解的 **极小不可满足核心 (Minimal Unsatisfiable Core, MUC)**。

### 9.5.2 微观几何冲突切平面 (Micro-Geometric No-Good Cut)
锁定构成 MUC 的具体实体实例集合 $\Omega_{\text{micro}} \subset \mathcal{I}$ 及其在当前失败解中的位姿 $p_i^*$。
路由子问题向主摆放模型发回一条最高优先级的永久排斥切平面：
$$ \sum_{i \in \Omega_{\text{micro}}} z_{i, p_i^*} \le |\Omega_{\text{micro}}| - 1 $$

---

## 9.6 终极验收与蓝图生成 (Ultimate Acceptance)

如果本模型返回 **SATISFIABLE (YES)**，系统将提取全量 0-1 决策变量，输出包含以下信息的**终极蓝图**：
1.  **326 个刚体的绝对位姿与朝向**（源自 07 章主问题）。
2.  **$70 \times 70 \times 2$ 空间内每一个物流组件的类型、坐标、朝向、承载物料**（源自本章微观解）。
