> [!NOTE]
> **ACCEPTED_DRAFT — 本文件已与 `src/models/flow_subproblem.py` 对齐。`[竣工图]` 标注反映代码实际状态。**

# 08 宏观拓扑流子问题 (Topological Flow Subproblem)

## 8.1 文档目的与模型边界
本文档确立了逻辑型 Benders 分解 (Logic-based Benders Decomposition, LBBD) 架构中的**第一级验证子问题 (First-Stage Subproblem)**。
在主摆放模型 (07 章) 吐出一个确定的刚体布局方案 $\mathbf{z}^*$ 后，系统**绝对不应**直接进入极度耗时的逐格物理布线搜索 (09 章)。本章旨在构建一个基于网格剩余空白空间的**连续多商品流拓扑网络 (Continuous Multi-Commodity Flow, MCF)**，利用多项式时间复杂度的线性规划 (LP)，快速侦测并拦截那些存在"宏观截面流量瓶颈（Bottleneck）"的绝对废解（例如机器挤成铁桶胡同导致物料无法进出）。
**【模型边界声明】**：
*   **包含域**：全局资源池化的供需匹配验证、物理拓扑缺口的极限流量验证、基于 Farkas 引理的 Benders 冲突切平面生成。
*   **不包含域**：**不计算传送带的具体方向与种类！不区分分流器与物流桥的微观排列！不考虑制造单元出入口至少间隔 1 格的微物理限制！** 本模型仅将未被占据的格子视为连通图中的流体管道（Capacity Pipes），进行连续松弛流验证。
---

## 8.2 拓扑流网络图构建 (Flow Graph Construction)

给定主模型传递的当前确定性摆放解 $\mathbf{z}^*$，全场 4900 个格子的占据状态已知。我们据此构建一个有向网络流图 $\mathcal{G} = (\mathcal{V}, \mathcal{E})$。
### 8.2.1 节点集合 ($\mathcal{V}$)
1.  **自由网格节点 $\mathcal{V}_{\text{free}}$**：所有未被任何绝对刚体（实体机器、供电桩、幽灵空地）覆盖的空白格子。
2.  **物理端口节点 $\mathcal{V}_{\text{port}}$**：所有被激活机器暴露在外的、合法的物理输入/输出边缘格。
3.  **超级源点与超级汇点 ($\mathcal{V}_{\text{super}}$)**：为实现 03/04 章设定的**"全局物料池化"**，对每一种独立物料 $k \in \mathcal{K}$（如蓝铁矿、钢块），在物理网格之外凭空创建一对超级源点 $S_k$ 与超级汇点 $T_k$。
### 8.2.2 边集合与宏观容量 ($\mathcal{E}$ & $C_e$)
定义网络中的拓扑边及其稳态容量上限（单位：个/Tick）：
1.  **空间邻接边 (Space Edges)**：
    对于 $\mathcal{V}_{\text{free}}$ 中任意两个四邻域（上下左右）相邻的格子 $u, v$，建立双向有向边 $(u,v)$ 和 $(v,u)$。
    *   **容量 $C_{u,v} = 2.0$**：由于 09 章允许地面层($L=0$)与高架层($L=1$)独立布线且可真三维重叠，两个相邻空白格子之间的物理边界在宏观上最多可并行承载 2 条满载物流流。
2.  **端口接入/接出边 (Port Edges)**：
    端口节点 $p \in \mathcal{V}_{\text{port}}$ 仅与其法向量朝向的正前方那一格相邻空格建立有向边（若为出口则 $p \to v$，若为入口则 $v \to p$）。
    *   **容量 $C_{p,v} = 1.0$ 或 $C_{v,p} = 1.0$**：代表物理端口本身的极限吞吐不可叠加。若端口正前方被其他机器堵死，该边直接断开（即面对死锁）。
3.  **超级源汇映射边 (Super-node Edges)**：
    *   从超级源点 $S_k$ 向全场所有*提供该物料 $k$ 的物理出口端口*连有向边，边容量为该出口分配的度数上限（本系统中通常为 $1.0$ 或 $0.5$）。
    *   从全场所有*需求该物料 $k$ 的物理入口端口*向超级汇点 $T_k$ 连有向边，边容量为该入口分配的度数上限。
---

## 8.3 连续多商品流线性规划约束 (Continuous MCF Formulation)

本层使用极其快速的纯线性规划 (Pure LP) 引擎进行流体力学仿真，彻底放弃 0-1 离散变量。
定义连续变量 $f_{u,v}^k \ge 0$ 表示物料 $k \in \mathcal{K}$ 在有向边 $(u,v) \in \mathcal{E}$ 上的稳态流量。
### 8.3.1 供需满足约束 (Demand Fulfillment)
依据 04 章 4.8 节给定的实例化拓扑度数矩阵，物料 $k$ 的全局总流率需求为 $D_k$（例如全局共需 34 个蓝铁矿/Tick）。
系统强制要求该网络必须能够跑满这个宏观吞吐量：
$$ \sum_{v \in \text{Outputs}(k)} f_{S_k, v}^k = D_k \quad \forall k \in \mathcal{K} $$
$$ \sum_{u \in \text{Inputs}(k)} f_{u, T_k}^k = D_k \quad \forall k \in \mathcal{K} $$

