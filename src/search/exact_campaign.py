"""
Exact campaign state manager（精确战役状态管理器）.

职责：
1. 计算 certified exact（严格认证精确）输入工件哈希。
2. 管理最长 168 小时级 campaign state（战役状态）持久化。
3. 只有在 schema / mode / artifact hash / required fields 一致时才允许恢复。
4. 为每个候选空地保存 strictly valid evidence（严格有效证据）与 exact-safe cuts（精确安全 cuts）。
"""

from __future__ import annotations

import calendar
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

DEFAULT_CAMPAIGN_FILENAME = "exact_campaign_state.json"
CAMPAIGN_SCHEMA_VERSION = 3
PROOF_SUMMARY_SCHEMA_VERSION = 1
VALID_CANDIDATE_STATUSES = {
    "RUNNING",
    "CERTIFIED",
    "INFEASIBLE",
    "UNKNOWN",
    "UNPROVEN",
}
REQUIRED_STATE_FIELDS = {
    "schema_version",
    "solve_mode",
    "campaign_hours",
    "created_at",
    "updated_at",
    "artifact_hashes",
    "proof_summary_schema_version",
    "reset_reason",
    "final_result",
    "final_status",
    "last_stop_reason",
    "candidates",
}
REQUIRED_CANDIDATE_FIELDS = {
    "ghost_rect",
    "attempts",
    "started_at",
    "updated_at",
    "finished_at",
    "status",
    "proof_summary",
    "exact_safe_cuts",
    "loaded_exact_safe_cut_count",
    "generated_exact_safe_cut_count",
}

EXACT_HASH_FILES = {
    "mandatory_exact_instances": "data/preprocessed/mandatory_exact_instances.json",
    "candidate_placements": "data/preprocessed/candidate_placements.json",
    "canonical_rules": "rules/canonical_rules.json",
    "generic_io_requirements": "data/preprocessed/generic_io_requirements.json",
}


def now_ts() -> float:
    return time.time()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts()))


