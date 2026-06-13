# Action Response Calibration Report

- Task: ``darwin_mvp_03_lift_object``
- Action mode: ``relative_pose_dik``
- Calibration steps per axis: 50
- Recommended gain multiplier: 0.44

## Axis Responses

| action | world delta (m) | response norm (m) | per-unit delta |
|---|---|---|---|
| action_x_pos | [0.03335772082209587, 0.006764054298400879, 8.428096771240234e-05] | 0.034036701841954696 | [0.06671544164419174, 0.013528108596801758, 0.0001685619354248047] |
| action_x_neg | [-0.012881699949502945, -0.0014581307768821716, -0.013796985149383545] | 0.018932013579221446 | [-0.02576339989900589, -0.0029162615537643433, -0.02759397029876709] |
| action_y_pos | [0.016261916607618332, 0.013671506196260452, 0.0037636756896972656] | 0.02157603457831719 | [0.032523833215236664, 0.027343012392520905, 0.007527351379394531] |
| action_y_neg | [-0.012481823563575745, -0.010174382477998734, 0.008715271949768066] | 0.018310378025569445 | [-0.02496364712715149, -0.020348764955997467, 0.017430543899536133] |
| action_z_pos | [-0.013131007552146912, 0.002832990139722824, -0.024898827075958252] | 0.02829135525606325 | [-0.026262015104293823, 0.005665980279445648, -0.049797654151916504] |
| action_z_neg | [-0.010856986045837402, 0.008754029870033264, -0.006659567356109619] | 0.015454999913798237 | [-0.021713972091674805, 0.01750805974006653, -0.013319134712219238] |

## Estimated Mapping

```json
{
  "world_x_to_action_axis": "positive_x",
  "world_y_to_action_axis": "positive_y",
  "world_z_to_action_axis": "negative_z"
}
```

## Interpretation

- A positive action on axis X producing a negative world X displacement
  indicates a body-frame sign flip.
- Small response norms confirm the DifferentialIK controller is heavily
  damped; increasing the commanded magnitude or using joint-space control
  may be necessary.

