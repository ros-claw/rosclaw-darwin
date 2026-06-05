"""Darwin Full Evolutionary Evaluation with heuristic policy."""
import sys
sys.path.insert(0, '/workspace/rosclaw-darwin')
sys.path.insert(0, '/workspace/rosclaw-darwin/stubs')
sys.path.insert(0, '/workspace/rosclaw-memory/src')

import os
os.environ['ROSCLAW_ARENA_MODE'] = 'docker'

import json
import time
import torch
import numpy as np

from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.environment.arena_adapter import ArenaAdapter
from rosclaw_darwin.evaluation.metrics import compute_metrics

print("=" * 70)
print("ROSClaw-Darwin: Full Evolutionary Evaluation")
print("=" * 70)

# ---- Initialize SeekDB ----
print("\n[0] Initializing SeekDB...")
memory = None
seekdb_ok = False
try:
    from powermem import create_memory
    memory = create_memory()
    seekdb_ok = True
    print("    SeekDB: READY")
except Exception as e:
    print(f"    SeekDB: UNAVAILABLE ({e})")
    print("    Using file-based fallback")

# ---- Load task ----
print("\n[1] Loading task...")
loader = TaskLoader()
task = loader.load('/workspace/rosclaw-darwin/configs/tasks/pick_place_milk.yaml')
print(f"    Task: {task.name}")
print(f"    Primitives: {[p.name for p in task.primitives]}")

# ---- Build adapter ----
print("\n[2] Building Arena adapter...")
adapter = ArenaAdapter(task, headless=True)
adapter.build()
print("    Build: SUCCESS")

env = adapter._env
device = getattr(env, 'device', None) or getattr(env.unwrapped, 'device', torch.device('cuda:0'))
print(f"    Device: {device}")

# ---- Get initial observation to understand the setup ----
obs = adapter.reset()
print(f"    Initial obs keys: {list(obs.keys()) if isinstance(obs, dict) else 'not dict'}")

# Extract initial eef_pos and quat
INIT_QUAT = None
if isinstance(obs, dict) and 'policy' in obs:
    p = obs['policy']
    if isinstance(p, dict):
        if 'eef_pos' in p:
            init_eef = p['eef_pos'][0] if p['eef_pos'].dim() > 1 else p['eef_pos']
            print(f"    Initial eef_pos: {init_eef}")
        if 'eef_quat' in p:
            INIT_QUAT = p['eef_quat'][0].clone() if p['eef_quat'].dim() > 1 else p['eef_quat'].clone()
            print(f"    Initial eef_quat: {INIT_QUAT}")
        if 'gripper_pos' in p:
            init_grip = p['gripper_pos'][0] if p['gripper_pos'].dim() > 1 else p['gripper_pos']
            print(f"    Initial gripper_pos: {init_grip}")

# ---- Policies ----

def policy_zero(obs, step_num=0):
    """No-op baseline."""
    return torch.zeros(env.action_space.shape, device=device)

def _get_eef_pos(obs):
    """Extract end-effector position from observation."""
    if isinstance(obs, dict) and 'policy' in obs:
        p = obs['policy']
        if isinstance(p, dict) and 'eef_pos' in p:
            return p['eef_pos'][0] if p['eef_pos'].dim() > 1 else p['eef_pos']
    return None

def _get_gripper_pos(obs):
    """Extract gripper position from observation."""
    if isinstance(obs, dict) and 'policy' in obs:
        p = obs['policy']
        if isinstance(p, dict) and 'gripper_pos' in p:
            return p['gripper_pos'][0] if p['gripper_pos'].dim() > 1 else p['gripper_pos']
    return None

def _get_eef_quat(obs):
    """Extract end-effector orientation from observation."""
    if isinstance(obs, dict) and 'policy' in obs:
        p = obs['policy']
        if isinstance(p, dict) and 'eef_quat' in p:
            return p['eef_quat'][0] if p['eef_quat'].dim() > 1 else p['eef_quat']
    return None

