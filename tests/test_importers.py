"""Tests for source importers."""

from rosclaw_darwin.sources.behavior1k import Behavior1KImporter
from rosclaw_darwin.sources.lw_benchhub import LWBenchHubImporter
from rosclaw_darwin.sources.robotwin import RoboTwinImporter


class TestLWImporter:
    def test_scan_empty_repo(self, tmp_path):
        importer = LWBenchHubImporter(repo_path=tmp_path)
        records = importer.scan()
        assert records == []

    def test_import_fallback(self, tmp_path):
        importer = LWBenchHubImporter(repo_path=tmp_path)
        task = importer.import_task({"name": "test_task", "environment": "env1"})
        assert task.id.startswith("lw_")
        assert task.provenance.source == "lw_benchhub"


class TestRoboTwinImporter:
    def test_scan_empty_repo(self, tmp_path):
        importer = RoboTwinImporter(repo_path=tmp_path)
        records = importer.scan()
        assert records == []


class TestBehavior1KImporter:
    def test_scan_empty_repo(self, tmp_path):
        importer = Behavior1KImporter(repo_path=tmp_path)
        records = importer.scan()
        assert records == []

    def test_import_bddl(self, tmp_path):
        importer = Behavior1KImporter(repo_path=tmp_path)
        task = importer.import_task({
            "_type": "bddl",
            "name": "clean_kitchen",
            "raw": "(:goal (and (ontop ?milk.n.01_1 ?counter.n.01_1)))",
        })
        assert task.id.startswith("behavior1k_")
        assert task.metadata.get("semantic_only") is True
