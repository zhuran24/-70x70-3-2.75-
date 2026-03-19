"""
Benders 切平面与反馈管理器 (Benders Cut Manager)
Status: ACCEPTED_DRAFT

目标：负责在 LBBD 架构下，接收子问题（宏观流/微观路由）发回的 Benders Cuts（切平面），
进行持久化存储、去重、以及在主问题每次求解前的热启动注入。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

RUN_STATUS_CERTIFIED = "CERTIFIED"
RUN_STATUS_INFEASIBLE = "INFEASIBLE"
RUN_STATUS_UNKNOWN = "UNKNOWN"
RUN_STATUS_UNPROVEN = "UNPROVEN"


@dataclass
class BendersCut:
    """Structured cut record for exact-contract compatibility."""

    cut_type: str
    conflict_set: Dict[str, Any]
    iteration: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    source_mode: str = "exploratory"
    exact_safe: bool = False
    artifact_hashes: Dict[str, str] = field(default_factory=dict)
    proof_stage: Optional[str] = None
    binding_exhausted: Optional[bool] = None
    routing_exhausted: Optional[bool] = None
    proof_summary: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema_version": int(self.schema_version),
            "cut_type": str(self.cut_type),
            "conflict_set": dict(self.conflict_set),
            "iteration": int(self.iteration),
            "metadata": dict(self.metadata),
            "source_mode": str(self.source_mode),
            "exact_safe": bool(self.exact_safe),
            "artifact_hashes": dict(self.artifact_hashes),
            "proof_stage": self.proof_stage,
            "binding_exhausted": self.binding_exhausted,
            "routing_exhausted": self.routing_exhausted,
            "proof_summary": dict(self.proof_summary),
            "created_at": self.created_at,
        }
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BendersCut":
        conflict_set_raw = payload.get("conflict_set", {})
        if not isinstance(conflict_set_raw, Mapping):
            raise ValueError("conflict_set must be a mapping for structured cuts")

        return cls(
            schema_version=int(payload.get("schema_version", 1)),
            cut_type=str(payload["cut_type"]),
            conflict_set={str(k): v for k, v in conflict_set_raw.items()},
            iteration=int(payload.get("iteration", 0)),
            metadata=dict(payload.get("metadata", {})),
            source_mode=str(payload.get("source_mode", "exploratory")),
            exact_safe=bool(payload.get("exact_safe", False)),
            artifact_hashes={
                str(k): str(v) for k, v in dict(payload.get("artifact_hashes", {})).items()
            },
            proof_stage=(
                None if payload.get("proof_stage") is None else str(payload.get("proof_stage"))
            ),
            binding_exhausted=payload.get("binding_exhausted"),
            routing_exhausted=payload.get("routing_exhausted"),
            proof_summary=dict(payload.get("proof_summary", {})),
            created_at=(
                None if payload.get("created_at") is None else str(payload.get("created_at"))
            ),
        )


def summarize_port_balance(
    port_specs: Iterable[Mapping[str, Any]],
) -> Dict[str, Dict[str, int]]:
    """Count discrete in/out endpoints per commodity for the current routing model."""

    balance: Dict[str, Dict[str, int]] = defaultdict(lambda: {"in": 0, "out": 0})
    for spec in port_specs:
        commodity = str(spec.get("commodity", ""))
        port_type = str(spec.get("type", ""))
        if not commodity or port_type not in {"in", "out"}:
            continue
        balance[commodity][port_type] += 1
    return dict(balance)


def analyze_port_balance(
    port_specs: Iterable[Mapping[str, Any]],
) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Summarize dead-end commodities and split/merge pressure for one binding."""

    balance = summarize_port_balance(port_specs)
    dead_end: Dict[str, Dict[str, int]] = {}
    needs_splitter: Dict[str, Dict[str, int]] = {}
    needs_merger: Dict[str, Dict[str, int]] = {}

    for commodity, counts in balance.items():
        in_count = int(counts.get("in", 0))
        out_count = int(counts.get("out", 0))

        if (in_count == 0 and out_count > 0) or (out_count == 0 and in_count > 0):
            dead_end[commodity] = {"in": in_count, "out": out_count}
            continue
        if in_count > out_count:
            needs_splitter[commodity] = {
                "in": in_count,
                "out": out_count,
                "delta": in_count - out_count,
            }
        elif out_count > in_count:
            needs_merger[commodity] = {
                "in": in_count,
                "out": out_count,
                "delta": out_count - in_count,
            }

    return {
        "balance": balance,
        "dead_end": dead_end,
        "needs_splitter": needs_splitter,
        "needs_merger": needs_merger,
    }


