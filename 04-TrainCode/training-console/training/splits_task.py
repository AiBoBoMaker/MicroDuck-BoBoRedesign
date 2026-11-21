"""Console-local front-back splits task (大劈叉), registered onto the frozen engine.

Training Studio ships this module and registers Mjlab-Splits-*-MicroDuck at
worker/setup time. Domain randomization and the 61-D observation contract come
from the official ground_pick factory; pose rewards and depth/period curricula
live here so the pinned official_0151 tree stays untouched.

Hardware constraint (do not ignore):
  hip_pitch soft limit ≈ ±1.41 rad (soft_joint_pos_limit_factor 0.9 × π/2).
  From stand (~±0.46), the left leg can open only ~55° more forward. A
  "90° snap" target of -2.0 is *illegal* — the servo saturates on the stop
  and the planted feet produce a tip-over torque. That is why a policy can
  train 10k+ steps and still fall on the first frame of the skill.

Feasible curriculum:
  1) OPEN — hips, knees, and ankles deepen *together* (no ankle-only PREP
     while both soles are still planted at stand).
  2) HOLD — sit in the deepest *legal* split.
  3) RISE — return to stand.

Rewards also credit sagittal foot separation so the policy may slide rather
than only chase joint angles that fight friction.
"""
ENABLE_SYMMETRY = False

# Slow open on an 8 s clock early; curriculum shortens later.
SPLITS_PERIOD = 8.0
# Brief settle near stand, then a long open (sliding needs time), hold, rise.
PREP_END = 0.12
DROP_END = 0.48
HOLD_END = 0.72
RISE_END = 0.90

# Soft-limit budget with margin: stay inside ±1.35 (hard ±π/2, soft ±1.41).
_SOFT_HIP = 1.35

STAND_POSE = {
    'left_hip_yaw': 0.0, 'left_hip_roll': -0.0873, 'left_hip_pitch': -0.4579,
    'left_knee': -0.0049, 'left_ankle': 0.4530,
    'neck_pitch': 0.3491, 'head_pitch': 0.3491, 'head_yaw': 0.0, 'head_roll': 0.0,
    'right_hip_yaw': 0.0, 'right_hip_roll': 0.0873, 'right_hip_pitch': 0.4579,
    'right_knee': 0.0049, 'right_ankle': -0.4530,
}
# Mild mid-open only — ankles move *with* hips, never alone at full stand.
PREP_SPLITS_POSE = {
    'left_hip_yaw': 0.0, 'left_hip_roll': -0.06, 'left_hip_pitch': -0.75,
    'left_knee': -0.05, 'left_ankle': 0.70,
    'neck_pitch': 0.32, 'head_pitch': 0.32, 'head_yaw': 0.0, 'head_roll': 0.0,
    'right_hip_yaw': 0.0, 'right_hip_roll': 0.06, 'right_hip_pitch': 0.15,
    'right_knee': 0.10, 'right_ankle': -0.65,
}
# Deepest legal floor split. Left hip at soft-limit margin; right hip back;
# slight knee bend so the pelvis can drop and the feet can slide.
FLOOR_SPLITS_POSE = {
    'left_hip_yaw': 0.02, 'left_hip_roll': -0.04, 'left_hip_pitch': -_SOFT_HIP,
    'left_knee': -0.12, 'left_ankle': 1.05,
    'neck_pitch': 0.28, 'head_pitch': 0.26, 'head_yaw': 0.0, 'head_roll': 0.05,
    'right_hip_yaw': -0.02, 'right_hip_roll': 0.04, 'right_hip_pitch': -0.70,
    'right_knee': 0.22, 'right_ankle': -0.95,
}
# Back-compat aliases for anything still referencing the old names.
OPEN_SPLITS_POSE = PREP_SPLITS_POSE

_LEG_JOINTS = [
    'left_hip_yaw', 'left_hip_roll', 'left_hip_pitch', 'left_knee', 'left_ankle',
    'right_hip_yaw', 'right_hip_roll', 'right_hip_pitch', 'right_knee', 'right_ankle',
]
_HIP_PITCH_JOINTS = ['left_hip_pitch', 'right_hip_pitch']
_ANKLE_JOINTS = ['left_ankle', 'right_ankle']
_KNEE_JOINTS = ['left_knee', 'right_knee']
_NECK_JOINTS = ['neck_pitch', 'head_pitch', 'head_yaw', 'head_roll']

