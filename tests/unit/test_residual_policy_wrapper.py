"""Unit tests for ResidualPolicy wrapper and baseline policies."""

from __future__ import annotations

from rosclaw_darwin.learning.residual_policy import (
    DEFAULT_RESIDUAL_LIMITS,
    ResidualAction,
    ResidualNonePolicy,
    ResidualPolicyWrapper,
    ResidualSeed24GuardPolicy,
    ResidualSlipGuardPolicy,
)


def test_zero_residual_leaves_action_unchanged():
    """ResidualNonePolicy should produce final action identical to heuristic."""
    heuristic = [0.1, 0.2, 0.3, 0.01, 0.02, 0.03, 0.5]
    policy = ResidualNonePolicy()
    wrapper = ResidualPolicyWrapper(residual_policy=policy)
    final = wrapper.compute_final_action(heuristic, {}, phase="APPROACH")
    assert final == heuristic


def test_clipping_at_limits():
    """Residual values exceeding limits should be clipped."""
    class LargeResidualPolicy(ResidualNonePolicy):
        def predict(self, observation, contact_signal, slip_signal, grip_quality_signal, phase):
            return ResidualAction(
                delta_pos=[0.1, 0.1, 0.1],
                delta_rot=[0.1, 0.1, 0.1],
                delta_gripper=0.2,
                active_axes=[True] * 7,
                confidence=1.0,
            )

    heuristic = [0.0] * 7
    policy = LargeResidualPolicy()
    wrapper = ResidualPolicyWrapper(residual_policy=policy)
    final = wrapper.compute_final_action(heuristic, {}, phase="APPROACH")

    assert abs(final[0] - DEFAULT_RESIDUAL_LIMITS["positional"]) < 1e-9
    assert abs(final[1] - DEFAULT_RESIDUAL_LIMITS["positional"]) < 1e-9
    assert abs(final[2] - DEFAULT_RESIDUAL_LIMITS["positional"]) < 1e-9
    assert abs(final[3] - DEFAULT_RESIDUAL_LIMITS["rotational"]) < 1e-9
    assert abs(final[4] - DEFAULT_RESIDUAL_LIMITS["rotational"]) < 1e-9
    assert abs(final[5] - DEFAULT_RESIDUAL_LIMITS["rotational"]) < 1e-9
    assert abs(final[6] - DEFAULT_RESIDUAL_LIMITS["gripper"]) < 1e-9


def test_seed24_guard_activates_on_signature():
    """Seed24 guard should trigger only when low_object_z and gripper_too_open are True."""
    policy = ResidualSeed24GuardPolicy()
    obs = {}

    # Matching signature in GRASP phase.
    gq = {"low_object_z": True, "gripper_too_open": True}
    action = policy.predict(obs, None, None, gq, "GRASP")
    assert action.active_axes[2] is True
    assert action.active_axes[6] is True
    assert action.delta_pos[2] == -0.003
    assert action.delta_gripper == -0.03
    assert action.confidence == 0.7

    # Missing gripper_too_open.
    gq_partial = {"low_object_z": True, "gripper_too_open": False}
    action2 = policy.predict(obs, None, None, gq_partial, "GRASP")
    assert all(a is False for a in action2.active_axes)
    assert action2.confidence == 0.0

    # Wrong phase.
    action3 = policy.predict(obs, None, None, gq, "LIFT")
    assert all(a is False for a in action3.active_axes)

    # No signal.
    action4 = policy.predict(obs, None, None, None, "GRASP")
    assert all(a is False for a in action4.active_axes)


def test_seed24_guard_stays_zero_otherwise():
    """When signature does not match, seed24 guard should return zero residual."""
    policy = ResidualSeed24GuardPolicy()
    gq = {"low_object_z": False, "gripper_too_open": False}
    action = policy.predict({}, None, None, gq, "GRASP")
    assert all(a is False for a in action.active_axes)
    assert action.delta_pos == [0.0, 0.0, 0.0]
    assert action.delta_gripper == 0.0


def test_slip_guard_activates_on_high_slip_signal():
    """Slip guard should trigger on slip_risk='high' or slip_score > 2.0."""
    policy = ResidualSlipGuardPolicy()

    slip_high = {"slip_risk": "high", "slip_score": 1.0}
    action = policy.predict({}, None, slip_high, None, "LIFT")
    assert action.active_axes[3] is True
    assert action.active_axes[4] is True
    assert action.active_axes[5] is True
    assert action.active_axes[6] is True
    assert action.delta_rot == [-0.02, 0.0, -0.02]
    assert action.delta_gripper == 0.02
    assert action.confidence == 0.6

    slip_numeric = {"slip_risk": "low", "slip_score": 3.5}
    action2 = policy.predict({}, None, slip_numeric, None, "LIFT")
    assert any(action2.active_axes)

    slip_low = {"slip_risk": "low", "slip_score": 1.0}
    action3 = policy.predict({}, None, slip_low, None, "LIFT")
    assert all(a is False for a in action3.active_axes)

    # No signal.
    action4 = policy.predict({}, None, None, None, "LIFT")
    assert all(a is False for a in action4.active_axes)


def test_active_axes_length_matches_action_length():
    """When active_axes is shorter than 7, wrapper should pad with False."""
    class ShortAxesPolicy(ResidualNonePolicy):
        def predict(self, observation, contact_signal, slip_signal, grip_quality_signal, phase):
            return ResidualAction(
                delta_pos=[0.003],
                delta_rot=[],
                delta_gripper=0.0,
                active_axes=[True],
                confidence=1.0,
            )

    heuristic = [0.0] * 7
    policy = ShortAxesPolicy()
    wrapper = ResidualPolicyWrapper(residual_policy=policy)
    final = wrapper.compute_final_action(heuristic, {}, phase="APPROACH")
    # Only first axis should be modified (within positional limit).
    assert final[0] == 0.003
    assert final[1:] == [0.0] * 6


def test_residual_action_norm():
    """Norm of a zero residual should be 0.0."""
    policy = ResidualNonePolicy()
    wrapper = ResidualPolicyWrapper(residual_policy=policy)
    action = policy.predict({}, None, None, None, "APPROACH")
    assert wrapper.residual_action_norm(action) == 0.0

    # Non-zero norm.
    action2 = ResidualAction(
        delta_pos=[0.003, 0.004, 0.0],
        delta_rot=[0.0, 0.0, 0.0],
        delta_gripper=0.0,
        active_axes=[True, True, False, False, False, False, False],
        confidence=1.0,
    )
    expected = (0.003 ** 2 + 0.004 ** 2) ** 0.5
    assert abs(wrapper.residual_action_norm(action2) - expected) < 1e-9