### 8.3.2 节点流量守恒 (Flow Conservation)
对于网络中任何一个非超级源汇的中间节点 $v \in \mathcal{V}_{\text{free}} \cup \mathcal{V}_{\text{port}}$ 及任意物料 $k$，流入总量必须等于流出总量（不可在空间中凭空消失或生成）：
$$ \sum_{u:(u,v) \in \mathcal{E}} f_{u,v}^k - \sum_{w:(v,w) \in \mathcal{E}} f_{v,w}^k = 0 \quad \forall k \in \mathcal{K}, \ \forall v $$

### 8.3.3 共享信道截面容量约束 (Shared Channel Capacity)
**（这是逼迫死胡同与铁桶阵现出原形的杀手锏方程）**
不同物料的流可以自由共享空白网格的拓扑空间，但总物理带宽不可超越空间极限。对于任意一对相邻的物理格子 $(u,v)$：
$$ \sum_{k \in \mathcal{K}} (f_{u,v}^k + f_{v,u}^k) \le C_{u,v} \quad \forall \text{ adjacent } u,v \in \mathcal{V}_{\text{free}} $$
*(物理语义：同一对相邻空格之间，无论混杂了多少种不同的商品，无论双向怎么交错，总流量绝对不能超过地面+高架的合并带宽 2.0)*

---

## 8.4 判定结果与 Benders 切平面生成 (Infeasibility & Cut Generation)

将上述连续变量模型提交给 LP 求解器（如 GLOP, PDLP 或 CPLEX），可在数毫秒到数十毫秒内返回确切状态：

### 8.4.1 状态 A：网络流合法 (Feasible)
若 LP 存在可行解，说明主模型给出的摆放草图在宏观流体力学上是畅通的，拥有足够宽阔的物理走廊。
**流转动作**：
1. 将当前的机器摆放草图 $\mathbf{z}^*$ 正式放行，移交给 **09 章 (精确逐格路由子问题)** 进行真刀真枪的三维传送带铺设验证。
2. LP 求解出的连续流分布矩阵 $\mathbf{F}^*$ 将作为 09 章的**启发式费洛蒙 (Heuristic Pheromone)**，直接限定物料的大致流向，极大加速离散路由搜索。
### 8.4.2 状态 B：网络流崩溃 (Infeasible)
若 LP 模型无解（最大流无法达到目标需求 $D_k$），说明当前布局一定存在致命的物理瓶颈（例如：机器簇之间的缝隙太窄导致物流严重拥堵；或 52 个原矿口被工厂城墙堵死在边缘进不来）。
**流转动作**：必须触发 **Benders 切平面反馈** 驳回该图纸，**绝对不进入 09 章的盲目穷举**。
1. **基于 Farkas 引理的瓶颈提取 (Farkas' Certificate / Min-Cut)**：
   提取 LP 求解器返回的对偶不可行射线 (Dual Infeasible Ray)。根据最大流最小割定理，该射线在物理几何上精确对应了流网络中的**"最小割集 (Min-Cut)"**——即那些达到容量饱和并彻底阻断流量的物理格子界限。
2. **锁定罪魁祸首刚体 ($\Omega_{\text{bottleneck}}$)**：
   识别出构成该最小割瓶颈周围的所有实体刚体障碍物集合 $\Omega_{\text{bottleneck}} \subset \mathcal{I}$。正是由于这些机器（或空地）卡在这里，挤占了原本属于物流通道的空间。
3. **生成拓扑拒斥切平面 (Topological No-Good Cut)**：
   提取这些机器在当前失败解中的位姿集合 $\{ p_i^* \mid i \in \Omega_{\text{bottleneck}} \}$。向 07 章主摆放模型发送一条永久生效的 Benders 组合切平面约束：
   $$ \sum_{i \in \Omega_{\text{bottleneck}}} z_{i, p_i^*} \le |\Omega_{\text{bottleneck}}| - 1 $$
   **【切平面数学语义】**： 主模型你听好了：在接下来的所有搜索中，**绝对不允许**同时把这几台机器按当前的位姿摆放！你们把通道堵死了！必须至少移走其中一台机器，或者把它们旋转腾出空间！

> [!NOTE]
> **[竣工图]** Farkas 对偶不可行射线提取在代码中尚未实现（`extract_bottleneck_cells()` 返回空集）。当前的退化方案是将整个失败解作为 no-good 切面（见 `cut_manager.py:extract_nogood_from_solution`）。这比 Farkas 精细提取弱很多，但保证正确性。[TBD] 待路由层完成后补充实现。

---

## 8.5 本章对全局池化原则的数学保障 (Pooling Assignment)

本章模型完美兑现了 03 章中确立的**"全局物料池化、无硬绑定专线"**的承诺。
在 MCNF 模型中，所有的粉碎机都向同一个超级源点 $S_{\text{powder}}$ 汇入粉末，所有的研磨机都从该节点抽取粉末。
**LP 求解器会根据最小流体阻力原则 (Minimum Resistance Principle)，自动将最近的粉碎机与研磨机在拓扑中被"软配对"**。如果 07 章布局混乱（如供需两端横跨地图且中间无通道），模型将轻易触发中部物理网格流量上限而宣告 Infeasible。这会通过 Benders Cut 逼迫 07 章主模型在迭代中自发地将上下游机器"靠拢"排布，最终涌现出极高的工业排布智能。