def policy_heuristic(obs, step_num):
    """Heuristic: move towards object, let z descend naturally, grip.

    Key findings:
    - z action is unstable in this arm config (can cause z to rise)
    - Pure x/y movement causes natural z changes due to arm kinematics
    - Goal: quickly move xy to target, close gripper when close
    """
    action = torch.zeros(env.action_space.shape, device=device)
    eef_pos = _get_eef_pos(obs)

    # Object at (0.1, 0.0, 0.05)
    target = torch.tensor([0.10, 0.00], device=device)

    if eef_pos is not None:
        dx = target[0] - eef_pos[0]
        dy = target[1] - eef_pos[1]
        dist_xy = torch.sqrt(dx**2 + dy**2)

        # Phase 1: Fast horizontal approach (steps 0-15)
        if step_num < 15:
            action[0, 0] = torch.clamp(dx * 12.0, -2.0, 2.0)
            action[0, 1] = torch.clamp(dy * 12.0, -2.0, 2.0)
            # NO z action - let arm kinematics handle it
            action[0, 6] = 0.0  # open

        # Phase 2: Fine-tune xy, prepare to grip (steps 15-25)
        elif step_num < 25:
            action[0, 0] = torch.clamp(dx * 8.0, -1.5, 1.5)
            action[0, 1] = torch.clamp(dy * 8.0, -1.5, 1.5)
            action[0, 6] = 0.0  # open

        # Phase 3: Close gripper (steps 25+)
        else:
            action[0, 0] = torch.clamp(dx * 5.0, -1.0, 1.0)
            action[0, 1] = torch.clamp(dy * 5.0, -1.0, 1.0)
            # Close gripper when reasonably aligned
            if dist_xy < 0.08:
                action[0, 6] = 1.0  # close
            else:
                action[0, 6] = 0.0
    else:
        action[0, 0] = 0.3
        action[0, 1] = 0.1
        action[0, 6] = 0.0

    return action

def policy_heuristic_v2(obs, step_num):
    """Improved heuristic: pure xy pursuit, grip when close.

    No z action - relies on arm kinematics and natural motion.
    """
    action = torch.zeros(env.action_space.shape, device=device)
    eef_pos = _get_eef_pos(obs)

    target = torch.tensor([0.10, 0.00], device=device)

    if eef_pos is not None:
        dx = target[0] - eef_pos[0]
        dy = target[1] - eef_pos[1]
        dist_xy = torch.sqrt(dx**2 + dy**2)

        # Proportional control with saturation
        action[0, 0] = torch.clamp(dx * 15.0, -2.5, 2.5)
        action[0, 1] = torch.clamp(dy * 15.0, -2.5, 2.5)

        # Gripper: close when aligned, always after step 20
        if dist_xy < 0.06 or step_num > 20:
            action[0, 6] = 1.0
        else:
            action[0, 6] = 0.0
    else:
        action[0, 0] = 0.3
        action[0, 1] = 0.1
        action[0, 6] = 0.0

    return action


def _get_object_pos(obj_name='milk_carton'):
    """Get object position from scene."""
    try:
        uw = env.unwrapped if hasattr(env, 'unwrapped') else env
        obj = uw.scene[obj_name]
        return obj.data.root_pos_w[0].clone()
    except Exception:
        return None


def _get_finger_poses():
    """Get finger tip positions from frame transformer."""
    try:
        uw = env.unwrapped if hasattr(env, 'unwrapped') else env
        ft = uw.scene.sensors['ee_frame']
        right = ft.data.target_pos_source[0, 1].clone()
        left = ft.data.target_pos_source[0, 2].clone()
        return right, left
    except Exception:
        return None, None


