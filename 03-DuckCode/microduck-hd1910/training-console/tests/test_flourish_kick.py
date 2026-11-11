"""浪子踢球：随机起步，先快后抬再快前踢。"""
import math
import unittest

import torch

from training.official_adapter import (
    _kick_angular_rate, configure_flourish_warm_start, flourish_forward_score,
    flourish_head_score, flourish_raise_score, flourish_rooster_score)
from training.official_spec import CATALOG, FLOURISH_KICK_END_S, FLOURISH_PRELUDE_S, FLOURISH_SKILL_S, TASKS


def parts(angle, episode_s, upright=1.0, angular_speed=0.0, foot_z=0.05, length=0.10):
    ahead = torch.tensor([length * math.sin(angle)], dtype=torch.float64)
    vertical = torch.tensor([-length * math.cos(angle)], dtype=torch.float64)
    return (ahead, vertical, torch.tensor([episode_s], dtype=torch.float64),
            torch.tensor([upright], dtype=torch.float64),
            torch.tensor([angular_speed], dtype=torch.float64),
            torch.tensor([foot_z], dtype=torch.float64))


class FlourishScoreTests(unittest.TestCase):
    def test_fast_back_raise_beats_a_slow_or_forward_leg(self):
        fast = flourish_raise_score(*parts(0.0, 0.25, angular_speed=-16.0))
        slow = flourish_raise_score(*parts(0.0, 0.25, angular_speed=-4.0))
        kicking = flourish_raise_score(*parts(math.pi / 4, 0.25, angular_speed=16.0))
        grounded = flourish_raise_score(*parts(0.0, 0.25, angular_speed=-16.0, foot_z=0.0))
        self.assertGreater(float(fast), float(slow))
        self.assertGreater(float(slow), 0.0)
        self.assertLess(float(kicking), 0.0)
        self.assertEqual(float(grounded), 0.0)
        self.assertEqual(float(flourish_raise_score(*parts(-math.pi / 4, 0.6, angular_speed=-16.0))), 0.0)

    def test_rooster_holds_still_and_rejects_a_kick(self):
        held = flourish_rooster_score(*parts(-math.pi / 4, 1.0))
        swinging = flourish_rooster_score(*parts(-math.pi / 4, 1.0, angular_speed=-16.0))
        forward = flourish_rooster_score(*parts(math.pi / 4, 1.0))
        fallen = flourish_rooster_score(*parts(-math.pi / 4, 1.0, upright=0.0))
        grounded = flourish_rooster_score(*parts(-math.pi / 4, 1.0, foot_z=0.0))
        self.assertGreater(float(held), 0.8)
        self.assertGreater(float(held), float(swinging))
        self.assertLess(float(forward), 0.0)
        self.assertEqual(float(fallen), 0.0)
        self.assertLess(float(grounded), 0.05)
        self.assertEqual(float(flourish_rooster_score(*parts(-math.pi / 4, 0.2))), 0.0)
        self.assertEqual(float(flourish_rooster_score(*parts(-math.pi / 4, FLOURISH_PRELUDE_S))), 0.0)

    def test_kick_pays_more_for_a_faster_forward_swing(self):
        fast = flourish_forward_score(*parts(0.0, 1.75, angular_speed=16.0))
        slow = flourish_forward_score(*parts(0.0, 1.75, angular_speed=4.0))
        rewind = flourish_forward_score(*parts(0.0, 1.75, angular_speed=-16.0))
        already_there = flourish_forward_score(*parts(math.pi / 4, 1.75, angular_speed=16.0))
        grounded = flourish_forward_score(*parts(0.0, 1.75, angular_speed=16.0, foot_z=0.0))
        self.assertGreater(float(fast), float(slow))
        self.assertGreater(float(slow), 0.0)
        self.assertLess(float(rewind), 0.0)
        self.assertEqual(float(already_there), 0.0)
        self.assertEqual(float(grounded), 0.0)
        self.assertEqual(float(flourish_forward_score(*parts(0.0, 1.0, angular_speed=16.0))), 0.0)

    def test_forward_hold_keeps_the_leg_still_and_off_the_ground(self):
        held = flourish_forward_score(*parts(math.pi / 4, 2.5))
        swinging = flourish_forward_score(*parts(math.pi / 4, 2.5, angular_speed=16.0))
        grounded = flourish_forward_score(*parts(math.pi / 4, 2.5, foot_z=0.0))
        back_during_hold = flourish_forward_score(*parts(-math.pi / 4, 2.5, angular_speed=16.0))
        self.assertGreater(float(held), 0.8)
        self.assertGreater(float(held), float(swinging))
        self.assertLess(float(grounded), 0.05)
        self.assertLess(float(back_during_hold), 0.05)
        self.assertEqual(float(flourish_forward_score(*parts(math.pi / 4, FLOURISH_KICK_END_S))), 0.0)

    def test_kick_rate_uses_the_previous_control_step(self):
        class Env:
            step_dt = 0.02
            episode_length_buf = torch.tensor([0])
        env = Env()
        first = _kick_angular_rate(env, torch.tensor([0.0]))
        env.episode_length_buf = torch.tensor([1])
        second = _kick_angular_rate(env, torch.tensor([0.2]))
        again = _kick_angular_rate(env, torch.tensor([0.2]))
        self.assertEqual(float(first), 0.0)
        self.assertAlmostEqual(float(second), 10.0)
        self.assertAlmostEqual(float(again), 10.0)

    def test_head_turns_right_from_the_back_lift(self):
        kick = torch.tensor([2.5])
        right = flourish_head_score(torch.tensor([-0.8]), torch.tensor([-0.08]), kick)
        center = flourish_head_score(torch.tensor([0.0]), torch.tensor([-0.08]), kick)
        left = flourish_head_score(torch.tensor([0.8]), torch.tensor([-0.08]), kick)
        during_raise = flourish_head_score(torch.tensor([-0.8]), torch.tensor([-0.08]), torch.tensor([0.4]))
        self.assertGreater(float(right), 0.8)
        self.assertGreater(float(right), float(center))
        self.assertGreater(float(center), float(left))
        self.assertGreater(float(during_raise), 0.8)
        self.assertEqual(float(flourish_head_score(torch.tensor([-0.8]), torch.tensor([0.08]), torch.tensor([FLOURISH_KICK_END_S]))), 0.0)

    def test_new_run_does_not_load_a_teacher(self):
        class Agent:
            resume = True
            load_run = 'teacher'
            load_checkpoint = 'model.pt'
        class Cfg:
            agent = Agent()
        receipt = configure_flourish_warm_start(Cfg(), {'flourish': {}})
        self.assertEqual(receipt['mode'], 'scratch')
        self.assertFalse(Cfg.agent.resume)
        self.assertEqual(Cfg.agent.load_run, '')
        self.assertEqual(Cfg.agent.load_checkpoint, '')
        Cfg.agent.resume = True
        continued = configure_flourish_warm_start(Cfg(), {'checkpoint': 'model_1000.pt', 'flourish': {'mode': 'resume'}})
        self.assertEqual(continued['mode'], 'resume')
        self.assertTrue(Cfg.agent.resume)

    def test_catalog_lists_flourish_after_the_right_kick(self):
        roles = [p['role'] for p in CATALOG['profiles']]
        self.assertLess(roles.index('kick_right'), roles.index('kick_flourish'))
        self.assertEqual(CATALOG['profiles'][roles.index('kick_flourish')]['name'], '浪子踢球 / Flourish kick')
        task = 'Mjlab-BallKickFlourish-Flat-MicroDuck'
        self.assertEqual(TASKS[task]['upstream_task'], 'Mjlab-BallKick-Flat-MicroDuck')
        self.assertEqual(TASKS[task]['iterations'], 10000)
        self.assertIn('随机起步', TASKS[task]['description'])
        self.assertEqual(FLOURISH_PRELUDE_S, 1.5)
        self.assertEqual(FLOURISH_SKILL_S, 4.0)


if __name__ == '__main__':
    unittest.main()
