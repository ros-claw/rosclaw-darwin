"""Build Arena eval job configs from TDL tasks."""

from __future__ import annotations

from typing import Any

from rosclaw_darwin.tdl.schema import Task


class EvalJobBuilder:
    """Convert TDL Task to Arena eval job dict."""

    @staticmethod
    def build(task: Task, policy_config: dict[str, Any]) -> dict[str, Any]:
        job: dict[str, Any] = {
            "task_id": task.id,
            "policy_type": policy_config.get("type", "zero"),
            "num_episodes": task.eval.max_episodes or 20,
            "num_steps": task.eval.max_steps or 1000,
            "headless": True,
        }

        # Native pass-through: use provenance.native_config
        if task.provenance and task.provenance.native_config:
            job.update(task.provenance.native_config)

        if policy_config.get("num_envs"):
            job["num_envs"] = policy_config["num_envs"]
        if policy_config.get("distributed"):
            job["distributed"] = True
        if policy_config.get("enable_cameras"):
            job["enable_cameras"] = True
        if policy_config.get("external_environment_class_path"):
            job["external_environment_class_path"] = policy_config["external_environment_class_path"]

        return job