_GROUND_PICK_REWARDS = (
    'mouth_ground_proximity', 'mouth_perpendicular_to_ground',
    'ground_pick_return_pose_legs', 'ground_pick_return_pose_neck',
    'return_upright', 'neck_vel_descent', 'mouth_payload_force', 'head_impact_penalty',
)


def _lerp_named_pose(stand, target, scale):
    s = float(max(0.0, min(1.0, scale)))
    return {name: stand[name] + s * (target[name] - stand[name]) for name in stand}


def _blend_named_pose(a, b, t):
    s = float(max(0.0, min(1.0, t)))
    return {name: a[name] + s * (b[name] - a[name]) for name in a}


def _scale_from_stand(stand, target, scale):
    """Curriculum deepens the *whole* pose — hips, knees, and ankles together."""
    return _lerp_named_pose(stand, target, scale)


def splits_phase_pose(phase, stand, prep, floor, prep_end=PREP_END, drop_end=DROP_END,
                      hold_end=HOLD_END, rise_end=RISE_END):
    """Return the named-pose target for one phase in [0, 1)."""
    p = float(phase) % 1.0
    if p < prep_end:
        return _blend_named_pose(stand, prep, p / max(prep_end, 1e-6))
    if p < drop_end:
        return _blend_named_pose(prep, floor, (p - prep_end) / max(drop_end - prep_end, 1e-6))
    if p < hold_end:
        return dict(floor)
    if p < rise_end:
        return _blend_named_pose(floor, stand, (p - hold_end) / max(rise_end - hold_end, 1e-6))
    return dict(stand)


def _phase_from_command(env, command_name):
    import torch
    cmd = env.command_manager.get_command(command_name)
    return (torch.atan2(cmd[:, 1], cmd[:, 0]) / (2 * torch.pi)) % 1.0


def _resolve_timeline(prep_end, drop_end, hold_end, rise_end, open_end, sit_end):
    """Map legacy open_end/sit_end onto the PREP→DROP→HOLD→RISE clock."""
    if open_end is not None and sit_end is not None:
        # Old 3-phase: stand→open→sit→rise. Treat open as drop end, sit as hold.
        return float(open_end) * 0.4, float(open_end), float(sit_end), float(rise_end)
    return prep_end, drop_end, hold_end, rise_end


def _pose_error(env, command_name, stand, prep, floor, joint_names,
                prep_end, drop_end, hold_end, rise_end, asset_cfg=None):
    import torch
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    cfg = asset_cfg or SceneEntityCfg('robot')
    asset = env.scene[cfg.name]
    names = list(joint_names)
    ids = [int(asset.find_joints([n])[0][0]) for n in names]
    phase = _phase_from_command(env, command_name)
    stand_v = torch.tensor([stand[n] for n in names], device=env.device, dtype=asset.data.joint_pos.dtype)
    prep_v = torch.tensor([prep[n] for n in names], device=env.device, dtype=asset.data.joint_pos.dtype)
    floor_v = torch.tensor([floor[n] for n in names], device=env.device, dtype=asset.data.joint_pos.dtype)
    p = phase.unsqueeze(-1)
    s1 = (p / max(prep_end, 1e-6)).clamp(0.0, 1.0)
    s2 = ((p - prep_end) / max(drop_end - prep_end, 1e-6)).clamp(0.0, 1.0)
    s3 = ((p - hold_end) / max(rise_end - hold_end, 1e-6)).clamp(0.0, 1.0)
    seg1 = stand_v + s1 * (prep_v - stand_v)
    seg2 = prep_v + s2 * (floor_v - prep_v)
    seg3 = floor_v + s3 * (stand_v - floor_v)
    target = seg1
    target = torch.where(p >= prep_end, seg2, target)
    target = torch.where(p >= drop_end, floor_v.expand_as(target), target)
    target = torch.where(p >= hold_end, seg3, target)
    target = torch.where(p >= rise_end, stand_v.expand_as(target), target)
    cur = asset.data.joint_pos[:, ids]
    return cur, target, phase


def _scaled_poses(stand, prep, floor, scale):
    """Both waypoints deepen with curriculum — never full ankles at scale≪1."""
    return _scale_from_stand(stand, prep, scale), _scale_from_stand(stand, floor, scale)