def policy_heuristic_v3(obs, step_num):
    """3D pick-and-place using ABSOLUTE pose commands.

    Arena adapter configures DifferentialIK with use_relative_mode=False and
    scale=1.0. Action space is (1, 8):
      action[0:3] = absolute target position (x,y,z)
      action[3:7] = target orientation quaternion (w,x,y,z)
      action[7]   = gripper (<0=close, >=0=open)
    DifferentialIK converges gradually toward the commanded pose.
    """
    action = torch.zeros(env.action_space.shape, device=device)
    eef_pos = _get_eef_pos(obs)

    # Use fixed initial quaternion for stable convergence
    if INIT_QUAT is not None and INIT_QUAT.numel() >= 4:
        action[0, 3] = INIT_QUAT[0]  # qw
        action[0, 4] = INIT_QUAT[1]  # qx
        action[0, 5] = INIT_QUAT[2]  # qy
        action[0, 6] = INIT_QUAT[3]  # qz

    if eef_pos is None:
        action[0, 0] = 0.35
        action[0, 2] = 0.25
        action[0, 7] = 1.0  # open (positive=open)
        return action

    # Phase 1: Stay high while launched object settles (steps 0-25)
    # Object spawns inside table and launches; wait for it to fall back.
    if step_num < 25:
        action[0, 0] = 0.35
        action[0, 1] = 0.0
        action[0, 2] = 0.25
        action[0, 7] = 1.0  # open
        return action

    # Phase 2: Descend to grasp (steps 25-60)
    if step_num < 60:
        action[0, 0] = 0.35
        action[0, 1] = 0.0
        action[0, 2] = 0.10
        action[0, 7] = 1.0  # open
        return action

    # Phase 3: Grasp (steps 60-90)
    if step_num < 90:
        action[0, 0] = 0.35
        action[0, 1] = 0.0
        action[0, 2] = 0.10
        action[0, 7] = -1.0  # close (negative=close)
        return action

    # Phase 4: Lift to z=0.30 (steps 90-130)
    if step_num < 130:
        action[0, 0] = 0.35
        action[0, 1] = 0.0
        action[0, 2] = 0.30
        action[0, 7] = -1.0  # keep closed
        return action

    # Phase 5: Move to fridge (steps 130-160)
    if step_num < 160:
        action[0, 0] = 0.40
        action[0, 1] = 0.0
        action[0, 2] = 0.30
        action[0, 7] = -1.0
        return action

    # Phase 6: Lower to z=0.10 for release (steps 160-210)
    if step_num < 210:
        action[0, 0] = 0.40
        action[0, 1] = 0.0
        action[0, 2] = 0.10
        action[0, 7] = -1.0
        return action

    # Phase 7: Release (steps 210+)
    action[0, 0] = 0.40
    action[0, 1] = 0.0
    action[0, 2] = 0.10
    action[0, 7] = 1.0  # open
    return action


POLICIES = [
    ("Loop1: Heuristic v3 (3D pick-place)", policy_heuristic_v3),
]

# Quick test policy to verify z direction
def policy_test_z_descent(obs, step_num):
    """Test: pure z- action to see if z decreases."""
    action = torch.zeros(env.action_space.shape, device=device)
    eef_pos = _get_eef_pos(obs)
    if eef_pos is not None and step_num < 100:
        action[0, 2] = -5.0  # z- (try descent)
        print(f"      [TestZ] step={step_num} eef_z={eef_pos[2]:.4f} action_z=-5.0")
    return action

def policy_test_z_ascent(obs, step_num):
    """Test: pure z+ action to see if z increases."""
    action = torch.zeros(env.action_space.shape, device=device)
    eef_pos = _get_eef_pos(obs)
    if eef_pos is not None and step_num < 100:
        action[0, 2] = 5.0  # z+ (try ascent)
        print(f"      [TestZ] step={step_num} eef_z={eef_pos[2]:.4f} action_z=+5.0")
    return action

# Uncomment to run quick z-direction tests:
# POLICIES = [
#     ("Test: z- descent", policy_test_z_descent),
#     ("Test: z+ ascent", policy_test_z_ascent),
# ]

