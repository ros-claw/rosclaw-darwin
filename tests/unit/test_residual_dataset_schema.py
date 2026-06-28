"""Unit tests for ResidualFrame schema and ResidualDataset construction."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from rosclaw_darwin.learning.residual_dataset import (
    ResidualDataset,
    ResidualFrame,
    _extract_action,
    _extract_heuristic_action,
    _extract_observation,
    _extract_signal,
    _is_seed24_like,
)


def test_residual_frame_v2_fields():
    frame = ResidualFrame(
        episode=1,
        step=0,
        task="t",
        phase="GRASP",
        pair_label="rescued",
        route_label="lower_regrip",
        medium_ood_label="first_failing_subtask",
        trigger_model_score=0.88,
        bounded_residual=[0.0, 0.0, 0.004, 0.0, 0.0, 0.0, 0.05],
    )
    assert frame.pair_label == "rescued"
    assert frame.route_label == "lower_regrip"
    assert frame.medium_ood_label == "first_failing_subtask"
    assert frame.trigger_model_score == 0.88
    assert frame.bounded_residual == [0.0, 0.0, 0.004, 0.0, 0.0, 0.0, 0.05]


def test_save_outputs_v2_label_files():
    """save() should emit pair_labels.jsonl, route_labels.jsonl, and medium_ood_labels.jsonl."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_024"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="GRASP", action=[0.0], heuristic_action=[0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {"episodes": [{"episode_id": 1, "success": False, "task": "goal_pose"}]}
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path)
        ds.frames[0].pair_label = "rescued"
        ds.frames[0].route_label = "lower_regrip"
        ds.frames[0].medium_ood_label = "first_failing_subtask"

        output_dir = Path(tmpdir) / "dataset"
        ds.save(output_dir)

        assert (output_dir / "pair_labels.jsonl").exists()
        assert (output_dir / "route_labels.jsonl").exists()
        assert (output_dir / "medium_ood_labels.jsonl").exists()

        pair_labels = [json.loads(line) for line in (output_dir / "pair_labels.jsonl").open()]
        assert len(pair_labels) == 1
        assert pair_labels[0]["pair_label"] == "rescued"

        route_labels = [json.loads(line) for line in (output_dir / "route_labels.jsonl").open()]
        assert route_labels[0]["route_label"] == "lower_regrip"


def test_residual_frame_schema_defaults():
    """ResidualFrame should validate with minimal fields and provide defaults."""
    frame = ResidualFrame(episode=1, step=0, task="t1", phase="APPROACH")
    assert frame.episode == 1
    assert frame.step == 0
    assert frame.task == "t1"
    assert frame.phase == "APPROACH"
    assert frame.observation == {}
    assert frame.heuristic_action == []
    assert frame.executed_action == []
    assert frame.success_label is False
    assert frame.failure_type is None
    assert frame.contact_signal is None
    assert frame.slip_signal is None
    assert frame.grip_quality_signal is None
    assert frame.residual_target == []
    assert frame.residual_mask == []
    assert frame.sample_weight == 1.0


