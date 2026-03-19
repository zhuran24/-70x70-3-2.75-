"""Tests for cut provenance（切平面来源追踪测试）."""

from __future__ import annotations

import json
from pathlib import Path

from src.models.cut_manager import BendersCut, CutManager
from src.search.benders_loop import collect_certification_blockers



def test_certified_exact_rejects_legacy_cut_file(tmp_path: Path) -> None:
    legacy_path = tmp_path / "cuts_legacy.json"
    legacy_path.write_text(
        json.dumps(
            [
                {
                    "cut_type": "topo",
                    "conflict_set": {"power_pole_599": 599},
                    "iteration": 1,
                    "metadata": {},
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manager = CutManager(
        solve_mode="certified_exact",
        current_hashes={"candidate_placements": "abc", "mandatory_exact_instances": "def"},
    )
    stats = manager.load(legacy_path)
    assert stats["loaded"] == 0
    assert stats["rejected_legacy"] == 1



def test_certified_exact_loads_only_matching_exact_safe_cuts(tmp_path: Path) -> None:
    exact_path = tmp_path / "cuts_exact.json"
    matching_hashes = {"candidate_placements": "abc", "mandatory_exact_instances": "def"}
    exact_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "cuts": [
                    {
                        "schema_version": 2,
                        "cut_type": "routing_exhausted_nogood",
                        "conflict_set": {"pose_optional::power_pole::pole_1": 1},
                        "iteration": 3,
                        "metadata": {},
                        "source_mode": "certified_exact",
                        "exact_safe": True,
                        "artifact_hashes": matching_hashes,
                        "proof_stage": "routing",
                        "binding_exhausted": True,
                        "routing_exhausted": True,
                        "proof_summary": {"enumerated_bindings": 4},
                        "created_at": "2026-03-15T00:00:00Z",
                    },
                    {
                        "schema_version": 2,
                        "cut_type": "routing_exhausted_nogood",
                        "conflict_set": {"pose_optional::power_pole::pole_2": 2},
                        "iteration": 4,
                        "metadata": {},
                        "source_mode": "certified_exact",
                        "exact_safe": True,
                        "artifact_hashes": {"candidate_placements": "mismatch", "mandatory_exact_instances": "def"},
                        "proof_stage": "routing",
                        "binding_exhausted": True,
                        "routing_exhausted": True,
                        "proof_summary": {},
                        "created_at": "2026-03-15T00:00:00Z",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manager = CutManager(solve_mode="certified_exact", current_hashes=matching_hashes)
    stats = manager.load(exact_path)
    assert stats["loaded"] == 1
    assert stats["rejected_hash"] == 1
    assert len(manager.cuts) == 1
    assert manager.cuts[0].exact_safe is True



def test_collect_certification_blockers_flags_hash_mismatch_cut() -> None:
    cut = BendersCut(
        cut_type="routing_exhausted_nogood",
        conflict_set={"pose_optional::power_pole::pole_1": 1},
        iteration=1,
        source_mode="certified_exact",
        exact_safe=True,
        artifact_hashes={"candidate_placements": "old"},
        proof_stage="routing",
        binding_exhausted=True,
        routing_exhausted=True,
    )
    blockers = collect_certification_blockers(
        solve_mode="certified_exact",
        loaded_cuts=[cut],
        current_hashes={"candidate_placements": "new"},
    )
    assert any(item["code"] == "cut_hash_mismatch" for item in blockers)


def test_certified_exact_loads_new_fine_grained_exact_safe_cut_types(tmp_path: Path) -> None:
    exact_path = tmp_path / "cuts_fine_grained_exact.json"
    matching_hashes = {"candidate_placements": "abc", "mandatory_exact_instances": "def"}
    exact_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "cuts": [
                    {
                        "schema_version": 2,
                        "cut_type": "binding_pose_domain_empty_nogood",
                        "conflict_set": {"tiny_001": 0},
                        "iteration": 1,
                        "metadata": {"kind": "placement_local_nogood"},
                        "source_mode": "certified_exact",
                        "exact_safe": True,
                        "artifact_hashes": matching_hashes,
                        "proof_stage": "binding",
                        "binding_exhausted": False,
                        "routing_exhausted": False,
                        "proof_summary": {"binding_status": "EMPTY_DOMAIN"},
                        "created_at": "2026-03-16T00:00:00Z",
                    },
                    {
                        "schema_version": 2,
                        "cut_type": "routing_front_blocked_nogood",
                        "conflict_set": {
                            "tiny_001": 0,
                            "pose_optional::power_pole::pole_block": 0,
                        },
                        "iteration": 2,
                        "metadata": {"kind": "placement_local_nogood"},
                        "source_mode": "certified_exact",
                        "exact_safe": True,
                        "artifact_hashes": matching_hashes,
                        "proof_stage": "routing",
                        "binding_exhausted": False,
                        "routing_exhausted": False,
                        "proof_summary": {"routing_status": "PRECHECK_FRONT_BLOCKED"},
                        "created_at": "2026-03-16T00:00:00Z",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manager = CutManager(solve_mode="certified_exact", current_hashes=matching_hashes)
    stats = manager.load(exact_path)

    assert stats["loaded"] == 2
    assert {cut.cut_type for cut in manager.cuts} == {
        "binding_pose_domain_empty_nogood",
        "routing_front_blocked_nogood",
    }
