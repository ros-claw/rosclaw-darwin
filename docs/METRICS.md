# Metrics

## Basic Metrics

| Metric | Description |
|--------|-------------|
| success_rate | Fraction of successful episodes |
| completion_time_mean | Mean time to completion |
| completion_time_std | Std dev of completion time |
| collision_count_mean | Mean collisions per episode |
| progress_mean | Mean progress (proxy for success_rate) |
| num_episodes | Total episodes evaluated |
| num_success | Total successful episodes |

## Evolution Metrics

| Metric | Description |
|--------|-------------|
| delta_success_rate | loop2.success_rate - loop1.success_rate |
| memory_integration_efficiency | 1 - same_failures_loop2 / max(1, same_failures_loop1) |
| skill_discovery_rate | num_validated_new_skills / num_episodes |
| robustness_gain | robustness_loop2 - robustness_loop1 |
| completion_time_improvement | Relative time reduction |
| evolution_score | Weighted composite (see README) |
