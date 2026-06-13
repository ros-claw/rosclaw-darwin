# ROSClaw-Darwin Result Semantics

This document defines how different evaluation results must be interpreted.
It is enforced by ``EvaluationResult`` metadata, ``PolicyMetadata``, and the
reporting pipeline.

## Result scopes

| Scope | Meaning | Can claim capability? | Can claim evolution? |
|---|---|---|---|
| ``mock_ci`` | Unit/integration test or mock adapter | No | No |
| ``pipeline_sanity`` | Oracle/cheat/replay used only to verify the eval pipeline | No | No |
| ``arena_real`` | Real policy running in IsaacLab-Arena Docker | Yes | No |
| ``robotwin_replay`` | Trajectory replay in RoboTwin | Yes* | No |
| ``semantic_only`` | Task imported but not executable | No | No |

\* Real robot replay can claim capability only when the replay is shown to
generalise, not when it is a single teleoperated trajectory.

## Cheat / oracle policies are excluded from everything except sanity

A policy is a cheat/oracle when it directly manipulates simulation state
(e.g. teleporting the object) or uses privileged information that a real
robot policy could not access.

For such policies:

- ``success_rate`` may be recorded as a pipeline sanity check.
- ``skill_discovery_rate`` and ``evolution_score`` must be ``null``/``0``.
- ``leaderboard_excluded`` must be ``true``.
- ``can_claim_capability`` must be ``false``.
- Reports must state: **This result is a pipeline sanity check only.**

## Why mock metrics cannot claim real capability

Mock adapters use simplified physics or scripted success signals. They are
essential for CI and fast iteration, but they do not prove that a policy works
on a real embodied task. Therefore mock results are tagged with
``claim_level = infrastructure``.

## Why semantic-only tasks cannot enter real success_rate

A task that is imported but has no executable environment cannot produce a real
rollout. Its metrics, if any, belong to ``semantic_only`` scope and cannot be
used for capability claims.

## Why skill hint consumption is not skill transfer

Logging ``[HEURISTIC_SKILL_HINTS] consumed: ...`` only proves the policy
configuration received the hint. It does **not** prove the hint improved
performance. Transfer must be measured by comparing metrics with and without
the hint (ablation).

## What qualifies as evolution evidence

Evolution evidence requires a closed loop:

1. Loop 1: real policy fails with a diagnosed failure type.
2. A skill hint is generated from that failure.
3. Loop 2: the same policy consumes the hint and reruns.
4. A metric improves (success rate, progress, distance, height, or failure
type advances to a later stage).

Only then can ``claim_level = evolution`` and ``can_claim_evolution = true``.
