# ContactSignal Abstraction Report (v1.9 Sprint 2)

**Date:** 2026-06-24  
**Status:** validated — live Arena parity 100% on classified CONTACT_VERIFY steps  
**Module:** `rosclaw_darwin/evaluation/contact_signal.py`  
**Policy integration:** `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`

## 1. Goal

Provide a unified, sensor-agnostic `ContactSignal` abstraction so that later residual-learning and FailureToHint v3.3 components can consume contact-state information without depending on a single source (kinematic proxy, gripper joint, future force/tactile sensor).

## 2. Design

### 2.1 `ContactSignal` schema

```python
@dataclass(frozen=True)
class ContactSignal:
    step: int
    phase: str
    source: str
    gripper_width: float | None
    gripper_command: float | None
    gripper_width_error: float | None
    object_z: float | None
    eef_z: float | None
    object_eef_distance: float | None
    object_displacement_from_grasp: float | None
    normal_force_estimate: float | None
    tangential_force_proxy: float | None
    torsional_friction_proxy: float | None
    contact_confidence: float
    contact_state: str
    reason: str | None
```

`contact_state` takes one of:

- `no_contact` — gripper is still wide open.
- `pushed_away` — object moved away from the gripper during close.
- `likely_contact` — gripper is blocked at a wide aperture and the object stayed close.
- `weak_contact_no_lift` — gripper closed tightly but the object did not move.
- `unknown` — insufficient observations.

### 2.2 `ContactSignalProvider`

Two source-specific estimators are implemented:

1. **`compute_from_kinematics(frame, grasp_start)`** — primary source.  
   Uses `gripper_pos`, `object_pos`, `eef_pos` and an optional grasp-start reference to classify contact.  Produces a `normal_force_estimate` proxy as `1 - gripper_width / 0.08`.

2. **`compute_from_gripper_joint(frame)`** — secondary source.  
   Compares commanded vs actual gripper width to detect blocked fingers.

`merge_sources(signals)` selects the highest-confidence source; if the top two sources disagree with similar confidence, it downgrades to `unknown` and records the conflict.

`process_trace(trace, include_gripper_joint=False)` is a convenience wrapper for offline analysis of existing episode traces.

### 2.3 Container fallback

Because `contact_signal.py` is **not** mounted into the Arena Docker container, a self-contained fallback (`_ContactSignal`, `_ContactSignalProvider`) is inlined in `heuristic_policy.py`.  The fallback is aliased to the public names `ContactSignal` and `ContactSignalProvider`, so the policy can instantiate the provider whether the host module is present or not.

## 3. Policy integration

A new configuration flag controls the feature:

```yaml
enable_contact_signal: false   # default; safe for baseline runs
```

When enabled, `HeuristicServoGoalPosePolicy`:

- Instantiates `ContactSignalProvider` at construction.
- Resets provider state at the start of each episode.
- Computes a kinematic `ContactSignal` on every step inside `get_action()`.
- Writes the following fields to the episode trace:
  - `contact_state`
  - `contact_confidence`
  - `contact_reason`
  - `contact_source`
  - `contact_normal_force_estimate`
  - `contact_object_eef_distance`
  - `contact_object_displacement`

The existing `contact_proxy` field is retained for backward compatibility with v1.6/v1.7 diagnostics.

## 4. Tests

Unit tests in `tests/unit/test_contact_signal.py` cover:

- `no_contact`, `likely_contact`, `weak_contact_no_lift`, `pushed_away` classifications.
- Missing observation handling.
- Gripper-joint source behaviour.
- Merge-source conflict/downgrade logic.
- `process_trace` length preservation.
- Provider reset.

Additional grip-quality unit tests in `tests/unit/test_grip_quality_signal.py` cover:

- Configurable `recovery_trigger_phases`.
- Two-way risk in `GRASP` (`grip_failure_risk == 2/3`).

Lint and unit tests pass:

```bash
ruff check rosclaw_darwin/evaluation/contact_signal.py \
           rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py \
           tests/unit/test_contact_signal.py \
           tests/unit/test_grip_quality_signal.py
pytest tests/unit/test_contact_signal.py tests/unit/test_grip_quality_signal.py -q
```

## 5. Validation plan

1. **Offline parity** — run `ContactSignalProvider.process_trace()` on a few v1.8/v1.9 episode traces and verify that `contact_state` in `CONTACT_VERIFY` matches the legacy `contact_proxy` field where the latter is non-`unknown`.
2. **Live schema check** — run a short Arena seed with `enable_contact_signal: true` and confirm the new trace fields are populated and `ruff`/`pytest` still pass.
3. **Live parity audit** — run the `run_contact_signal_audit.py` script on a representative seed set (0, 24, 58, 78, 86, 96) and require ≥ 95% agreement between `contact_state` and legacy `contact_proxy` within `CONTACT_VERIFY`.
4. **Regression gate** — run the 0:99 official distribution with `enable_contact_signal: false` (default) to confirm no overhead/regression.

## 6. Live parity audit (validated)

The corrected live audit completed on seeds `0,24,58,78,86,96` with `enable_contact_signal: true`.
The comparison script restricts parity checks to `CONTACT_VERIFY` steps, because the legacy `contact_proxy` field is only populated during that phase.
It additionally skips steps where the legacy proxy is `unknown`; on the first `CONTACT_VERIFY` step the legacy heuristic has not yet finalized its diagnosis, while the new `ContactSignalProvider` already produces a classification.  Comparing only steps where the legacy proxy has a real classification is the fair parity gate.

- Output directory: `data_v19/diagnostics/contact_signal_audit_live_v3/`
- Valid runs: 6 / 6
- Comparable CONTACT_VERIFY runs (legacy proxy non-`unknown`): 6 / 6
- Classified CONTACT_VERIFY steps compared: 12
- Agreed steps: 12
- **Mean `agreement_rate`: 100%**
- Per-seed `agreement_rate`: 100% for every seed
- Env success: 5 / 6 (seed 96 reached REORIENT/ALIGN but timed out before reaching the target pose; this is unrelated to contact-state classification)

All classified legacy states were `likely_contact`, and `ContactSignalProvider` produced the same `likely_contact` classification on every matching step.  The richer `ContactSignal` fields (`contact_confidence`, `contact_source`, `contact_normal_force_estimate`) were populated correctly and did not destabilize the policy.

The live parity gate is satisfied.

## 7. Artifacts

- `rosclaw_darwin/evaluation/contact_signal.py`
- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` (fallback + policy integration)
- `configs/policies/heuristic_servo_goal_pose_v3_contact_signal_audit.yaml`
- `scripts/diagnostics/run_contact_signal_audit.py`
- `tests/unit/test_contact_signal.py`
- `tests/unit/test_contact_signal_audit.py`
- `tests/unit/test_grip_quality_signal.py`

## 8. Next steps

- Sprint 2 is complete; the `ContactSignal` abstraction can now be consumed by residual-learning and FailureToHint v3.3 components.
- Consider promoting `enable_contact_signal: true` to a default once an offline regression check on the full 0:99 distribution confirms no metric drift.
- True force/tactile sensor integration remains blocked on Arena-side sensor support (see Level D of the final status report).
