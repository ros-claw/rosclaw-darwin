"""Tests for MemoryStore."""

from rosclaw_darwin.integration.memory_store import MemoryStore


class TestMemoryStore:
    def test_file_backend_record_and_query(self, tmp_path):
        store = MemoryStore(tmp_path / "exp.jsonl", backend="file")
        store.record({
            "task_id": "t1",
            "task_name": "Task One",
            "run_id": "r1",
            "adapter": "mock",
            "metrics": {"success_rate": 0.2},
            "failure_types": {"grasp_miss": 1},
            "task_text": "pick the red cube",
        })
        store.record({
            "task_id": "t1",
            "task_name": "Task One",
            "run_id": "r2",
            "adapter": "mock",
            "metrics": {"success_rate": 0.9},
            "failure_types": {},
            "task_text": "pick the red cube",
        })
        assert store.count() == 2
        assert len(store.query(task_id="t1")) == 2
        assert len(store.query(failure_type="grasp_miss")) == 1
        assert store.query(failure_type="grasp_miss")[0]["run_id"] == "r1"

    def test_file_backend_persists_and_reloads(self, tmp_path):
        path = tmp_path / "exp.jsonl"
        store = MemoryStore(path, backend="file")
        store.record({"task_id": "t1", "run_id": "r1", "adapter": "mock", "metrics": {"success_rate": 0.5}, "failure_types": {}})
        del store
        store2 = MemoryStore(path, backend="file")
        assert store2.count() == 1
        assert store2.query(task_id="t1")[0]["run_id"] == "r1"

    def test_consolidate_memory_bonus(self, tmp_path):
        store = MemoryStore(tmp_path / "exp.jsonl", backend="file")
        for i in range(3):
            store.record({
                "task_id": "t1",
                "run_id": f"r{i}",
                "adapter": "mock",
                "metrics": {"success_rate": 0.0},
                "failure_types": {"miss": 1},
            })
        result = store.consolidate(task_id="t1")
        assert result["count"] == 3
        assert result["failures"] == 3
        assert result["memory_bonus"] == min(0.3, 0.05 * 3)

    def test_vector_backend_similarity(self, tmp_path):
        store = MemoryStore(tmp_path / "vec.jsonl", backend="vector", embedding_model="keyword")
        store.record({
            "task_id": "pick_cube",
            "task_name": "Pick Cube",
            "run_id": "r1",
            "adapter": "mock",
            "metrics": {"success_rate": 0.2},
            "failure_types": {"grasp_miss": 2},
            "task_text": "pick the red cube from the table",
        })
        store.record({
            "task_id": "place_cup",
            "task_name": "Place Cup",
            "run_id": "r2",
            "adapter": "mock",
            "metrics": {"success_rate": 0.4},
            "failure_types": {"collision": 1},
            "task_text": "place the cup on the shelf",
        })
        similar = store.query_similar("pick cube from table", top_k=2)
        assert similar[0]["task_id"] == "pick_cube"
