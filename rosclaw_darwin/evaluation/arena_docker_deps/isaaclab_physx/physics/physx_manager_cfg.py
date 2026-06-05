from dataclasses import dataclass

@dataclass
class PhysxCfg:
    gpu_max_rigid_patch_count: int = 5 * 2**15
    gpu_found_lost_pairs_capacity: int = 2**23
    gpu_found_lost_aggregate_pairs_capacity: int = 2**25
    gpu_total_aggregate_pairs_capacity: int = 2**23
    gpu_max_soft_body_contacts: int = 2**21
    gpu_max_particle_contacts: int = 2**21
    gpu_heap_capacity: int = 2**25
    gpu_temp_buffer_capacity: int = 2**24
    gpu_max_num_partitions: int = 8
    gpu_collision_stack_size: int = 2**26