def iso_to_ts(iso_text: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(iso_text, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return now_ts()


def sha256_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compute_exact_artifact_hashes(project_root: Path) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    for key, relative_path in EXACT_HASH_FILES.items():
        hashes[key] = sha256_file(project_root / relative_path)
    return hashes


def candidate_key(ghost_w: int, ghost_h: int) -> str:
    return f"{ghost_w}x{ghost_h}"


def _candidate_defaults(ghost_w: int, ghost_h: int) -> Dict[str, Any]:
    return {
        "ghost_rect": {"w": int(ghost_w), "h": int(ghost_h), "area": int(ghost_w) * int(ghost_h)},
        "attempts": 0,
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
        "status": "UNKNOWN",
        "proof_summary": {},
        "exact_safe_cuts": [],
        "loaded_exact_safe_cut_count": 0,
        "generated_exact_safe_cut_count": 0,
    }


def _build_initial_state(
    *,
    current_hashes: Mapping[str, str],
    campaign_hours: float,
    reset_reason: Optional[str],
) -> Dict[str, Any]:
    timestamp = now_iso()
    return {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "solve_mode": "certified_exact",
        "campaign_hours": float(campaign_hours),
        "created_at": timestamp,
        "updated_at": timestamp,
        "artifact_hashes": {str(k): str(v) for k, v in current_hashes.items()},
        "proof_summary_schema_version": PROOF_SUMMARY_SCHEMA_VERSION,
        "reset_reason": reset_reason,
        "final_result": None,
        "final_status": None,
        "last_stop_reason": None,
        "candidates": {},
    }


def _validate_candidate_record(record_key: str, record: Mapping[str, Any]) -> Optional[str]:
    missing = sorted(REQUIRED_CANDIDATE_FIELDS.difference(record.keys()))
    if missing:
        return f"candidate_missing_field:{record_key}:{missing[0]}"

    ghost_rect = record.get("ghost_rect")
    if not isinstance(ghost_rect, Mapping):
        return f"candidate_invalid_ghost_rect:{record_key}"
    for field in ("w", "h", "area"):
        if field not in ghost_rect:
            return f"candidate_missing_ghost_rect_field:{record_key}:{field}"

    try:
        int(record.get("attempts", 0))
        int(record.get("loaded_exact_safe_cut_count", 0))
        int(record.get("generated_exact_safe_cut_count", 0))
    except Exception:
        return f"candidate_invalid_count:{record_key}"

    status = str(record.get("status", ""))
    if status not in VALID_CANDIDATE_STATUSES:
        return f"candidate_invalid_status:{record_key}:{status}"

    if not isinstance(record.get("proof_summary"), Mapping):
        return f"candidate_invalid_proof_summary:{record_key}"
    if not isinstance(record.get("exact_safe_cuts"), list):
        return f"candidate_invalid_exact_safe_cuts:{record_key}"

    for field in ("started_at", "updated_at"):
        if record.get(field) is None:
            return f"candidate_missing_timestamp:{record_key}:{field}"
    if status == "RUNNING" and record.get("finished_at") is not None:
        return f"candidate_running_has_finished_at:{record_key}"
    if status != "RUNNING" and record.get("finished_at") is None:
        return f"candidate_terminal_missing_finished_at:{record_key}"
    return None


def _validate_resume_state(
    state: Mapping[str, Any],
    *,
    current_hashes: Mapping[str, str],
) -> Optional[str]:
    missing = sorted(REQUIRED_STATE_FIELDS.difference(state.keys()))
    if missing:
        return f"missing_state_field:{missing[0]}"
    if int(state.get("schema_version", -1)) != CAMPAIGN_SCHEMA_VERSION:
        return "schema_version_mismatch"
    if str(state.get("solve_mode")) != "certified_exact":
        return "solve_mode_mismatch"
    if int(state.get("proof_summary_schema_version", -1)) != PROOF_SUMMARY_SCHEMA_VERSION:
        return "proof_summary_schema_version_mismatch"
    if not isinstance(state.get("artifact_hashes"), Mapping):
        return "artifact_hashes_invalid"
    if dict(state.get("artifact_hashes", {})) != dict(current_hashes):
        return "artifact_hash_mismatch"
    if not isinstance(state.get("candidates"), Mapping):
        return "candidates_invalid"
    if state.get("last_stop_reason") is not None:
        stop_reason = state.get("last_stop_reason")
        if not isinstance(stop_reason, Mapping) or "reason" not in stop_reason:
            return "last_stop_reason_invalid"
    final_result = state.get("final_result")
    final_status = state.get("final_status")
    if final_result is not None and not isinstance(final_result, Mapping):
        return "final_result_invalid"
    if final_status is not None and not isinstance(final_status, str):
        return "final_status_invalid"
    if final_result is not None and final_status != "CERTIFIED":
        return "final_status_mismatch"

    for record_key, record in dict(state.get("candidates", {})).items():
        if not isinstance(record, Mapping):
            return f"candidate_invalid:{record_key}"
        reason = _validate_candidate_record(str(record_key), record)
        if reason is not None:
            return reason
    return None


@dataclass
class ExactCampaign:
    project_root: Path
    path: Path
    state: Dict[str, Any]
    resumed: bool
    compatible_hashes: bool

    @classmethod
    def load_or_create(
        cls,
        project_root: Path,
        campaign_hours: float = 168.0,
        resume: bool = False,
        filename: str = DEFAULT_CAMPAIGN_FILENAME,
    ) -> "ExactCampaign":
        checkpoints_dir = project_root / "data" / "checkpoints"
        checkpoints_dir.mkdir(parents=True, exist_ok=True)
        path = checkpoints_dir / filename
        current_hashes = compute_exact_artifact_hashes(project_root)

        reset_reason: Optional[str] = None
        if resume and path.exists():
            try:
                loaded_state = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                reset_reason = "state_json_invalid"
            else:
                if isinstance(loaded_state, Mapping):
                    reset_reason = _validate_resume_state(
                        loaded_state,
                        current_hashes=current_hashes,
                    )
                    if reset_reason is None:
                        state = dict(loaded_state)
                        state["updated_at"] = now_iso()
                        state["reset_reason"] = None
                        return cls(
                            project_root=project_root,
                            path=path,
                            state=state,
                            resumed=True,
                            compatible_hashes=True,
                        )
                else:
                    reset_reason = "state_payload_invalid"

        state = _build_initial_state(
            current_hashes=current_hashes,
            campaign_hours=campaign_hours,
            reset_reason=reset_reason,
        )
        return cls(
            project_root=project_root,
            path=path,
            state=state,
            resumed=False,
            compatible_hashes=(reset_reason is None),
        )

    @property
    def artifact_hashes(self) -> Dict[str, str]:
        return dict(self.state.get("artifact_hashes", {}))

    @property
    def campaign_hours(self) -> float:
        return float(self.state.get("campaign_hours", 168.0))

    @property
    def reset_reason(self) -> Optional[str]:
        value = self.state.get("reset_reason")
        return None if value is None else str(value)

    def remaining_seconds(self) -> float:
        created_at = str(self.state.get("created_at", now_iso()))
        elapsed = max(0.0, now_ts() - iso_to_ts(created_at))
        return max(0.0, self.campaign_hours * 3600.0 - elapsed)

    def is_compatible_with_current_hashes(self) -> bool:
        return self.state.get("artifact_hashes") == compute_exact_artifact_hashes(self.project_root)

    def get_candidate_record(self, ghost_w: int, ghost_h: int) -> Optional[Dict[str, Any]]:
        record = self.state.get("candidates", {}).get(candidate_key(ghost_w, ghost_h))
        return dict(record) if isinstance(record, dict) else None

    def get_candidate_cuts(self, ghost_w: int, ghost_h: int) -> list[Dict[str, Any]]:
        record = self.get_candidate_record(ghost_w, ghost_h) or {}
        return list(record.get("exact_safe_cuts", []))

    def mark_candidate_started(self, ghost_w: int, ghost_h: int) -> None:
        key = candidate_key(ghost_w, ghost_h)
        candidates = self.state.setdefault("candidates", {})
        existing = candidates.get(key, {})
        record = _candidate_defaults(ghost_w, ghost_h)
        if isinstance(existing, Mapping):
            record.update(dict(existing))

        timestamp = now_iso()
        record["status"] = "RUNNING"
        record["attempts"] = int(record.get("attempts", 0)) + 1
        record["started_at"] = timestamp
        record["updated_at"] = timestamp
        record["finished_at"] = None

        candidates[key] = record
        self.state["last_stop_reason"] = None
        if self.state.get("final_result") is None:
            self.state["final_status"] = None
        self.state["updated_at"] = timestamp

    def mark_candidate_result(
        self,
        ghost_w: int,
        ghost_h: int,
        status: str,
        *,
        exact_safe_cuts: Optional[list[Mapping[str, Any]]] = None,
        solution: Optional[Mapping[str, Any]] = None,
        proof_summary: Optional[Mapping[str, Any]] = None,
        loaded_exact_safe_cut_count: Optional[int] = None,
        generated_exact_safe_cut_count: Optional[int] = None,
    ) -> None:
        key = candidate_key(ghost_w, ghost_h)
        candidates = self.state.setdefault("candidates", {})
        existing = candidates.get(key, {})
        record = _candidate_defaults(ghost_w, ghost_h)
        if isinstance(existing, Mapping):
            record.update(dict(existing))

        timestamp = now_iso()
        record["status"] = str(status)
        record["updated_at"] = timestamp
        record["finished_at"] = timestamp
        if record.get("started_at") is None:
            record["started_at"] = timestamp
        record["proof_summary"] = dict(proof_summary or {})

        if exact_safe_cuts is not None:
            record["exact_safe_cuts"] = [dict(cut) for cut in exact_safe_cuts]
        else:
            record["exact_safe_cuts"] = list(record.get("exact_safe_cuts", []))

        if loaded_exact_safe_cut_count is not None:
            record["loaded_exact_safe_cut_count"] = int(loaded_exact_safe_cut_count)
        else:
            record["loaded_exact_safe_cut_count"] = int(record.get("loaded_exact_safe_cut_count", 0))

        if generated_exact_safe_cut_count is not None:
            record["generated_exact_safe_cut_count"] = int(generated_exact_safe_cut_count)
        else:
            record["generated_exact_safe_cut_count"] = int(
                record.get("generated_exact_safe_cut_count", 0)
            )

        if solution is not None and status == "CERTIFIED":
            record["solution"] = dict(solution)
            self.state["final_result"] = {
                "ghost_rect": {"w": ghost_w, "h": ghost_h, "area": ghost_w * ghost_h},
                "placement_solution": dict(solution),
                "search_status": status,
                "search_stats": {
                    "campaign_resumed": self.resumed,
                    "timestamp": timestamp,
                },
            }
            self.state["final_status"] = "CERTIFIED"
            self.state["last_stop_reason"] = None
        elif status != "CERTIFIED":
            record.pop("solution", None)

        candidates[key] = record
        self.state["updated_at"] = timestamp

    def mark_campaign_stopped(self, reason: str, status: Optional[str] = None) -> None:
        timestamp = now_iso()
        stop_record = {
            "reason": str(reason),
            "status": None if status is None else str(status),
            "updated_at": timestamp,
        }
        self.state["last_stop_reason"] = stop_record
        if status is not None:
            self.state["final_status"] = str(status)
        self.state["updated_at"] = timestamp

    def best_certified_result(self) -> Optional[Dict[str, Any]]:
        result = self.state.get("final_result")
        if not isinstance(result, dict):
            return None
        result_copy = dict(result)
        result_copy["search_status"] = "CERTIFIED"
        self.state["final_result"] = dict(result_copy)
        self.state["final_status"] = "CERTIFIED"
        return result_copy

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state["updated_at"] = now_iso()
        self.path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
