"""Unit tests for the evaluation runtime registry."""

from __future__ import annotations

import pytest

from rosclaw_darwin.evaluation.runtime import (
    EvalRuntime,
    get_darwin_home,
    get_eval_runtimes_path,
    get_runtime,
    list_runtimes,
    load_eval_runtimes,
    register_runtime,
    save_eval_runtimes,
)


@pytest.fixture
def isolated_darwin_home(tmp_path, monkeypatch) -> None:
    """Point ROSCLAW_DARWIN_HOME at a temp directory for the duration of the test."""
    monkeypatch.setenv("ROSCLAW_DARWIN_HOME", str(tmp_path / "darwin_home"))


def test_get_darwin_home_defaults_to_user_dir(monkeypatch) -> None:
    monkeypatch.delenv("ROSCLAW_DARWIN_HOME", raising=False)
    home = get_darwin_home()
    assert home.name == "darwin"
    assert home.parent.name == ".rosclaw"


def test_get_darwin_home_reads_env(monkeypatch, tmp_path) -> None:
    custom = str(tmp_path / "custom_darwin")
    monkeypatch.setenv("ROSCLAW_DARWIN_HOME", custom)
    assert str(get_darwin_home()) == custom


def test_get_eval_runtimes_path(isolated_darwin_home, tmp_path) -> None:
    path = get_eval_runtimes_path()
    assert path.name == "eval_runtimes.yaml"
    assert path.parent.name == "darwin_home"


def test_register_and_list_runtime(isolated_darwin_home) -> None:
    runtime = EvalRuntime(
        name="lerobot_default",
        mode="external",
        python="/usr/bin/python3",
        lerobot_eval="lerobot-eval",
        gpu=True,
        environment={"CUDA_VISIBLE_DEVICES": "0"},
        tags=["lerobot", "pusht"],
    )
    registered = register_runtime("lerobot_default", runtime)

    assert registered.name == "lerobot_default"
    runtimes = list_runtimes()
    assert "lerobot_default" in runtimes
    assert runtimes["lerobot_default"].mode == "external"
    assert runtimes["lerobot_default"].gpu is True
    assert runtimes["lerobot_default"].tags == ["lerobot", "pusht"]


def test_get_runtime(isolated_darwin_home) -> None:
    runtime = EvalRuntime(name="docker_runtime", mode="docker", image="lerobot/runtime:latest")
    register_runtime("docker_runtime", runtime)

    found = get_runtime("docker_runtime")
    assert found.mode == "docker"
    assert found.image == "lerobot/runtime:latest"

    with pytest.raises(KeyError, match="No eval runtime registered"):
        get_runtime("missing")


def test_save_and_load_roundtrip(isolated_darwin_home, tmp_path) -> None:
    runtimes = {
        "r1": EvalRuntime(
            name="r1",
            mode="external",
            python="/venv/bin/python",
            lerobot_eval="/venv/bin/lerobot-eval",
            workdir="/workspace",
            gpu=True,
            environment={"HF_HOME": "/cache"},
            tags=["a", "b"],
        ),
        "r2": EvalRuntime(
            name="r2",
            mode="docker",
            image="rosclaw/lerobot:latest",
            gpu=False,
        ),
    }
    save_eval_runtimes(runtimes)

    loaded = load_eval_runtimes()
    assert len(loaded) == 2
    assert loaded["r1"].python == "/venv/bin/python"
    assert loaded["r1"].environment == {"HF_HOME": "/cache"}
    assert loaded["r2"].mode == "docker"
    assert loaded["r2"].image == "rosclaw/lerobot:latest"
    assert loaded["r2"].tags == []


def test_register_updates_existing_runtime(isolated_darwin_home) -> None:
    register_runtime("mutable", EvalRuntime(name="mutable", mode="external", gpu=False))
    register_runtime("mutable", EvalRuntime(name="mutable", mode="docker", image="new:latest"))

    runtime = get_runtime("mutable")
    assert runtime.mode == "docker"
    assert runtime.image == "new:latest"
    assert runtime.gpu is False