# ---- Practice hook ----
def practice_hook(session_id, task_id, metrics_dict):
    event = {
        "session_id": session_id,
        "task_id": task_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "strategy": metrics_dict.get("strategy", "unknown"),
        "success": metrics_dict.get("success", False),
        "steps": metrics_dict.get("step_count", 0),
        "reward": metrics_dict.get("total_reward", 0.0),
        "time": metrics_dict.get("completion_time", 0.0),
    }
    content = json.dumps(event)

    if seekdb_ok and memory is not None:
        try:
            memory.add(
                content=content,
                user_id=session_id,
                metadata={"task_id": task_id, "type": "darwin_eval"},
            )
            print(f"      [Practice] Saved to SeekDB")
            return
        except Exception as e:
            print(f"      [Practice] SeekDB failed: {e}")

    fallback_path = "/data/rosclaw/fallback"
    os.makedirs(fallback_path, exist_ok=True)
    fname = f"{fallback_path}/darwin_{session_id}_{int(time.time())}.json"
    with open(fname, "w") as f:
        json.dump(event, f, indent=2)
    print(f"      [Practice] Saved fallback: {fname}")

# ---- Memory hook ----
def memory_hook(query_text, session_id):
    if seekdb_ok and memory is not None:
        try:
            results = memory.search(query_text, user_id=session_id, top_k=5)
            items = results.get("results", [])
            print(f"      [Memory] Found {len(items)} memories")
            for item in items[:2]:
                mem = item.get("memory", "")
                print(f"        - {mem[:100]}...")
            return items
        except Exception as e:
            print(f"      [Memory] Query failed: {e}")
    else:
        print(f"      [Memory] SeekDB not available")
    return []

# ---- Evaluate ----
def evaluate_episode(policy_fn, max_steps=300, strategy_name=""):
    limit = max_steps or task.eval_config.max_steps
    obs = adapter.reset()
    trajectory = []
    success = False
    t0 = time.perf_counter()

    for step in range(limit):
        action = policy_fn(obs, step)
        result = adapter._env.step(action)
        # Unpack: (obs, reward, terminated, truncated, info) for 5-tuple
        if len(result) == 5:
            obs, reward, terminated, truncated, info = result
        else:
            obs, reward, terminated, info = result
            truncated = False
        done = terminated or truncated
        trajectory.append({"step": step, "reward": reward, "info": info})

        # Log eef_pos and object pos every 5 steps for debugging
        env_unwrapped = adapter._env.unwrapped if hasattr(adapter._env, 'unwrapped') else adapter._env
        ep_len_buf = getattr(env_unwrapped, 'episode_length_buf', None)
        # Check termination terms
        try:
            tm = env_unwrapped.termination_manager
            success_val = tm.get_term("success")
            dropped_val = tm.get_term("object_dropped")
            timeout_val = tm.get_term("time_out")
        except Exception:
            success_val = dropped_val = timeout_val = None
        if step % 5 == 0:
            eef = _get_eef_pos(obs)
            obj = _get_object_pos()
            grip = _get_gripper_pos(obs)
            rf, lf = _get_finger_poses()
            reward_val = _scalar(reward)
            if eef is not None:
                obj_str = f"obj=({obj[0]:.3f},{obj[1]:.3f},{obj[2]:.3f})" if obj is not None else "obj=N/A"
                grip_str = f"grip={grip[0]:.4f}" if grip is not None else "grip=N/A"
                finger_str = ""
                if rf is not None and lf is not None:
                    finger_str = f"  R=({rf[0]:.3f},{rf[1]:.3f},{rf[2]:.3f}) L=({lf[0]:.3f},{lf[1]:.3f},{lf[2]:.3f})"
                print(f"      [Step {step:3d}] eef=({eef[0]:.3f},{eef[1]:.3f},{eef[2]:.3f})  {obj_str}  {grip_str}{finger_str}")

        if done:
            # Correct success detection: check termination manager's success term
            # (info dict may not contain "success" key in IsaacLab)
            env_unwrapped = adapter._env.unwrapped if hasattr(adapter._env, 'unwrapped') else adapter._env
            try:
                tm = env_unwrapped.termination_manager
                success_term = tm.get_term("success")
                success = bool(success_term.item()) if success_term is not None else False
            except Exception:
                success = info.get("success", reward > 0.9)
                if isinstance(success, torch.Tensor):
                    success = bool(success.item())
            ep_len_buf = getattr(env_unwrapped, 'episode_length_buf', None)
            max_ep_len = getattr(env_unwrapped, 'max_episode_length', None)
            print(f"      [DONE at step {step}] term={terminated}  trunc={truncated}  success={success}")
            print(f"        episode_length_buf={ep_len_buf}, max_episode_length={max_ep_len}")
            print(f"        info keys: {list(info.keys())}")
            for k, v in info.items():
                v_str = str(v)
                if len(v_str) > 120:
                    v_str = v_str[:120] + "..."
                print(f"        {k}: {v_str}")
            break

    elapsed = time.perf_counter() - t0
    metrics = compute_metrics(trajectory, success=success)
    metrics.completion_time = elapsed
    metrics.info["strategy"] = strategy_name
    return metrics

