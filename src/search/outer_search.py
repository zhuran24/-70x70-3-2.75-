"""
Outer search（外层搜索） for the maximum empty rectangle objective（最大连续矩形空地目标）.

核心原则：
1. certified_exact（严格认证精确）默认开启。
2. exact 路径只使用 safe static occupied-area lower bound（安全静态占地下界）。
3. 支持 exact campaign（精确战役）恢复与 168 小时级断点续跑。
4. exploratory（探索）结果不得冒充 certified exact（严格认证精确）结果。
"""

from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.models.cut_manager import (
    RUN_STATUS_CERTIFIED,
    RUN_STATUS_INFEASIBLE,
    RUN_STATUS_UNKNOWN,
    RUN_STATUS_UNPROVEN,
)
from src.models.master_model import load_generic_io_requirements_artifact, load_project_data
from src.search.benders_loop import (
    ExactSearchSession,
    compute_exact_static_area_lower_bound,
    run_benders_for_ghost_rect,
)
from src.search.exact_campaign import ExactCampaign

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTIER_SELECTION_POLICY = "certification_prune_per_anchor_v1"


def _normalize_solve_mode(
    solve_mode: Optional[str] = None,
    certification_mode: Optional[bool] = None,
) -> str:
    if certification_mode is not None:
        return "certified_exact" if certification_mode else "exploratory"
    if solve_mode is None:
        return "certified_exact"
    if solve_mode not in {"certified_exact", "exploratory"}:
        raise ValueError(f"Unsupported solve mode（不支持的求解模式）: {solve_mode}")
    return solve_mode


def generate_candidate_sizes(
    *,
    max_w: int = 70,
    max_h: int = 70,
    min_side: int = 6,
    max_aspect_ratio: Optional[float] = None,
    area_upper_bound: Optional[int] = None,
) -> List[Tuple[int, int, int]]:
    candidates: List[Tuple[int, int, int]] = []
    for w in range(min_side, max_w + 1):
        for h in range(min_side, min(max_h, w) + 1):
            area = w * h
            if area_upper_bound is not None and area > area_upper_bound:
                continue
            if max_aspect_ratio is not None and max_aspect_ratio > 0:
                longer = max(w, h)
                shorter = max(1, min(w, h))
                if longer / shorter > max_aspect_ratio:
                    continue
            candidates.append((area, w, h))
    candidates.sort(key=lambda item: (-item[0], -item[1], -item[2]))
    return candidates