def splits_pose_track(env, command_name='twist', stand_pose=None, prep_pose=None, floor_pose=None,
                      open_pose=None, std=0.35, prep_end=PREP_END, drop_end=DROP_END,
                      hold_end=HOLD_END, rise_end=RISE_END, open_end=None, sit_end=None,
                      asset_cfg=None, joint_names=None, scale_attr='split_scale'):
    """Gaussian tracking of the PREP→DROP→HOLD→RISE pose schedule."""
    import torch
    stand = stand_pose or STAND_POSE
    prep = prep_pose or open_pose or PREP_SPLITS_POSE
    scale = float(getattr(env, scale_attr, 0.30))
    prep_end, drop_end, hold_end, rise_end = _resolve_timeline(
        prep_end, drop_end, hold_end, rise_end, open_end, sit_end,
    )
    prep_s, floor_s = _scaled_poses(stand, prep, floor_pose or FLOOR_SPLITS_POSE, scale)
    cur, target, _ = _pose_error(
        env, command_name, stand, prep_s, floor_s, joint_names or _LEG_JOINTS,
        prep_end, drop_end, hold_end, rise_end, asset_cfg,
    )
    return torch.exp(-((cur - target) / std) ** 2).mean(dim=-1)


def splits_pose_track_l1(env, command_name='twist', stand_pose=None, prep_pose=None, floor_pose=None,
                         open_pose=None, prep_end=PREP_END, drop_end=DROP_END,
                         hold_end=HOLD_END, rise_end=RISE_END, open_end=None, sit_end=None,
                         asset_cfg=None, joint_names=None, scale_attr='split_scale'):
    import torch
    stand = stand_pose or STAND_POSE
    prep = prep_pose or open_pose or PREP_SPLITS_POSE
    scale = float(getattr(env, scale_attr, 0.30))
    prep_end, drop_end, hold_end, rise_end = _resolve_timeline(
        prep_end, drop_end, hold_end, rise_end, open_end, sit_end,
    )
    prep_s, floor_s = _scaled_poses(stand, prep, floor_pose or FLOOR_SPLITS_POSE, scale)
    cur, target, _ = _pose_error(
        env, command_name, stand, prep_s, floor_s, joint_names or _LEG_JOINTS,
        prep_end, drop_end, hold_end, rise_end, asset_cfg,
    )
    return -(cur - target).abs().mean(dim=-1)


def splits_hip_open_bonus(env, command_name='twist', prep_end=PREP_END, drop_end=DROP_END,
                          hold_end=HOLD_END, asset_cfg=None, scale_attr='split_scale'):
    """Extra credit while the hips are near the open split during/after the open."""
    import torch
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    cfg = asset_cfg or SceneEntityCfg('robot')
    asset = env.scene[cfg.name]
    scale = float(getattr(env, scale_attr, 0.30))
    _prep, floor = _scaled_poses(STAND_POSE, PREP_SPLITS_POSE, FLOOR_SPLITS_POSE, scale)
    del _prep
    ids = [int(asset.find_joints([n])[0][0]) for n in _HIP_PITCH_JOINTS]
    target = torch.tensor(
        [floor[n] for n in _HIP_PITCH_JOINTS],
        device=env.device, dtype=asset.data.joint_pos.dtype,
    )
    cur = asset.data.joint_pos[:, ids]
    match = torch.exp(-((cur - target) / 0.30) ** 2).mean(dim=-1)
    phase = _phase_from_command(env, command_name)
    window = (phase >= prep_end) & (phase < hold_end)
    return match * window.to(dtype=match.dtype)


# Keep old name so any stale JSON reward entry still resolves.
splits_hip_snap_bonus = splits_hip_open_bonus


def splits_feet_separation(env, command_name='twist', target_dist=0.14, std=0.06,
                           prep_end=PREP_END, hold_end=HOLD_END, scale_attr='split_scale',
                           asset_cfg=None):
    """Reward sagittal/horizontal foot-site distance during the open+hold window.

    Joint tracking alone fights planted friction; this gives a direct signal to
    slide the feet apart as the hips open. ``target_dist`` scales with curriculum
    so early stages only ask for a few centimetres.
    """
    import torch
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    cfg = asset_cfg or SceneEntityCfg('robot', site_names=('left_foot', 'right_foot'))
    asset = env.scene[cfg.name]
    foot_xy = asset.data.site_pos_w[:, cfg.site_ids, :2]
    dist = torch.norm(foot_xy[:, 0] - foot_xy[:, 1], dim=-1)
    scale = float(getattr(env, scale_attr, 0.30))
    want = float(target_dist) * max(0.35, scale)
    match = torch.exp(-((dist - want) / std) ** 2)
    phase = _phase_from_command(env, command_name)
    window = (phase >= prep_end) & (phase < hold_end)
    return match * window.to(dtype=match.dtype)


