"""Residual dataset construction for slip-aware residual learning.

Converts episode trace JSONL files and aggregate summaries into a structured
residual-learning dataset.  Each frame records the heuristic action, the
executed action, and the residual target (executed - heuristic) so that a
bounded residual policy can learn when and how to correct the base heuristic.
"""

from __future__ import annotations

import json
import math
import random
import re
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel, Field

# Thresholds for seed-24-like heuristic fallback in the residual dataset.
SEED24_OBJECT_Z_THRESHOLD = 0.023
SEED24_GRIPPER_POS_THRESHOLD = 0.035


class ResidualFrame(BaseModel):
    """A single frame in the residual-learning dataset."""

    episode: int
    step: int
    task: str
    object_name: str | None = None
    seed: int | None = None
    phase: str

    observation: dict[str, Any] = Field(default_factory=dict)

    heuristic_action: list[float] = Field(default_factory=list)
    executed_action: list[float] = Field(default_factory=list)

    success_label: bool = False
    failure_type: str | None = None

    # v1.10 paired / route / OOD labels
    pair_label: str | None = None
    route_label: str | None = None
    medium_ood_label: str | None = None

    contact_signal: dict[str, Any] | None = None
    slip_signal: dict[str, Any] | None = None
    grip_quality_signal: dict[str, Any] | None = None

    residual_target: list[float] = Field(default_factory=list)
    residual_mask: list[bool] = Field(default_factory=list)
    sample_weight: float = 1.0
    source_trace: str | None = None

    # v1.10 learned model bookkeeping
    trigger_model_score: float | None = None
    bounded_residual: list[float] = Field(default_factory=list)