def _candidate_objective(candidate: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return (int(candidate[0]), int(candidate[1]), int(candidate[2]))


def _candidate_key(candidate: Tuple[int, int, int]) -> str:
    return f"{int(candidate[1])}x{int(candidate[2])}"


def _is_objectively_worse_or_equal(
    candidate: Tuple[int, int, int],
    best_candidate: Tuple[int, int, int],
) -> bool:
    return _candidate_objective(candidate) <= _candidate_objective(best_candidate)


def _compute_frontier_candidate_metrics(
    candidate: Tuple[int, int, int],
    potential_domain: List[Tuple[int, int, int]],
    *,
    grid_w: int,
    grid_h: int,
) -> Dict[str, int]:
    area, ghost_w, ghost_h = candidate
    anchor_count = max(0, (int(grid_w) - int(ghost_w) + 1) * (int(grid_h) - int(ghost_h) + 1))
    certification_prune_gain = 0
    infeasible_prune_gain = 0
    for other in potential_domain:
        other_area, other_w, other_h = other
        if _candidate_objective(other) <= _candidate_objective(candidate) or (
            int(other_w) <= int(ghost_w) and int(other_h) <= int(ghost_h)
        ):
            certification_prune_gain += 1
        if int(other_w) >= int(ghost_w) and int(other_h) >= int(ghost_h):
            infeasible_prune_gain += 1

    score = Fraction(certification_prune_gain, max(1, anchor_count))
    return {
        "selection_score_num": int(score.numerator),
        "selection_score_den": int(score.denominator),
        "certification_prune_gain": int(certification_prune_gain),
        "infeasible_prune_gain": int(infeasible_prune_gain),
        "anchor_count": int(anchor_count),
    }


def _frontier_selection_sort_key(
    candidate: Tuple[int, int, int],
    metrics: Dict[str, int],
) -> Tuple[Fraction, int, int, int, int, int, int]:
    return (
        Fraction(int(metrics["selection_score_num"]), max(1, int(metrics["selection_score_den"]))),
        int(metrics["certification_prune_gain"]),
        -int(metrics["anchor_count"]),
        int(metrics["infeasible_prune_gain"]),
        int(candidate[0]),
        int(candidate[1]),
        int(candidate[2]),
    )


def _select_frontier_candidate(
    frontier: List[Tuple[int, int, int]],
    potential_domain: List[Tuple[int, int, int]],
    *,
    grid_w: int,
    grid_h: int,
) -> Tuple[Tuple[int, int, int], Dict[str, int], Dict[str, Dict[str, int]]]:
    metrics_by_key: Dict[str, Dict[str, int]] = {}
    selected_candidate: Optional[Tuple[int, int, int]] = None
    selected_metrics: Optional[Dict[str, int]] = None

    for candidate in frontier:
        metrics = _compute_frontier_candidate_metrics(
            candidate,
            potential_domain,
            grid_w=grid_w,
            grid_h=grid_h,
        )
        metrics["frontier_size"] = len(frontier)
        metrics_by_key[_candidate_key(candidate)] = dict(metrics)
        if selected_candidate is None or _frontier_selection_sort_key(candidate, metrics) > _frontier_selection_sort_key(
            selected_candidate,
            selected_metrics or {},
        ):
            selected_candidate = candidate
            selected_metrics = metrics

    if selected_candidate is None or selected_metrics is None:
        raise ValueError("frontier must be non-empty when selecting a candidate")
    return selected_candidate, selected_metrics, metrics_by_key


def _compute_exact_frontier_state(
    candidates: List[Tuple[int, int, int]],
    campaign: Optional[ExactCampaign],
    *,
    grid_w: int,
    grid_h: int,
) -> Dict[str, Any]:
    candidate_records = {}
    if campaign is not None:
        raw_candidates = campaign.state.get("candidates", {})
        if isinstance(raw_candidates, dict):
            candidate_records = raw_candidates

    explicit_certified: List[Tuple[int, int, int]] = []
    explicit_infeasible: List[Tuple[int, int, int]] = []
    best_certified_candidate: Optional[Tuple[int, int, int]] = None
    best_certified_record: Optional[Dict[str, Any]] = None

    for candidate in candidates:
        _area, ghost_w, ghost_h = candidate
        record = candidate_records.get(f"{ghost_w}x{ghost_h}")
        if not isinstance(record, dict):
            continue
        status = str(record.get("status", ""))
        if status == RUN_STATUS_CERTIFIED:
            explicit_certified.append(candidate)
            if (
                best_certified_candidate is None
                or _candidate_objective(candidate) > _candidate_objective(best_certified_candidate)
            ):
                best_certified_candidate = candidate
                best_certified_record = dict(record)
        elif status == RUN_STATUS_INFEASIBLE:
            explicit_infeasible.append(candidate)

    potential_domain: List[Tuple[int, int, int]] = []
    derived_pruned_candidates = 0
    for candidate in candidates:
        _area, ghost_w, ghost_h = candidate
        record = candidate_records.get(f"{ghost_w}x{ghost_h}")
        status = None if not isinstance(record, dict) else str(record.get("status", ""))
        if status in {RUN_STATUS_CERTIFIED, RUN_STATUS_INFEASIBLE}:
            continue

        if any(ghost_w <= cert_w and ghost_h <= cert_h for _a, cert_w, cert_h in explicit_certified):
            derived_pruned_candidates += 1
            continue
        if any(ghost_w >= inf_w and ghost_h >= inf_h for _a, inf_w, inf_h in explicit_infeasible):
            derived_pruned_candidates += 1
            continue
        if best_certified_candidate is not None and _is_objectively_worse_or_equal(
            candidate,
            best_certified_candidate,
        ):
            derived_pruned_candidates += 1
            continue

        potential_domain.append(candidate)

    frontier: List[Tuple[int, int, int]] = []
    for candidate in potential_domain:
        _area, ghost_w, ghost_h = candidate
        dominated = False
        for other in potential_domain:
            if other == candidate:
                continue
            _other_area, other_w, other_h = other
            if (other_w >= ghost_w and other_h >= ghost_h) and (
                other_w > ghost_w or other_h > ghost_h
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    frontier.sort(key=_candidate_objective, reverse=True)

    selected_candidate: Optional[Tuple[int, int, int]] = None
    selected_metrics: Optional[Dict[str, int]] = None
    frontier_metrics_by_key: Dict[str, Dict[str, int]] = {}
    if frontier:
        selected_candidate, selected_metrics, frontier_metrics_by_key = _select_frontier_candidate(
            frontier,
            potential_domain,
            grid_w=grid_w,
            grid_h=grid_h,
        )

    return {
        "potential_domain": potential_domain,
        "frontier": frontier,
        "frontier_size": len(frontier),
        "derived_pruned_candidates": derived_pruned_candidates,
        "best_certified_candidate": best_certified_candidate,
        "best_certified_record": best_certified_record,
        "selected_candidate": selected_candidate,
        "selected_candidate_metrics": selected_metrics,
        "frontier_metrics_by_key": frontier_metrics_by_key,
    }


def _build_certified_result(
    *,
    candidate: Tuple[int, int, int],
    solution: Dict[str, Any],
    attempts: int,
    solve_mode: str,
    campaign_resumed: bool,
    frontier_peak_size: int,
    derived_pruned_candidates: int,
    frontier_selection_policy: str,
    frontier_candidate_metrics: Mapping[str, Any],
) -> Dict[str, Any]:
    area, ghost_w, ghost_h = candidate
    return {
        "ghost_rect": {"w": ghost_w, "h": ghost_h, "area": area},
        "placement_solution": dict(solution),
        "search_status": RUN_STATUS_CERTIFIED,
        "search_stats": {
            "attempts": attempts,
            "explicit_candidate_solves": attempts,
            "solve_mode": solve_mode,
            "campaign_resumed": campaign_resumed,
            "frontier_peak_size": frontier_peak_size,
            "derived_pruned_candidates": derived_pruned_candidates,
            "frontier_selection_policy": str(frontier_selection_policy),
            "frontier_candidate_metrics": dict(frontier_candidate_metrics),
        },
    }


def _save_final_result(project_root: Path, result: Dict[str, Any]) -> Path:
    output_dir = project_root / "data" / "solutions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "final_solution.json"
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def _build_campaign_result_payload(
    *,
    attempts: int,
    run_metadata: Dict[str, Any],
    frontier_selection_policy: str,
    frontier_candidate_metrics: Mapping[str, Any],
) -> Dict[str, Any]:
    proof_summary = dict(run_metadata.get("proof_summary", {}))
    return {
        "proof_summary": {
            "search_attempts": attempts,
            "frontier_selection_policy": str(frontier_selection_policy),
            "frontier_candidate_metrics": dict(frontier_candidate_metrics),
            **proof_summary,
        },
        "exact_safe_cuts": list(run_metadata.get("exact_safe_cuts", [])),
        "loaded_exact_safe_cut_count": int(run_metadata.get("loaded_exact_safe_cut_count", 0)),
        "generated_exact_safe_cut_count": int(
            run_metadata.get("generated_exact_safe_cut_count", 0)
        ),
    }


def run_outer_search(
    *,
    start_area: Optional[int] = None,
    max_attempts: Optional[int] = None,
    project_root: Optional[Path] = None,
    solve_mode: Optional[str] = None,
    certification_mode: Optional[bool] = None,
    master_seconds: float = 600.0,
    binding_seconds: float = 600.0,
    routing_seconds: float = 600.0,
    flow_seconds: float = 60.0,
    master_time_limit: Optional[float] = None,
    benders_max_iter: int = 30,
    campaign_hours: float = 168.0,
    resume_campaign: bool = False,
    max_aspect_ratio: Optional[float] = None,
    area_upper_bound: Optional[int] = None,
    min_side: int = 6,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    solve_mode = _normalize_solve_mode(solve_mode, certification_mode)
    if project_root is None:
        project_root = PROJECT_ROOT
    if master_time_limit is not None:
        master_seconds = float(master_time_limit)

    exact_campaign: Optional[ExactCampaign] = None
    if solve_mode == "certified_exact":
        exact_campaign = ExactCampaign.load_or_create(
            project_root,
            campaign_hours=campaign_hours,
            resume=resume_campaign,
        )

    exact_instances, _pools, rules = load_project_data(project_root, solve_mode="certified_exact")
    generic_io_requirements = load_generic_io_requirements_artifact(project_root)
    grid = dict(rules["globals"]["grid"])
    grid_w = int(grid["width"])
    grid_h = int(grid["height"])
    safe_area_upper_bound = grid_w * grid_h - compute_exact_static_area_lower_bound(
        exact_instances,
        rules,
        generic_io_requirements,
    )
    if area_upper_bound is None:
        area_upper_bound = safe_area_upper_bound
    else:
        area_upper_bound = min(int(area_upper_bound), safe_area_upper_bound)

    candidates = generate_candidate_sizes(
        max_w=grid_w,
        max_h=grid_h,
        min_side=min_side,
        max_aspect_ratio=max_aspect_ratio,
        area_upper_bound=area_upper_bound,
    )
    if start_area is not None:
        candidates = [item for item in candidates if item[0] <= start_area]

    attempts = 0
    frontier_peak_size = 0
    exact_session: Optional[ExactSearchSession] = None

    if solve_mode == "certified_exact":
        while True:
            frontier_state = _compute_exact_frontier_state(
                candidates,
                exact_campaign,
                grid_w=grid_w,
                grid_h=grid_h,
            )
            frontier_peak_size = max(frontier_peak_size, int(frontier_state["frontier_size"]))

            if not frontier_state["potential_domain"]:
                best_candidate = frontier_state["best_certified_candidate"]
                best_record = frontier_state["best_certified_record"]
                if best_candidate is not None and isinstance(best_record, dict):
                    best_proof_summary = dict(best_record.get("proof_summary", {}))
                    result = _build_certified_result(
                        candidate=best_candidate,
                        solution=dict(best_record.get("solution", {})),
                        attempts=attempts,
                        solve_mode=solve_mode,
                        campaign_resumed=exact_campaign.resumed if exact_campaign is not None else False,
                        frontier_peak_size=frontier_peak_size,
                        derived_pruned_candidates=int(
                            frontier_state["derived_pruned_candidates"]
                        ),
                        frontier_selection_policy=str(
                            best_proof_summary.get(
                                "frontier_selection_policy",
                                FRONTIER_SELECTION_POLICY,
                            )
                        ),
                        frontier_candidate_metrics=dict(
                            best_proof_summary.get("frontier_candidate_metrics", {})
                        ),
                    )
                    _save_final_result(project_root, result)
                    if exact_campaign is not None:
                        exact_campaign.state["final_result"] = dict(result)
                        exact_campaign.state["final_status"] = RUN_STATUS_CERTIFIED
                        exact_campaign.mark_campaign_stopped(
                            "search_exhausted_all_candidates",
                            status=RUN_STATUS_CERTIFIED,
                        )
                        exact_campaign.save()
                    return RUN_STATUS_CERTIFIED, result

                if exact_campaign is not None:
                    exact_campaign.mark_campaign_stopped(
                        "search_exhausted_all_candidates",
                        status=RUN_STATUS_INFEASIBLE,
                    )
                    exact_campaign.save()
                return RUN_STATUS_INFEASIBLE, None

            if max_attempts is not None and attempts >= max_attempts:
                if exact_campaign is not None:
                    exact_campaign.mark_campaign_stopped(
                        "max_attempts_exhausted",
                        status=RUN_STATUS_UNKNOWN,
                    )
                    exact_campaign.save()
                return RUN_STATUS_UNKNOWN, None

            if exact_campaign is not None and exact_campaign.remaining_seconds() <= 0:
                exact_campaign.mark_campaign_stopped(
                    "campaign_time_budget_exhausted",
                    status=RUN_STATUS_UNKNOWN,
                )
                exact_campaign.save()
                return RUN_STATUS_UNKNOWN, None

            selected_candidate = frontier_state["selected_candidate"]
            if selected_candidate is None:
                raise ValueError("frontier must provide a selected candidate when potential_domain is non-empty")
            area, ghost_w, ghost_h = selected_candidate
            frontier_candidate_metrics = dict(frontier_state["selected_candidate_metrics"] or {})
            if exact_campaign is not None:
                exact_campaign.mark_candidate_started(ghost_w, ghost_h)
                exact_campaign.save()

            attempts += 1
            if exact_session is None:
                exact_session = ExactSearchSession.create(project_root, solve_mode=solve_mode)
            status, solution = run_benders_for_ghost_rect(
                ghost_w=ghost_w,
                ghost_h=ghost_h,
                max_iterations=benders_max_iter,
                project_root=project_root,
                solve_mode=solve_mode,
                master_seconds=master_seconds,
                binding_seconds=binding_seconds,
                routing_seconds=routing_seconds,
                flow_seconds=flow_seconds,
                campaign=exact_campaign,
                session=exact_session,
            )
            run_metadata = dict(getattr(run_benders_for_ghost_rect, "last_run_metadata", {}) or {})
            campaign_payload = _build_campaign_result_payload(
                attempts=attempts,
                run_metadata=run_metadata,
                frontier_selection_policy=FRONTIER_SELECTION_POLICY,
                frontier_candidate_metrics=frontier_candidate_metrics,
            )

            if status == RUN_STATUS_CERTIFIED and solution is not None:
                if exact_campaign is not None:
                    exact_campaign.mark_candidate_result(
                        ghost_w,
                        ghost_h,
                        RUN_STATUS_CERTIFIED,
                        exact_safe_cuts=campaign_payload["exact_safe_cuts"],
                        solution=solution,
                        proof_summary=campaign_payload["proof_summary"],
                        loaded_exact_safe_cut_count=campaign_payload["loaded_exact_safe_cut_count"],
                        generated_exact_safe_cut_count=campaign_payload[
                            "generated_exact_safe_cut_count"
                        ],
                    )
                    exact_campaign.save()
                continue

            if status == RUN_STATUS_INFEASIBLE:
                if exact_campaign is not None:
                    exact_campaign.mark_candidate_result(
                        ghost_w,
                        ghost_h,
                        RUN_STATUS_INFEASIBLE,
                        exact_safe_cuts=campaign_payload["exact_safe_cuts"],
                        proof_summary=campaign_payload["proof_summary"],
                        loaded_exact_safe_cut_count=campaign_payload["loaded_exact_safe_cut_count"],
                        generated_exact_safe_cut_count=campaign_payload[
                            "generated_exact_safe_cut_count"
                        ],
                    )
                    exact_campaign.save()
                continue

            if status == RUN_STATUS_UNKNOWN:
                if exact_campaign is not None:
                    exact_campaign.mark_candidate_result(
                        ghost_w,
                        ghost_h,
                        RUN_STATUS_UNKNOWN,
                        exact_safe_cuts=campaign_payload["exact_safe_cuts"],
                        proof_summary=campaign_payload["proof_summary"],
                        loaded_exact_safe_cut_count=campaign_payload["loaded_exact_safe_cut_count"],
                        generated_exact_safe_cut_count=campaign_payload[
                            "generated_exact_safe_cut_count"
                        ],
                    )
                    exact_campaign.mark_campaign_stopped(
                        "candidate_returned_unknown",
                        status=RUN_STATUS_UNKNOWN,
                    )
                    exact_campaign.save()
                return RUN_STATUS_UNKNOWN, None
            if status == RUN_STATUS_UNPROVEN:
                if exact_campaign is not None:
                    exact_campaign.mark_candidate_result(
                        ghost_w,
                        ghost_h,
                        RUN_STATUS_UNPROVEN,
                        exact_safe_cuts=campaign_payload["exact_safe_cuts"],
                        proof_summary=campaign_payload["proof_summary"],
                        loaded_exact_safe_cut_count=campaign_payload["loaded_exact_safe_cut_count"],
                        generated_exact_safe_cut_count=campaign_payload[
                            "generated_exact_safe_cut_count"
                        ],
                    )
                    exact_campaign.mark_campaign_stopped(
                        "candidate_returned_unproven",
                        status=RUN_STATUS_UNPROVEN,
                    )
                    exact_campaign.save()
                return RUN_STATUS_UNPROVEN, None

    for area, ghost_w, ghost_h in candidates:
        if max_attempts is not None and attempts >= max_attempts:
            return RUN_STATUS_UNKNOWN, None

        attempts += 1
        status, solution = run_benders_for_ghost_rect(
            ghost_w=ghost_w,
            ghost_h=ghost_h,
            max_iterations=benders_max_iter,
            project_root=project_root,
            solve_mode=solve_mode,
            master_seconds=master_seconds,
            binding_seconds=binding_seconds,
            routing_seconds=routing_seconds,
            flow_seconds=flow_seconds,
            campaign=exact_campaign,
        )
        if status == RUN_STATUS_CERTIFIED and solution is not None:
            return (
                RUN_STATUS_CERTIFIED,
                _build_certified_result(
                    candidate=(area, ghost_w, ghost_h),
                    solution=solution,
                    attempts=attempts,
                    solve_mode=solve_mode,
                    campaign_resumed=False,
                    frontier_peak_size=0,
                    derived_pruned_candidates=0,
                    frontier_selection_policy=FRONTIER_SELECTION_POLICY,
                    frontier_candidate_metrics={},
                ),
            )
        if status == RUN_STATUS_INFEASIBLE:
            continue
        if status == RUN_STATUS_UNKNOWN:
            return RUN_STATUS_UNKNOWN, None
        if status == RUN_STATUS_UNPROVEN:
            return RUN_STATUS_UNPROVEN, None

    return RUN_STATUS_INFEASIBLE, None


if __name__ == "__main__":
    status, result = run_outer_search(max_attempts=3, solve_mode="exploratory", area_upper_bound=64)
    print("status=", status)
    if result:
        print(json.dumps(result["ghost_rect"], ensure_ascii=False))