def splits_base_drop(env, command_name='twist', target_z=0.075, std=0.03,
                     drop_end=DROP_END, hold_end=HOLD_END, scale_attr='split_scale',
                     asset_cfg=None):
    """Reward a lower pelvis during hold — a real split sits, it does not tip."""
    import torch
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    cfg = asset_cfg or SceneEntityCfg('robot')
    asset = env.scene[cfg.name]
    z = asset.data.root_link_pos_w[:, 2] - env.scene.terrain.env_origins[:, 2]
    scale = float(getattr(env, scale_attr, 0.30))
    # Stand ~0.115 m; ask for a partial drop early, deeper later.
    stand_z = 0.115
    want = stand_z + max(0.25, scale) * (float(target_z) - stand_z)
    match = torch.exp(-((z - want) / std) ** 2)
    phase = _phase_from_command(env, command_name)
    window = (phase >= drop_end) & (phase < hold_end)
    return match * window.to(dtype=match.dtype)


def split_scale_curriculum(env, env_ids, scale_stages, attr_name='split_scale'):
    import torch
    del env_ids
    scale = float(scale_stages[0]['scale'])
    for stage in scale_stages:
        if env.common_step_counter > stage['step']:
            scale = float(stage['scale'])
    setattr(env, attr_name, scale)
    return torch.tensor([scale])


def phase_period_curriculum(env, env_ids, command_name, period_stages):
    import torch
    del env_ids
    period = float(period_stages[0]['period'])
    for stage in period_stages:
        if env.common_step_counter > stage['step']:
            period = float(stage['period'])
    env.command_manager.get_term(command_name)._period = period
    return torch.tensor([period])