class ResidualDataset:
    """Load traces, compute residuals, and expose train/val/test splits."""

    def __init__(self, frames: list[ResidualFrame]) -> None:
        self.frames = frames
        self._train: list[ResidualFrame] | None = None
        self._val: list[ResidualFrame] | None = None
        self._test: list[ResidualFrame] | None = None

    @classmethod
    def from_saved(
        cls,
        dataset_dir: str | Path,
    ) -> "ResidualDataset":
        """Load a previously saved ResidualDataset from its artifact directory.

        Only ``frames.jsonl`` is required; split manifests are loaded when
        present.  This is the preferred entry point for training scripts that
        consume datasets produced by ``save()``.
        """
        dataset_dir = Path(dataset_dir)
        if not dataset_dir.exists():
            raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

        jsonl_path = dataset_dir / "frames.jsonl"
        if not jsonl_path.exists():
            raise FileNotFoundError(f"frames.jsonl not found in {dataset_dir}")

        frames: list[ResidualFrame] = []
        with jsonl_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                # Parquet/jsonl may serialize None fields as strings or numpy
                # scalars; Pydantic will coerce the simple types.
                frames.append(ResidualFrame(**record))

        ds = cls(frames)

        for split, attr in (("train", "_train"), ("val", "_val"), ("test", "_test")):
            split_path = dataset_dir / f"split_{split}.json"
            if split_path.exists():
                data = json.loads(split_path.read_text(encoding="utf-8"))
                eps = set(data.get("episodes", []))
                setattr(ds, attr, [f for f in frames if f.episode in eps])

        return ds

    @classmethod
    def from_traces(
        cls,
        trace_dir: str | Path,
        summary_path: str | Path | None = None,
        train_ratio: float = 0.70,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
        random_seed: int = 42,
        failure_weight: float = 2.0,
        success_weight: float = 1.0,
        seed_success_map: dict[int, bool] | None = None,
        trace_success_map: dict[str, bool] | None = None,
    ) -> "ResidualDataset":
        """Build a ResidualDataset from a directory of episode traces.

        Parameters
        ----------
        trace_dir:
            Directory containing subdirectories with ``trace.jsonl`` files.
        summary_path:
            Optional path to an aggregate summary JSON file with per-episode
            success/failure metadata.
        train_ratio, val_ratio, test_ratio:
            Episode-level split ratios (must sum to 1.0).
        random_seed:
            Seed for reproducible episode-level stratified splitting.
        failure_weight:
            Weight assigned to frames from failed episodes.
        success_weight:
            Weight assigned to frames from successful episodes.
        seed_success_map:
            Optional mapping from seed to success label. When a trace's inferred
            seed is present in this map, the map value overrides the summary
            metadata. This lets callers use per-seed audit CSVs (e.g.
            ``per_seed_results.csv``) to label successful episodes even when the
            aggregate summary lacks per-episode metadata.
        trace_success_map:
            Optional mapping from trace path (relative to ``trace_dir``) to
            success label. When present, this takes precedence over both the
            summary metadata and ``seed_success_map``. This is useful when the
            same seed appears under multiple conditions (e.g. target yaw or OOD
            variant) and a global seed map would be ambiguous.
        """
        trace_dir = Path(trace_dir)
        if not trace_dir.exists():
            raise FileNotFoundError(f"Trace directory not found: {trace_dir}")

        summary: dict[str, Any] = {}
        if summary_path is not None:
            summary_path = Path(summary_path)
            if not summary_path.exists():
                raise FileNotFoundError(f"Summary path not found: {summary_path}")
            with summary_path.open() as fh:
                summary = json.load(fh)

        # Collect per-episode metadata from summary if available.
        episode_meta: dict[int, dict[str, Any]] = {}
        if "episodes" in summary:
            for ep in summary["episodes"]:
                eid = int(ep.get("episode_id", ep.get("episode", 0)))
                episode_meta[eid] = ep
        elif "per_episode" in summary:
            for key, ep in summary["per_episode"].items():
                eid = int(key) if key.isdigit() else int(ep.get("episode_id", ep.get("episode", 0)))
                episode_meta[eid] = ep

        frames: list[ResidualFrame] = []
        trace_files = list(trace_dir.rglob("trace.jsonl"))
        # Each trace file is a distinct episode.  Trace records often reuse a
        # default episode id (e.g. 1), so we assign a globally unique episode id
        # per file to avoid merging unrelated episodes.
        global_episode_counter = 0

        for trace_file in trace_files:
            with trace_file.open() as fh:
                records = [json.loads(line) for line in fh if line.strip()]

            if not records:
                continue

            global_episode_counter += 1
            episode_id = global_episode_counter
            # Original summary metadata is keyed by the old episode id if it was
            # unique; otherwise ignore it because we cannot map it per file.
            original_episode = int(records[0].get("episode", 0))
            meta = episode_meta.get(episode_id, episode_meta.get(original_episode, {}))

            task = str(meta.get("task", meta.get("task_id", "unknown")))
            object_name = meta.get("object_name")
            seed = meta.get("seed")
            if seed is None:
                # Infer seed from path conventions like seed_042 or seed042.
                for part in trace_file.parts:
                    match = re.search(r"(?:^|_)seed_?(\d{3,})", part)
                    if match:
                        try:
                            seed = int(match.group(1))
                            break
                        except ValueError:
                            pass

            success = bool(meta.get("success", False))
            if seed_success_map is not None and seed is not None and seed in seed_success_map:
                success = bool(seed_success_map[seed])

            # Per-trace success override takes precedence over summary/seed map.
            trace_relative_key = str(trace_file.relative_to(trace_dir).as_posix())
            if trace_success_map is not None:
                if trace_relative_key in trace_success_map:
                    success = bool(trace_success_map[trace_relative_key])
                elif str(trace_file.relative_to(trace_dir)) in trace_success_map:
                    success = bool(trace_success_map[str(trace_file.relative_to(trace_dir))])
                elif trace_file.name in trace_success_map:
                    success = bool(trace_success_map[trace_file.name])

            failure_type = meta.get("failure_type") or meta.get("failure_reason")

            for record in records:
                step = int(record.get("step", 0))
                phase = str(record.get("phase", "UNKNOWN"))

                # Extract action fields from the trace.
                executed_action = _extract_action(record)
                heuristic_action = _extract_heuristic_action(record)

                # If heuristic_action is missing, default to executed_action
                # so that residual_target becomes zero (no-op baseline).
                if not heuristic_action:
                    heuristic_action = list(executed_action)

                residual_target = [
                    e - h for e, h in zip(executed_action, heuristic_action)
                ]

                # Default mask: all True (all axes may be modified).
                residual_mask = [True] * len(residual_target) if residual_target else []

                # Sample weight based on episode success.
                weight = failure_weight if not success else success_weight

                # Optional signals: prefer explicit trace fields, fall back to None.
                contact_signal = _extract_signal(record, "contact")
                slip_signal = _extract_signal(record, "slip")
                grip_quality_signal = _extract_signal(record, "grip_quality")
                observation = _extract_observation(record)
                if grip_quality_signal is None and (
                    observation.get("object_z") is not None
                    or observation.get("gripper_pos") is not None
                ):
                    grip_quality_signal = {}
                if grip_quality_signal is not None:
                    grip_quality_signal = _enrich_grip_quality_signal(
                        grip_quality_signal, observation
                    )

                frames.append(
                    ResidualFrame(
                        episode=episode_id,
                        step=step,
                        task=task,
                        object_name=object_name,
                        seed=seed,
                        phase=phase,
                        observation=_extract_observation(record),
                        heuristic_action=heuristic_action,
                        executed_action=executed_action,
                        success_label=success,
                        failure_type=failure_type,
                        contact_signal=contact_signal,
                        slip_signal=slip_signal,
                        grip_quality_signal=grip_quality_signal,
                        residual_target=residual_target,
                        residual_mask=residual_mask,
                        sample_weight=weight,
                        source_trace=str(trace_file),
                    )
                )

        ds = cls(frames)
        ds._split_by_episode(train_ratio, val_ratio, test_ratio, random_seed)
        return ds

    def _split_by_episode(
        self,
        train_ratio: float,
        val_ratio: float,
        test_ratio: float,
        random_seed: int,
    ) -> None:
        """Stratified split by episode, preserving success/failure proportions.

        Each list (success episodes and failure episodes) is shuffled and then
        partitioned greedily into train/val/test. If train+val would consume all
        items, train and val are shrunk so that test receives at least one item
        when the list is non-empty.
        """
        if not self.frames:
            self._train = []
            self._val = []
            self._test = []
            return

        episodes: dict[int, dict[str, Any]] = {}
        for frame in self.frames:
            eid = frame.episode
            if eid not in episodes:
                episodes[eid] = {"success": frame.success_label, "frames": []}
            episodes[eid]["frames"].append(frame)

        success_eps = [eid for eid, meta in episodes.items() if meta["success"]]
        failure_eps = [eid for eid, meta in episodes.items() if not meta["success"]]

        rng = random.Random(random_seed)
        rng.shuffle(success_eps)
        rng.shuffle(failure_eps)

        def _split_list(items: list[int], tr: float, vr: float) -> tuple[list[int], list[int], list[int]]:
            """Partition ``items`` greedily into train/val/test ratios.

            Guarantees that at least one item is assigned to test when ``items``
            is non-empty, by shrinking train then val if necessary.
            """
            n = len(items)
            n_train = math.floor(n * tr)
            n_val = math.floor(n * vr)
            # Ensure at least one item goes to test if n > 0.
            if n_train + n_val >= n and n > 0:
                n_train = max(0, n_train - 1)
            if n_train + n_val >= n and n > 0:
                n_val = max(0, n_val - 1)
            return items[:n_train], items[n_train : n_train + n_val], items[n_train + n_val :]

        s_train, s_val, s_test = _split_list(success_eps, train_ratio, val_ratio)
        f_train, f_val, f_test = _split_list(failure_eps, train_ratio, val_ratio)

        train_eps = set(s_train + f_train)
        val_eps = set(s_val + f_val)
        test_eps = set(s_test + f_test)

        # Any remaining episodes (shouldn't happen) go to train.
        all_assigned = train_eps | val_eps | test_eps
        for eid in episodes:
            if eid not in all_assigned:
                train_eps.add(eid)

        self._train = [f for f in self.frames if f.episode in train_eps]
        self._val = [f for f in self.frames if f.episode in val_eps]
        self._test = [f for f in self.frames if f.episode in test_eps]

    @property
    def train(self) -> list[ResidualFrame]:
        if self._train is None:
            raise RuntimeError("Dataset has not been split yet.")
        return self._train

    @property
    def val(self) -> list[ResidualFrame]:
        if self._val is None:
            raise RuntimeError("Dataset has not been split yet.")
        return self._val

    @property
    def test(self) -> list[ResidualFrame]:
        if self._test is None:
            raise RuntimeError("Dataset has not been split yet.")
        return self._test

    def statistics(self) -> dict[str, Any]:
        """Return dataset-level statistics."""
        if not self.frames:
            return {
                "num_episodes": 0,
                "num_frames": 0,
                "success_frames": 0,
                "failure_frames": 0,
                "slip_frames": 0,
                "seed24_like_frames": 0,
                "phase_distribution": {},
                "train_episodes": 0,
                "val_episodes": 0,
                "test_episodes": 0,
            }

        episodes: set[int] = set()
        success_frames = 0
        failure_frames = 0
        slip_frames = 0
        seed24_like_frames = 0
        phase_distribution: dict[str, int] = {}

        for frame in self.frames:
            episodes.add(frame.episode)
            if frame.success_label:
                success_frames += 1
            else:
                failure_frames += 1
            if frame.slip_signal is not None and frame.slip_signal.get("any_slip"):
                slip_frames += 1
            if _is_seed24_like(frame):
                seed24_like_frames += 1
            phase_distribution[frame.phase] = phase_distribution.get(frame.phase, 0) + 1

        train_eps = {f.episode for f in self.train} if self._train is not None else set()
        val_eps = {f.episode for f in self.val} if self._val is not None else set()
        test_eps = {f.episode for f in self.test} if self._test is not None else set()

        return {
            "num_episodes": len(episodes),
            "num_frames": len(self.frames),
            "success_frames": success_frames,
            "failure_frames": failure_frames,
            "slip_frames": slip_frames,
            "seed24_like_frames": seed24_like_frames,
            "phase_distribution": phase_distribution,
            "train_episodes": len(train_eps),
            "val_episodes": len(val_eps),
            "test_episodes": len(test_eps),
        }

    def to_feature_matrix(
        self,
        label_mode: str = "seed24_like",
        phase_list: list[str] | None = None,
        frames: list[ResidualFrame] | None = None,
    ) -> dict[str, Any]:
        """Build a numeric feature matrix from frames.

        Parameters
        ----------
        label_mode:
            How to derive the binary label. Supported modes:
            - ``seed24_like`` -- positive if the frame matches the seed-24-like
              heuristic (``_is_seed24_like``).
            - ``grip_failure`` -- positive for failed episodes whose
              ``failure_type`` contains ``grip`` or ``not_lifted``.
            - ``pair_rescued`` -- positive when ``pair_label == "rescued"``.
            - ``pair_failure`` -- positive when ``pair_label`` is one of
              ``rescued`` or ``unchanged_failure``.
        phase_list:
            Fixed phase ordering for one-hot encoding.  If ``None``, it is
            derived from the frames in this call.
        frames:
            Optional subset of frames.  Defaults to ``self.frames``.

        Returns
        -------
        dict with keys ``X`` (np.ndarray), ``y`` (np.ndarray),
        ``sample_weight`` (np.ndarray), ``phases`` (list[str]),
        ``feature_names`` (list[str]), and ``frames`` (list[ResidualFrame]).
        """
        frames = frames if frames is not None else self.frames
        if phase_list is None:
            phase_list = sorted({f.phase for f in frames})

        numeric_feature_defs = [
            ("object_z", lambda f, obs: obs.get("object_z") or 0.0),
            ("gripper_pos", lambda f, obs: obs.get("gripper_pos") or 0.0),
            ("eef_z", lambda f, obs: obs.get("eef_z") or 0.0),
            ("orientation_error", lambda f, obs: obs.get("orientation_error") or 0.0),
            ("object_eef_distance", lambda f, obs: obs.get("object_eef_distance") or 0.0),
            ("object_eef_yaw_delta", lambda f, obs: obs.get("object_eef_yaw_delta") or 0.0),
            ("gripper_too_open", lambda f, obs: float(f.grip_quality_signal is not None and f.grip_quality_signal.get("gripper_too_open", False))),
            ("low_object_z", lambda f, obs: float(f.grip_quality_signal is not None and f.grip_quality_signal.get("low_object_z", False))),
            ("any_slip", lambda f, obs: float(f.slip_signal is not None and f.slip_signal.get("any_slip", False))),
            ("slip_score", lambda f, obs: float((f.slip_signal.get("slip_score") or 0.0)) if f.slip_signal else 0.0),
            ("contact_confidence", lambda f, obs: float((f.contact_signal.get("confidence") or 0.0)) if f.contact_signal else 0.0),
            ("has_contact", lambda f, obs: float(f.contact_signal is not None and f.contact_signal.get("state") in {"stable", "contact", "grasp"})),
        ]

        feature_names = list(phase_list) + [name for name, _ in numeric_feature_defs]
        n = len(frames)
        d = len(feature_names)
        X = np.zeros((n, d), dtype=np.float32)
        y = np.zeros(n, dtype=np.float32)
        sample_weight = np.zeros(n, dtype=np.float32)

        for i, frame in enumerate(frames):
            obs = frame.observation
            if frame.phase in phase_list:
                X[i, phase_list.index(frame.phase)] = 1.0
            offset = len(phase_list)
            for j, (_, extractor) in enumerate(numeric_feature_defs):
                X[i, offset + j] = float(extractor(frame, obs))

            if label_mode == "seed24_like":
                y[i] = 1.0 if _is_seed24_like(frame) else 0.0
            elif label_mode == "grip_failure":
                y[i] = 1.0 if (not frame.success_label and frame.failure_type and any(k in (frame.failure_type or "").lower() for k in ("grip", "not_lifted", "slip"))) else 0.0
            elif label_mode == "pair_rescued":
                y[i] = 1.0 if frame.pair_label == "rescued" else 0.0
            elif label_mode == "pair_failure":
                y[i] = 1.0 if frame.pair_label in {"rescued", "unchanged_failure"} else 0.0
            else:
                raise ValueError(f"Unknown label_mode: {label_mode}")

            sample_weight[i] = float(frame.sample_weight)

        return {
            "X": X,
            "y": y,
            "sample_weight": sample_weight,
            "phases": phase_list,
            "feature_names": feature_names,
            "frames": frames,
        }

    def to_residual_target_matrix(
        self,
        phase_list: list[str] | None = None,
        frames: list[ResidualFrame] | None = None,
    ) -> dict[str, Any]:
        """Build a feature matrix and a bounded residual target matrix.

        The residual target is restricted to three axes:
        - ``dz`` -- residual_target[2]
        - ``dgripper`` -- residual_target[6]
        - ``lift_speed_scale`` -- 1.0 when no residual is requested, learned
          multiplier otherwise.  For training we treat the target scale as 1.0
          (no change) because the dataset does not yet contain explicit speed
          annotations.

        Returns
        -------
        dict with keys ``X``, ``Y`` (np.ndarray shape (n, 3)),
        ``sample_weight``, ``phases``, ``feature_names``, ``axes``,
        and ``frames``.
        """
        frames = frames if frames is not None else self.frames
        if phase_list is None:
            phase_list = sorted({f.phase for f in frames})

        numeric_feature_defs = [
            ("object_z", lambda f, obs: obs.get("object_z") or 0.0),
            ("gripper_pos", lambda f, obs: obs.get("gripper_pos") or 0.0),
            ("eef_z", lambda f, obs: obs.get("eef_z") or 0.0),
            ("orientation_error", lambda f, obs: obs.get("orientation_error") or 0.0),
            ("object_eef_distance", lambda f, obs: obs.get("object_eef_distance") or 0.0),
            ("object_eef_yaw_delta", lambda f, obs: obs.get("object_eef_yaw_delta") or 0.0),
            ("gripper_too_open", lambda f, obs: float(f.grip_quality_signal is not None and f.grip_quality_signal.get("gripper_too_open", False))),
            ("low_object_z", lambda f, obs: float(f.grip_quality_signal is not None and f.grip_quality_signal.get("low_object_z", False))),
            ("any_slip", lambda f, obs: float(f.slip_signal is not None and f.slip_signal.get("any_slip", False))),
            ("slip_score", lambda f, obs: float((f.slip_signal.get("slip_score") or 0.0)) if f.slip_signal else 0.0),
            ("contact_confidence", lambda f, obs: float((f.contact_signal.get("confidence") or 0.0)) if f.contact_signal else 0.0),
            ("has_contact", lambda f, obs: float(f.contact_signal is not None and f.contact_signal.get("state") in {"stable", "contact", "grasp"})),
        ]

        feature_names = list(phase_list) + [name for name, _ in numeric_feature_defs]
        axes = ["dz", "dgripper", "lift_speed_scale"]
        n = len(frames)
        d = len(feature_names)
        X = np.zeros((n, d), dtype=np.float32)
        Y = np.zeros((n, 3), dtype=np.float32)
        sample_weight = np.zeros(n, dtype=np.float32)

        for i, frame in enumerate(frames):
            obs = frame.observation
            if frame.phase in phase_list:
                X[i, phase_list.index(frame.phase)] = 1.0
            offset = len(phase_list)
            for j, (_, extractor) in enumerate(numeric_feature_defs):
                X[i, offset + j] = float(extractor(frame, obs))

            rt = frame.residual_target if frame.residual_target else [0.0] * 7
            dz = float(rt[2]) if len(rt) > 2 else 0.0
            dgripper = float(rt[6]) if len(rt) > 6 else 0.0
            # Default speed scale target is 1.0 (no change).
            speed_target = 1.0

            # Override with a seed-24-like lower-reclose target when the frame
            # matches the grip-quality signature.  This gives the bounded residual
            # micro-policy a concrete correction to learn instead of always no-op.
            if _is_seed24_like(frame) and frame.phase in {
                "GRASP", "LIFT", "HOLD", "VERIFY_OBJECT_FOLLOWING", "GRIP_QUALITY_RECOVERY"
            }:
                dz = 0.015
                dgripper = -0.05

            Y[i, :] = [dz, dgripper, speed_target]
            # Up-weight seed-24-like frames so the minority correction class is
            # not drowned out by the overwhelming no-op majority.
            weight_factor = 5.0 if _is_seed24_like(frame) else 1.0
            sample_weight[i] = float(frame.sample_weight) * weight_factor


        return {
            "X": X,
            "Y": Y,
            "sample_weight": sample_weight,
            "phases": phase_list,
            "feature_names": feature_names,
            "axes": axes,
            "frames": frames,
        }

    def to_route_label_matrix(
        self,
        phase_list: list[str] | None = None,
        frames: list[ResidualFrame] | None = None,
    ) -> dict[str, Any]:
        """Build a feature matrix and integer route-label target.

        Only frames with a non-null ``route_label`` in the v1.10 route schema
        are returned.  The target is an integer class index aligned with the
        ``ROUTE_CLASSES`` ordering in ``rosclaw_darwin.learning.route_classifier``.

        Returns
        -------
        dict with keys ``X`` (np.ndarray), ``y`` (np.ndarray of int class
        indices), ``sample_weight``, ``phases``, ``feature_names``,
        ``route_classes``, and ``frames``.
        """
        from rosclaw_darwin.learning.route_classifier import ROUTE_CLASS_TO_INDEX, ROUTE_CLASSES

        frames = frames if frames is not None else self.frames
        frames = [f for f in frames if f.route_label in ROUTE_CLASS_TO_INDEX]
        if phase_list is None:
            phase_list = sorted({f.phase for f in frames})

        numeric_feature_defs = [
            ("object_z", lambda f, obs: obs.get("object_z") or 0.0),
            ("gripper_pos", lambda f, obs: obs.get("gripper_pos") or 0.0),
            ("eef_z", lambda f, obs: obs.get("eef_z") or 0.0),
            ("orientation_error", lambda f, obs: obs.get("orientation_error") or 0.0),
            ("object_eef_distance", lambda f, obs: obs.get("object_eef_distance") or 0.0),
            ("object_eef_yaw_delta", lambda f, obs: obs.get("object_eef_yaw_delta") or 0.0),
            ("gripper_too_open", lambda f, obs: float(f.grip_quality_signal is not None and f.grip_quality_signal.get("gripper_too_open", False))),
            ("low_object_z", lambda f, obs: float(f.grip_quality_signal is not None and f.grip_quality_signal.get("low_object_z", False))),
            ("any_slip", lambda f, obs: float(f.slip_signal is not None and f.slip_signal.get("any_slip", False))),
            ("slip_score", lambda f, obs: float((f.slip_signal.get("slip_score") or 0.0)) if f.slip_signal else 0.0),
            ("contact_confidence", lambda f, obs: float((f.contact_signal.get("confidence") or 0.0)) if f.contact_signal else 0.0),
            ("has_contact", lambda f, obs: float(f.contact_signal is not None and f.contact_signal.get("state") in {"stable", "contact", "grasp"})),
        ]

        feature_names = list(phase_list) + [name for name, _ in numeric_feature_defs]
        n = len(frames)
        d = len(feature_names)
        X = np.zeros((n, d), dtype=np.float32)
        y = np.zeros(n, dtype=np.int64)
        sample_weight = np.zeros(n, dtype=np.float32)

        for i, frame in enumerate(frames):
            obs = frame.observation
            if frame.phase in phase_list:
                X[i, phase_list.index(frame.phase)] = 1.0
            offset = len(phase_list)
            for j, (_, extractor) in enumerate(numeric_feature_defs):
                X[i, offset + j] = float(extractor(frame, obs))

            y[i] = ROUTE_CLASS_TO_INDEX[frame.route_label]
            sample_weight[i] = float(frame.sample_weight)

        return {
            "X": X,
            "y": y,
            "sample_weight": sample_weight,
            "phases": phase_list,
            "feature_names": feature_names,
            "route_classes": ROUTE_CLASSES,
            "frames": frames,
        }

    def save(self, output_dir: str | Path, force_jsonl: bool = False) -> None:
        """Write dataset artifacts to ``output_dir``.

        Files produced:
        - ``frames.parquet`` (if pandas/pyarrow available, else JSONL)
        - ``frames.jsonl`` (when ``force_jsonl=True`` or parquet is unavailable)
        - ``episodes.jsonl`` (one line per episode with metadata)
        - ``metadata.yaml`` (dataset statistics and build info)
        - ``split_train.json``, ``split_val.json``, ``split_test.json``
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write frames.
        wrote_jsonl = False
        if not force_jsonl:
            try:
                import pandas as pd

                records = [f.model_dump() for f in self.frames]
                df = pd.json_normalize(records, sep="_")
                df.to_parquet(output_dir / "frames.parquet", index=False)
            except Exception:
                # Fallback to JSONL if pandas/parquet is unavailable.
                with (output_dir / "frames.jsonl").open("w") as fh:
                    for frame in self.frames:
                        fh.write(json.dumps(frame.model_dump(), default=str) + "\n")
                wrote_jsonl = True
        else:
            with (output_dir / "frames.jsonl").open("w") as fh:
                for frame in self.frames:
                    fh.write(json.dumps(frame.model_dump(), default=str) + "\n")
            wrote_jsonl = True

        # Parquet with nested dicts/lists can be hard to round-trip; keep JSONL
        # available as a robust fallback for downstream tools.
        if not wrote_jsonl:
            try:
                with (output_dir / "frames.jsonl").open("w") as fh:
                    for frame in self.frames:
                        fh.write(json.dumps(frame.model_dump(), default=str) + "\n")
            except Exception:
                pass

        # Write episode metadata.
        episodes: dict[int, dict[str, Any]] = {}
        for frame in self.frames:
            eid = frame.episode
            if eid not in episodes:
                episodes[eid] = {
                    "episode": eid,
                    "task": frame.task,
                    "object_name": frame.object_name,
                    "seed": frame.seed,
                    "success": frame.success_label,
                    "failure_type": frame.failure_type,
                    "num_frames": 0,
                }
            episodes[eid]["num_frames"] += 1

        with (output_dir / "episodes.jsonl").open("w") as fh:
            for meta in episodes.values():
                fh.write(json.dumps(meta, default=str) + "\n")

        # Write metadata.
        stats = self.statistics()
        metadata = {
            "dataset": "residual_learning",
            "version": "v2",
            "num_frames": stats["num_frames"],
            "num_episodes": stats["num_episodes"],
            "success_frames": stats["success_frames"],
            "failure_frames": stats["failure_frames"],
            "slip_frames": stats["slip_frames"],
            "seed24_like_frames": stats["seed24_like_frames"],
            "phase_distribution": stats["phase_distribution"],
            "splits": {
                "train_episodes": stats["train_episodes"],
                "val_episodes": stats["val_episodes"],
                "test_episodes": stats["test_episodes"],
            },
        }
        with (output_dir / "metadata.yaml").open("w") as fh:
            yaml.dump(metadata, fh, sort_keys=False, allow_unicode=True)

        # Write label manifests for v1.10 downstream tasks.
        pair_labels: list[dict[str, Any]] = []
        route_labels: list[dict[str, Any]] = []
        medium_ood_labels: list[dict[str, Any]] = []
        for frame in self.frames:
            base = {"episode": frame.episode, "step": frame.step, "seed": frame.seed, "phase": frame.phase}
            if frame.pair_label is not None:
                pair_labels.append({**base, "pair_label": frame.pair_label})
            if frame.route_label is not None:
                route_labels.append({**base, "route_label": frame.route_label})
            if frame.medium_ood_label is not None:
                medium_ood_labels.append({**base, "medium_ood_label": frame.medium_ood_label})

        def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
            if not records:
                return
            with path.open("w") as fh:
                for rec in records:
                    fh.write(json.dumps(rec, default=str) + "\n")

        _write_jsonl(output_dir / "pair_labels.jsonl", pair_labels)
        _write_jsonl(output_dir / "route_labels.jsonl", route_labels)
        _write_jsonl(output_dir / "medium_ood_labels.jsonl", medium_ood_labels)

        # Write split manifests.
        def _write_split(name: str, frames: list[ResidualFrame]) -> None:
            eps = sorted({f.episode for f in frames})
            with (output_dir / f"split_{name}.json").open("w") as fh:
                json.dump({"episodes": eps, "count": len(eps)}, fh, indent=2)

        _write_split("train", self.train)
        _write_split("val", self.val)
        _write_split("test", self.test)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_action(record: dict[str, Any]) -> list[float]:
    """Best-effort extraction of the executed action vector from a trace record."""
    # Prefer explicit action fields if present.
    for key in ("action", "executed_action", "command"):
        val = record.get(key)
        if isinstance(val, list):
            return [float(v) for v in val]
    # Fallback: reconstruct from positional/rotational/gripper components.
    components: list[float] = []
    for key in ("dx", "dy", "dz", "droll", "dpitch", "dyaw", "dgripper"):
        if key in record:
            components.append(float(record[key]))
    if components:
        return components
    # Last resort: use action_norm as a scalar (not ideal but safe).
    norm = record.get("action_norm")
    if norm is not None:
        return [float(norm)]
    return []


def _extract_heuristic_action(record: dict[str, Any]) -> list[float]:
    """Extract heuristic action if explicitly logged; otherwise empty."""
    val = record.get("heuristic_action")
    if isinstance(val, list):
        return [float(v) for v in val]
    return []


def _extract_observation(record: dict[str, Any]) -> dict[str, Any]:
    """Extract observation-relevant fields from a trace record."""
    obs_keys = {
        "eef_x",
        "eef_y",
        "eef_z",
        "eef_roll",
        "eef_pitch",
        "eef_yaw",
        "object_x",
        "object_y",
        "object_z",
        "object_yaw",
        "target_x",
        "target_y",
        "target_z",
        "target_yaw",
        "gripper_pos",
        "orientation_error",
        "object_eef_distance",
        "object_eef_yaw_delta",
    }
    return {k: record[k] for k in obs_keys if k in record}


def _extract_signal(record: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    """Extract a signal dict prefixed with ``prefix_`` from the record."""
    signal: dict[str, Any] = {}
    prefix_with_underscore = prefix + "_"
    for key, value in record.items():
        if key.startswith(prefix_with_underscore):
            short_key = key[len(prefix_with_underscore) :]
            signal[short_key] = value
    # Also accept the exact key if it is a dict.
    if prefix in record and isinstance(record[prefix], dict):
        signal.update(record[prefix])
    return signal if signal else None


def _enrich_grip_quality_signal(
    signal: dict[str, Any], observation: dict[str, Any]
) -> dict[str, Any]:
    """Add inferred booleans to a grip-quality signal when they are missing.

    Older traces may only contain the raw ``object_z`` / ``gripper_pos``
    observation fields. This helper derives ``low_object_z`` and
    ``gripper_too_open`` so that seed-24-like detection works uniformly.
    """
    enriched = dict(signal)
    if "low_object_z" not in enriched:
        obj_z = observation.get("object_z")
        if obj_z is not None:
            enriched["low_object_z"] = bool(obj_z < SEED24_OBJECT_Z_THRESHOLD)
    if "gripper_too_open" not in enriched:
        gripper_pos = observation.get("gripper_pos")
        if gripper_pos is not None:
            enriched["gripper_too_open"] = bool(gripper_pos > SEED24_GRIPPER_POS_THRESHOLD)
    return enriched


def _is_seed24_like(frame: ResidualFrame) -> bool:
    """Heuristic: does this frame look like a seed-24 signature?"""
    if frame.success_label:
        return False
    gq = frame.grip_quality_signal
    if gq is not None:
        if gq.get("low_object_z") and gq.get("gripper_too_open"):
            return True
    # Fallback: check observation proxies.
    obs = frame.observation
    obj_z = obs.get("object_z")
    gripper_pos = obs.get("gripper_pos")
    if obj_z is not None and gripper_pos is not None:
        if obj_z < SEED24_OBJECT_Z_THRESHOLD and gripper_pos > SEED24_GRIPPER_POS_THRESHOLD:
            return True
    return False