def test_residual_frame_full_construction():
    frame = ResidualFrame(
        episode=2,
        step=5,
        task="goal_pose",
        object_name="dex_cube",
        seed=24,
        phase="GRASP",
        observation={"eef_x": 0.1},
        heuristic_action=[0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        executed_action=[0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        success_label=False,
        failure_type="object_not_lifted",
        contact_signal={"state": "likely_contact"},
        slip_signal={"any_slip": True},
        grip_quality_signal={"low_object_z": True, "gripper_too_open": False},
        residual_target=[0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        residual_mask=[True, False, True, True, True, True, True],
        sample_weight=2.0,
    )
    assert frame.seed == 24
    assert frame.failure_type == "object_not_lifted"
    assert frame.contact_signal["state"] == "likely_contact"
    assert frame.sample_weight == 2.0


def test_residual_frame_serialization():
    frame = ResidualFrame(
        episode=1, step=0, task="t", phase="APPROACH", residual_target=[0.1, -0.05]
    )
    dumped = frame.model_dump()
    assert dumped["episode"] == 1
    assert dumped["residual_target"] == [0.1, -0.05]


# ---------------------------------------------------------------------------
# Dataset construction from synthetic traces
# ---------------------------------------------------------------------------


def _make_trace_record(
    step: int = 0,
    phase: str = "APPROACH",
    action: list[float] | None = None,
    heuristic_action: list[float] | None = None,
    eef_x: float = 0.0,
    object_z: float = 0.025,
    gripper_pos: float = 0.02,
    episode: int = 1,
) -> dict:
    rec: dict = {
        "episode": episode,
        "step": step,
        "phase": phase,
        "eef_x": eef_x,
        "object_z": object_z,
        "gripper_pos": gripper_pos,
    }
    if action is not None:
        rec["action"] = action
    if heuristic_action is not None:
        rec["heuristic_action"] = heuristic_action
    return rec


def test_from_traces_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_000"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
            _make_trace_record(step=1, phase="GRASP", action=[0.0, 0.0, -0.01], heuristic_action=[0.0, 0.0, -0.01]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {"episode_id": 1, "success": True, "task": "goal_pose", "failure_type": None}
            ]
        }
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path)
        assert len(ds.frames) == 2
        assert ds.frames[0].success_label is True
        assert ds.frames[0].residual_target == [0.0, 0.0, 0.0]
        assert ds.frames[0].sample_weight == 1.0


def test_from_traces_seed_success_map_overrides_summary():
    """seed_success_map should override summary metadata for matching seeds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_024"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {"episode_id": 1, "success": False, "task": "goal_pose", "failure_type": "object_not_lifted"}
            ]
        }
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(
            tmpdir,
            summary_path=summary_path,
            seed_success_map={24: True},
        )
        assert len(ds.frames) == 1
        assert ds.frames[0].success_label is True
        assert ds.frames[0].sample_weight == 1.0


def test_from_traces_seed_success_map_ignores_unknown_seeds():
    """seed_success_map should not affect seeds that are not present in the map."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_007"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {"episode_id": 1, "success": False, "task": "goal_pose", "failure_type": "object_not_lifted"}
            ]
        }
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(
            tmpdir,
            summary_path=summary_path,
            seed_success_map={24: True},
        )
        assert ds.frames[0].success_label is False


def test_from_traces_trace_success_map_overrides_seed_map():
    """trace_success_map should take precedence over seed_success_map and summary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_024"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {"episode_id": 1, "success": False, "task": "goal_pose", "failure_type": "object_not_lifted"}
            ]
        }
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        trace_key = "seed_024/trace.jsonl"
        ds = ResidualDataset.from_traces(
            tmpdir,
            summary_path=summary_path,
            seed_success_map={24: False},
            trace_success_map={trace_key: True},
        )
        assert len(ds.frames) == 1
        assert ds.frames[0].success_label is True
        assert ds.frames[0].sample_weight == 1.0


def test_from_traces_trace_success_map_ignores_unknown_traces():
    """trace_success_map should not affect traces that are not present in the map."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_024"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {"episode_id": 1, "success": False, "task": "goal_pose", "failure_type": "object_not_lifted"}
            ]
        }
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(
            tmpdir,
            summary_path=summary_path,
            trace_success_map={"other/trace.jsonl": True},
        )
        assert ds.frames[0].success_label is False