def _scalar(v):
    if isinstance(v, torch.Tensor):
        return v.item() if v.numel() == 1 else v.tolist()
    return v

# ---- Main loop ----
all_sessions = []

try:
    for loop_idx, (policy_name, policy_fn) in enumerate(POLICIES):
        print(f"\n{'='*70}")
        print(f"EVOLUTION LOOP {loop_idx + 1}: {policy_name}")
        print(f"{'='*70}")

        session_id = f"darwin_loop{loop_idx+1}"

        if loop_idx > 0:
            print(f"\n  [Memory Query] Loading past experiences...")
            memories = memory_hook(task.id, session_id="darwin_eval")
            if memories:
                print(f"  → Using {len(memories)} memories")
            else:
                print(f"  → No prior memories")

        print(f"\n  [Evaluation] Running {policy_name}...")
        metrics = evaluate_episode(policy_fn, max_steps=300, strategy_name=policy_name)

        success_val = _scalar(metrics.success)
        reward_val = _scalar(metrics.info.get('total_reward', 0.0))

        print(f"  Results:")
        print(f"    Success:      {success_val}")
        print(f"    Steps:        {metrics.step_count}")
        print(f"    Total reward: {reward_val:.6f}")
        print(f"    Time:         {metrics.completion_time:.3f}s")

        print(f"\n  [Practice Capture] Saving experience...")
        metrics_dict = {
            "success": success_val,
            "step_count": metrics.step_count,
            "total_reward": reward_val,
            "completion_time": metrics.completion_time,
            "strategy": policy_name,
        }
        practice_hook(session_id, task.id, metrics_dict)

        all_sessions.append({
            "loop": loop_idx + 1,
            "policy": policy_name,
            "metrics": metrics_dict,
        })

    # ---- Analysis ----
    print(f"\n{'='*70}")
    print("[3] Evolution Analysis")
    print(f"{'='*70}")

    for s in all_sessions:
        m = s["metrics"]
        print(f"\n  Loop {s['loop']} ({m['strategy']}):")
        print(f"    Reward: {m['total_reward']:.6f} | Steps: {m['step_count']} | Success: {m['success']}")

    if len(all_sessions) >= 2:
        best = max(all_sessions, key=lambda s: s["metrics"]["total_reward"])
        worst = min(all_sessions, key=lambda s: s["metrics"]["total_reward"])
        delta_reward = best["metrics"]["total_reward"] - worst["metrics"]["total_reward"]
        print(f"\n  Evolution Delta:")
        print(f"    Best:  {best['metrics']['strategy']} (reward={best['metrics']['total_reward']:.6f})")
        print(f"    Worst: {worst['metrics']['strategy']} (reward={worst['metrics']['total_reward']:.6f})")
        print(f"    Delta: {delta_reward:+.6f}")

        sdr = 1 if abs(delta_reward) > 1e-6 else 0
        print(f"\n  Darwin Metrics:")
        print(f"    SDR: {sdr} | MIE: 1 | SSI: N/A")

    print(f"\n{'='*70}")
    print("DARWIN EVOLUTION COMPLETE!")
    print(f"{'='*70}")

except Exception as e:
    print(f"\nERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
finally:
    print("\n[4] Closing adapter...")
    adapter.close()
    print("    Closed.")
