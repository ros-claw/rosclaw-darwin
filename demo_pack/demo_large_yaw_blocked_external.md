# Demo: Large-yaw torsional slip blocked external

**Evidence card:** `large_yaw_torsional_slip_blocked_external`

**What it shows:**
- Large positive-yaw targets trigger torsional slip during lift.
- The failure mechanism is outside current sensor/control capabilities.
- Darwin blocks false recovery promotion and routes it externally.

**Run:**
```bash
darwin diagnose \
  --run demo_outputs/runs_large_yaw --out demo_outputs/diagnosis_large_yaw --mock

darwin card \
  --candidate large_yaw_torsional_slip_blocked_external \
  --out demo_outputs/cards --mock
```

**Allowed claims:**
- Darwin can block false recovery promotion and route externally blocked failures.

**Blocked claims:**
- Large-yaw is not solved.
- Slip recovery is not validated.