def test_from_traces_enriches_grip_quality_signal_from_observation():
    """Grip quality signal should gain low_object_z / gripper_too_open from observation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_024"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(
                step=0,
                phase="GRASP",
                action=[0.0, 0.0, -0.01],
                heuristic_action=[0.0, 0.0, -0.01],
                object_z=0.020,
                gripper_pos=0.040,
            ),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {"episodes": [{"episode_id": 1, "success": False, "task": "goal_pose"}]}
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path)
        gq = ds.frames[0].grip_quality_signal
        assert gq is not None
        assert gq.get("low_object_z") is True
        assert gq.get("gripper_too_open") is True


def test_from_traces_failure_weight():
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_001"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.05, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {"episode_id": 1, "success": False, "task": "goal_pose", "failure_type": "grasp_failed"}
            ]
        }
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path, failure_weight=2.5)
        assert len(ds.frames) == 1
        assert ds.frames[0].success_label is False
        assert ds.frames[0].sample_weight == 2.5
        assert ds.frames[0].residual_target == [0.05, 0.0, 0.0]


def test_from_traces_missing_heuristic_action_defaults_to_executed():
    """When heuristic_action is missing, residual_target should be zero."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_002"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {"episodes": [{"episode_id": 1, "success": True, "task": "t"}]}
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path)
        assert ds.frames[0].heuristic_action == [0.1, 0.0, 0.0]
        assert ds.frames[0].executed_action == [0.1, 0.0, 0.0]
        assert ds.frames[0].residual_target == [0.0, 0.0, 0.0]


def test_to_feature_matrix_seed24_like():
    """to_feature_matrix should produce the expected label for seed24-like frames."""
    frames = [
        ResidualFrame(
            episode=1,
            step=0,
            task="goal_pose",
            phase="GRASP",
            success_label=False,
            observation={"object_z": 0.01, "gripper_pos": 0.04},
            grip_quality_signal={"low_object_z": True, "gripper_too_open": True},
        ),
        ResidualFrame(
            episode=2,
            step=0,
            task="goal_pose",
            phase="GRASP",
            success_label=True,
            observation={"object_z": 0.05, "gripper_pos": 0.02},
        ),
    ]
    ds = ResidualDataset(frames)
    mat = ds.to_feature_matrix(label_mode="seed24_like")
    assert mat["X"].shape == (2, len(mat["feature_names"]))
    assert mat["y"][0] == 1.0
    assert mat["y"][1] == 0.0
    assert "GRASP" in mat["phases"]


def test_from_saved_roundtrip():
    """from_saved should reconstruct a dataset written by save()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_000"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {"episodes": [{"episode_id": 1, "success": True, "task": "goal_pose"}]}
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path)
        output_dir = Path(tmpdir) / "dataset"
        ds.save(output_dir)

        loaded = ResidualDataset.from_saved(output_dir)
        assert len(loaded.frames) == 1
        assert loaded.frames[0].phase == "APPROACH"
        # With a single episode the split logic assigns it to test.
        assert loaded.test
        assert loaded.frames[0].episode in {f.episode for f in loaded.test}


def test_from_traces_residual_mask_defaults_all_true():
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_003"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, action=[0.1, 0.2, 0.3], heuristic_action=[0.0, 0.1, 0.2]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {"episodes": [{"episode_id": 1, "success": True, "task": "t"}]}
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path)
        assert ds.frames[0].residual_mask == [True, True, True]


def test_train_val_test_split_stratified():
    """Splits should be stratified by success_label and sum to total episodes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(10):
            trace_dir = Path(tmpdir) / f"seed_{i:03d}"
            trace_dir.mkdir()
            trace_file = trace_dir / "trace.jsonl"
            records = [_make_trace_record(step=0, action=[0.0], heuristic_action=[0.0], episode=i + 1)]
            with trace_file.open("w") as fh:
                for rec in records:
                    fh.write(json.dumps(rec) + "\n")

        episodes = []
        for i in range(10):
            episodes.append(
                {"episode_id": i + 1, "success": i < 5, "task": "t", "failure_type": None}
            )
        summary = {"episodes": episodes}
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(
            tmpdir, summary_path=summary_path, train_ratio=0.6, val_ratio=0.2, test_ratio=0.2, random_seed=7
        )
        train_eps = {f.episode for f in ds.train}
        val_eps = {f.episode for f in ds.val}
        test_eps = {f.episode for f in ds.test}

        assert len(train_eps & val_eps) == 0
        assert len(train_eps & test_eps) == 0
        assert len(val_eps & test_eps) == 0
        assert len(train_eps | val_eps | test_eps) == 10

        # Stratification: both success and failure should appear in train.
        train_success = any(f.success_label for f in ds.train)
        train_failure = any(not f.success_label for f in ds.train)
        assert train_success and train_failure


