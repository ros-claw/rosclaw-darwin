"""Tests for suite creation filtering."""

import yaml


class TestSuiteFilter:
    def test_filter_executable(self, tmp_path):
        from rosclaw_darwin.cli.main import _task_matches_filter

        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "id": "t1",
            "name": "T1",
            "scene": {"name": "kitchen"},
            "embodiment": {"robot": "franka"},
            "execution": {"executable": True, "backend": "arena"},
        }))
        assert _task_matches_filter(str(task_file), "execution.executable=true") is True
        assert _task_matches_filter(str(task_file), "execution.executable=false") is False
        assert _task_matches_filter(str(task_file), "execution.backend=arena") is True

    def test_filter_semantic_only(self, tmp_path):
        from rosclaw_darwin.cli.main import _task_matches_filter

        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "id": "t2",
            "name": "T2",
            "scene": {"name": "household"},
            "embodiment": {"robot": "unitree_g1"},
            "execution": {"semantic_only": True, "backend": "behavior_semantic"},
        }))
        assert _task_matches_filter(str(task_file), "execution.semantic_only=true") is True
        assert _task_matches_filter(str(task_file), "execution.backend=behavior_semantic") is True
        assert _task_matches_filter(str(task_file), "execution.executable=true") is False

    def test_filter_defaults_for_old_task(self, tmp_path):
        from rosclaw_darwin.cli.main import _task_matches_filter

        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "id": "t3",
            "name": "T3",
            "scene": {"name": "table"},
            "embodiment": {"robot": "franka"},
        }))
        assert _task_matches_filter(str(task_file), "execution.executable=false") is True
        assert _task_matches_filter(str(task_file), "execution.backend=unknown") is True