def make_microduck_splits_env_cfg(play=False, rough=False):
    """Reuse official ground_pick DR/obs/action contract; swap in splits phase rewards."""
    from mjlab.managers import CurriculumTermCfg, RewardTermCfg
    from mjlab_microduck.tasks import mdp as microduck_mdp
    from mjlab_microduck.tasks.microduck_ground_pick_env_cfg import make_microduck_ground_pick_env_cfg

    cfg = make_microduck_ground_pick_env_cfg(play=play, rough=rough)
    for name in _GROUND_PICK_REWARDS:
        cfg.rewards.pop(name, None)

    pose_params = {
        'command_name': 'twist', 'stand_pose': STAND_POSE, 'prep_pose': PREP_SPLITS_POSE,
        'floor_pose': FLOOR_SPLITS_POSE, 'prep_end': PREP_END, 'drop_end': DROP_END,
        'hold_end': HOLD_END, 'rise_end': RISE_END,
    }
    cfg.rewards['splits_pose'] = RewardTermCfg(
        func=splits_pose_track, weight=5.0,
        params={**pose_params, 'std': 0.40, 'joint_names': _LEG_JOINTS},
    )
    cfg.rewards['splits_pose_l1'] = RewardTermCfg(
        func=splits_pose_track_l1, weight=1.2,
        params={**pose_params, 'joint_names': _LEG_JOINTS},
    )
    cfg.rewards['splits_hips'] = RewardTermCfg(
        func=splits_pose_track, weight=4.5,
        params={**pose_params, 'std': 0.28, 'joint_names': _HIP_PITCH_JOINTS},
    )
    cfg.rewards['splits_hip_open'] = RewardTermCfg(
        func=splits_hip_open_bonus, weight=2.5,
        params={
            'command_name': 'twist', 'prep_end': PREP_END, 'drop_end': DROP_END,
            'hold_end': HOLD_END,
        },
    )
    # Ankles follow the scaled schedule — never a full-strength planted hook.
    cfg.rewards['splits_toes'] = RewardTermCfg(
        func=splits_pose_track, weight=2.0,
        params={**pose_params, 'std': 0.25, 'joint_names': _ANKLE_JOINTS},
    )
    cfg.rewards['splits_knees'] = RewardTermCfg(
        func=splits_pose_track, weight=2.0,
        params={**pose_params, 'std': 0.22, 'joint_names': _KNEE_JOINTS},
    )
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    _feet_sites = SceneEntityCfg('robot', site_names=('left_foot', 'right_foot'))
    cfg.rewards['splits_feet_sep'] = RewardTermCfg(
        func=splits_feet_separation, weight=3.0,
        params={
            'command_name': 'twist', 'target_dist': 0.14, 'std': 0.06,
            'prep_end': PREP_END, 'hold_end': HOLD_END, 'asset_cfg': _feet_sites,
        },
    )
    cfg.rewards['splits_base_drop'] = RewardTermCfg(
        func=splits_base_drop, weight=2.0,
        params={
            'command_name': 'twist', 'target_z': 0.075, 'std': 0.03,
            'drop_end': DROP_END, 'hold_end': HOLD_END,
        },
    )
    cfg.rewards['splits_neck'] = RewardTermCfg(
        func=splits_pose_track, weight=1.0,
        params={**pose_params, 'std': 0.30, 'joint_names': _NECK_JOINTS},
    )
    # Trunk may pitch as the pelvis drops; do not force a rigid stand.
    cfg.rewards['upright'].weight = 0.5
    if 'feet_grounded' in cfg.rewards:
        # Keep some contact bias, but allow a foot to unweight while sliding.
        cfg.rewards['feet_grounded'].weight = 0.3
    if 'feet_flat' in cfg.rewards:
        # Heel/toe contact is expected in a split; stop rewarding flat soles.
        cfg.rewards['feet_flat'].weight = -0.3

    twist = cfg.commands['twist']
    twist.period = SPLITS_PERIOD
    twist.randomize_phase = False
    cfg.episode_length_s = 16.0

    # Shallow first: learn balance + a few cm of foot slide, then deepen.
    cfg.curriculum['split_scale'] = CurriculumTermCfg(
        func=split_scale_curriculum,
        params={'scale_stages': [
            {'step': 0, 'scale': 0.25},
            {'step': 1000 * 24, 'scale': 0.40},
            {'step': 2500 * 24, 'scale': 0.55},
            {'step': 5000 * 24, 'scale': 0.75},
            {'step': 8000 * 24, 'scale': 0.90},
            {'step': 12000 * 24, 'scale': 1.00},
        ]},
    )
    cfg.curriculum['splits_period'] = CurriculumTermCfg(
        func=phase_period_curriculum,
        params={'command_name': 'twist', 'period_stages': [
            {'step': 0, 'period': 8.0},
            {'step': 4000 * 24, 'period': 7.0},
            {'step': 8000 * 24, 'period': 6.0},
        ]},
    )
    # Smooth open, not a jerk — keep action_rate meaningful early.
    cfg.curriculum['action_rate_weight'] = CurriculumTermCfg(
        func=microduck_mdp.reward_weight,
        params={'reward_name': 'action_rate_l2', 'weight_stages': [
            {'step': 0, 'weight': -0.4},
            {'step': 2000 * 24, 'weight': -0.7},
            {'step': 6000 * 24, 'weight': -1.0},
        ]},
    )
    return cfg


def build_rl_cfg():
    from mjlab.rl import RslRlOnPolicyRunnerCfg, RslRlModelCfg
    from mjlab_microduck.tasks.symmetry import PpoWithSymmetryCfg, SYMMETRY_CFG
    return RslRlOnPolicyRunnerCfg(
        actor=RslRlModelCfg(
            hidden_dims=(512, 256, 128), activation='elu', obs_normalization=True,
            distribution_cfg={'class_name': 'GaussianDistribution', 'init_std': 1.0, 'std_type': 'scalar'},
        ),
        critic=RslRlModelCfg(hidden_dims=(512, 256, 128), activation='elu', obs_normalization=True),
        algorithm=PpoWithSymmetryCfg(
            value_loss_coef=1.0, use_clipped_value_loss=True, clip_param=0.2, entropy_coef=0.01,
            num_learning_epochs=5, num_mini_batches=4, learning_rate=1.0e-3, schedule='adaptive',
            gamma=0.99, lam=0.95, desired_kl=0.01, max_grad_norm=1.0,
            symmetry_cfg=SYMMETRY_CFG if ENABLE_SYMMETRY else None,
        ),
        experiment_name='splits', run_name='splits', save_interval=250,
        num_steps_per_env=24, max_iterations=20_000,
    )


# Lazily constructed so importing this module without the engine still works for catalog tools.
MicroduckSplitsRlCfg = None


def get_rl_cfg():
    global MicroduckSplitsRlCfg
    if MicroduckSplitsRlCfg is None:
        MicroduckSplitsRlCfg = build_rl_cfg()
    return MicroduckSplitsRlCfg