class CutManager:
    """Compatibility manager for both runtime JSONL cuts and structured exact cuts."""

    def __init__(
        self,
        checkpoint_dir: Optional[Path] = None,
        *,
        solve_mode: str = "exploratory",
        current_hashes: Optional[Mapping[str, str]] = None,
    ):
        self.checkpoint_dir = checkpoint_dir or (PROJECT_ROOT / "data" / "checkpoints")
        self.solve_mode = str(solve_mode)
        self.current_hashes = (
            {str(k): str(v) for k, v in current_hashes.items()}
            if current_hashes is not None
            else {}
        )
        self.cuts_file = self.checkpoint_dir / "benders_cuts.jsonl"
        self.cuts: List[BendersCut] = []
        self._cut_signatures: Set[frozenset[Tuple[str, Any]]] = set()
        self.active_cuts: Set[frozenset[Tuple[str, str]]] = set()

        self._ensure_dir()
        self.load_cuts()

    def _ensure_dir(self) -> None:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        if not self.cuts_file.exists():
            self.cuts_file.touch()

    def _clear_structured_registry(self) -> None:
        self.cuts.clear()
        self._cut_signatures.clear()
        self.active_cuts.clear()

    def _runtime_signature(
        self,
        conflict_set: Iterable[Mapping[str, Any]],
    ) -> frozenset[Tuple[str, str]]:
        return frozenset(
            sorted(
                (
                    str(item["instance_id"]),
                    str(item["pose_id"]),
                )
                for item in conflict_set
            )
        )

    def _structured_signature(self, cut: BendersCut) -> frozenset[Tuple[str, Any]]:
        return frozenset(sorted((str(k), v) for k, v in cut.conflict_set.items()))

    def load_cuts(self) -> None:
        """Load runtime JSONL cuts accumulated by the flow-based loop."""

        self.active_cuts.clear()
        if not self.cuts_file.exists():
            return

        with self.cuts_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    conflict_set = payload.get("conflict_set", [])
                    if not isinstance(conflict_set, list):
                        continue
                    self.active_cuts.add(self._runtime_signature(conflict_set))
                except Exception as exc:
                    print(f"[WARN] 加载 Benders Cut 失败: {exc}")

    def load(self, path: Path) -> Dict[str, int]:
        """Load structured cut artifacts with exact-contract filtering."""

        stats: Dict[str, int] = {
            "loaded": 0,
            "rejected_legacy": 0,
            "rejected_hash": 0,
            "rejected_not_exact_safe": 0,
            "rejected_mode": 0,
            "deduped": 0,
        }
        self._clear_structured_registry()

        if not path.exists():
            return stats

        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            stats["rejected_legacy"] = len(payload)
            return stats
        if not isinstance(payload, Mapping):
            stats["rejected_legacy"] = 1
            return stats

        raw_cuts = payload.get("cuts", [])
        if not isinstance(raw_cuts, list):
            stats["rejected_legacy"] = 1
            return stats

        for raw_cut in raw_cuts:
            if not isinstance(raw_cut, Mapping):
                stats["rejected_legacy"] += 1
                continue

            try:
                cut = BendersCut.from_dict(raw_cut)
            except Exception:
                stats["rejected_legacy"] += 1
                continue

            if self.solve_mode == "certified_exact":
                if cut.source_mode != "certified_exact":
                    stats["rejected_mode"] += 1
                    continue
                if not cut.exact_safe:
                    stats["rejected_not_exact_safe"] += 1
                    continue
                if self.current_hashes and cut.artifact_hashes != self.current_hashes:
                    stats["rejected_hash"] += 1
                    continue

            signature = self._structured_signature(cut)
            if signature in self._cut_signatures:
                stats["deduped"] += 1
                continue

            self._cut_signatures.add(signature)
            self.cuts.append(cut)
            self.active_cuts.add(
                frozenset((str(instance_id), str(pose_idx)) for instance_id, pose_idx in cut.conflict_set.items())
            )
            stats["loaded"] += 1

        return stats

    def register_structured_cut(self, cut: BendersCut) -> bool:
        """Register one structured exact/exploratory cut in memory with deduplication."""

        signature = self._structured_signature(cut)
        if signature in self._cut_signatures:
            return False

        self._cut_signatures.add(signature)
        self.cuts.append(cut)
        return True

    def add_cut(self, conflict_set: List[Dict[str, str]], reason: str, source: str) -> bool:
        """Add one runtime cut record while preserving existing JSONL compatibility."""

        frozen_conflict = self._runtime_signature(conflict_set)
        if frozen_conflict in self.active_cuts:
            return False

        self.active_cuts.add(frozen_conflict)
        cut_record = {
            "source": source,
            "reason": reason,
            "conflict_set": conflict_set,
        }
        with self.cuts_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(cut_record, ensure_ascii=False) + "\n")
        return True

    def get_all_cuts(self) -> List[List[Tuple[str, str]]]:
        """Return all runtime cuts in a stable tuple-list format for the master model."""

        return [sorted(list(cut)) for cut in self.active_cuts]

    def clear_all(self) -> None:
        """Dangerous helper used only when all historical cuts must be invalidated."""

        self._clear_structured_registry()
        if self.cuts_file.exists():
            self.cuts_file.unlink()
        self.cuts_file.touch()