def test_statistics():
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_000"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.0], heuristic_action=[0.0]),
            _make_trace_record(step=1, phase="GRASP", action=[0.0], heuristic_action=[0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {"episodes": [{"episode_id": 1, "success": True, "task": "t"}]}
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path)
        stats = ds.statistics()
        assert stats["num_episodes"] == 1
        assert stats["num_frames"] == 2
        assert stats["success_frames"] == 2
        assert stats["failure_frames"] == 0
        assert stats["phase_distribution"]["APPROACH"] == 1
        assert stats["phase_distribution"]["GRASP"] == 1


# ---------------------------------------------------------------------------
# Helper extraction tests
# ---------------------------------------------------------------------------


def test_extract_action_explicit():
    assert _extract_action({"action": [0.1, 0.2]}) == [0.1, 0.2]
    assert _extract_action({"executed_action": [0.3]}) == [0.3]
    assert _extract_action({"command": [0.4, 0.5]}) == [0.4, 0.5]


def test_extract_action_fallback_components():
    assert _extract_action({"dx": 0.1, "dy": 0.2, "dz": -0.1}) == [0.1, 0.2, -0.1]


def test_extract_action_fallback_norm():
    assert _extract_action({"action_norm": 1.5}) == [1.5]


def test_extract_action_empty():
    assert _extract_action({}) == []


def test_extract_heuristic_action():
    assert _extract_heuristic_action({"heuristic_action": [0.1]}) == [0.1]
    assert _extract_heuristic_action({}) == []


def test_extract_observation():
    obs = _extract_observation({"eef_x": 0.1, "object_z": 0.2, "extra": 99})
    assert "eef_x" in obs
    assert "object_z" in obs
    assert "extra" not in obs


def test_extract_signal():
    record = {
        "contact_state": "likely_contact",
        "contact_confidence": 0.8,
        "slip_any_slip": True,
        "slip_score": 3.2,
    }
    contact = _extract_signal(record, "contact")
    assert contact == {"state": "likely_contact", "confidence": 0.8}
    slip = _extract_signal(record, "slip")
    assert slip == {"any_slip": True, "score": 3.2}


def test_extract_signal_dict_value():
    record = {"contact": {"state": "no_contact"}}
    contact = _extract_signal(record, "contact")
    assert contact == {"state": "no_contact"}


def test_extract_signal_none():
    assert _extract_signal({}, "contact") is None


# ---------------------------------------------------------------------------
# Seed-24-like detection
# ---------------------------------------------------------------------------


def test_is_seed24_like_from_grip_quality_signal():
    frame = ResidualFrame(
        episode=1,
        step=0,
        task="t",
        phase="GRASP",
        success_label=False,
        grip_quality_signal={"low_object_z": True, "gripper_too_open": True},
    )
    assert _is_seed24_like(frame) is True


def test_is_seed24_like_from_observation():
    frame = ResidualFrame(
        episode=1,
        step=0,
        task="t",
        phase="GRASP",
        success_label=False,
        observation={"object_z": 0.020, "gripper_pos": 0.040},
    )
    assert _is_seed24_like(frame) is True


def test_is_seed24_like_success_false():
    frame = ResidualFrame(
        episode=1,
        step=0,
        task="t",
        phase="GRASP",
        success_label=True,
        observation={"object_z": 0.020, "gripper_pos": 0.040},
    )
    assert _is_seed24_like(frame) is False


def test_is_seed24_like_not_matching():
    frame = ResidualFrame(
        episode=1,
        step=0,
        task="t",
        phase="GRASP",
        success_label=False,
        observation={"object_z": 0.030, "gripper_pos": 0.020},
    )
    assert _is_seed24_like(frame) is False
