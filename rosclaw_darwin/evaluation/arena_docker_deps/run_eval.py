import sys
# Inject --headless before AppLauncher initializes so it picks headless kit
if "--headless" not in sys.argv:
    sys.argv.insert(1, "--headless")

sys.path.insert(0, "/workspace/data")
import lightwheel_patch

# Monkey-patch wp.to_torch for OmniWarp 1.12.0 + PyTorch 2.7 compatibility.
# Arena's observation code calls wp.to_torch() on torch.Tensor inputs; older
# OmniWarp assumes torch.device has .is_cpu which was removed in PyTorch 2.7.
try:
    import warp as wp
    import torch

    _orig_to_torch = wp.to_torch

    def _compat_to_torch(a, requires_grad=None):
        if isinstance(a, torch.Tensor):
            return a
        return _orig_to_torch(a, requires_grad)

    wp.to_torch = _compat_to_torch
except Exception:
    pass

from isaaclab_arena.evaluation.eval_runner import main

if __name__ == "__main__":
    main()
