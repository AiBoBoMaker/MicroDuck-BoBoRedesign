"""Mass selection, persistence and actual MuJoCo inertial compilation."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import training_console as tc
from studio import fresh_recipe, recipe_digest
from training.recipe import SERVO_MASS_PROFILE, MASS_CLOSURE_PROFILE, MASS_CLOSURE_PROFILES, apply_robot, com_with_rear_mass, migrate_battery_mass, validate_servo_mass

try:
    import mujoco
    import numpy as np
except ImportError:
    mujoco = None

ROOT = Path(__file__).resolve().parents[1]
MODEL = json.loads((ROOT/'data/baseline_official0151.json').read_text())['model']


class ServoMassRecipeTests(unittest.TestCase):
    def test_default_is_official_skeleton_hd1910_battery150(self):
        recipe = fresh_recipe()
        self.assertEqual(recipe['baseline'], 'official_0151')
        self.assertEqual(recipe['robot']['servo_mass_model'], 'hd1910_battery150_v1')
        self.assertEqual(MASS_CLOSURE_PROFILE['battery_g'], 150.0)
        self.assertEqual(MASS_CLOSURE_PROFILE['target_g'], 884.0)
        self.assertEqual(len(recipe['calibration']['data']['joints']), 15)
        saved = {'robot': {'servo_mass_model': 'hd1910_820g_v1'}}
        self.assertTrue(migrate_battery_mass(saved))
        self.assertEqual(saved['robot']['servo_mass_model'], 'hd1910_battery150_v1')
        manual = {'robot': {'servo_mass_model': 'hd1910_820g_v1', 'bodies': {'trunk_base': {'mass': .25}}}}
        self.assertFalse(migrate_battery_mass(manual))

    def test_saved_selection_survives_restart_and_changes_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = tc.TrainingManager(Path(folder))
            recipe = fresh_recipe(); recipe['baseline'] = 'official_0151'
            previous = recipe_digest(recipe)
            recipe['robot'] = {'servo_mass_model': 'hd1910_23g'}
            manager.save_recipe({'recipe': recipe}); manager.close()
            restored = tc.TrainingManager(Path(folder))
            self.assertEqual(restored.recipe['robot']['servo_mass_model'], 'hd1910_23g')
            self.assertNotEqual(recipe_digest(restored.recipe), previous)
            request = {'op': 'preview'}; restored.decorate_request(request, {})
            self.assertEqual(request['studio_recipe']['robot'], recipe['robot'])
            restored.close()

    def test_rejects_luwu_custom_and_unknown_weight_options(self):
        for baseline, robot in [('luwu', {'servo_mass_model':'hd1910_23g'}),
                                ('official_0151', {'servo_mass_model':'hd1910_23g','mjcf_path':'model.xml'}),
                                ('official_0151', {'servo_mass_model':'anything'})]:
            with self.assertRaises(ValueError): validate_servo_mass(robot, baseline)
        self.assertFalse(validate_servo_mass({}, 'luwu'))
        self.assertEqual(sum(SERVO_MASS_PROFILE['body_counts'].values()), 15)


@unittest.skipUnless(mujoco, 'MuJoCo required for real inertial compilation')
class ServoMassPhysicsTests(unittest.TestCase):
    def test_820g_closure_and_old_recipe_replay_are_distinct(self):
        cfg = self.config()
        apply_robot(cfg, {'servo_mass_model':'hd1910_820g_v1'}, 'official_0151')
        for _ in range(3):
            m = cfg.scene.entities['robot'].spec_fn().compile()
            self.assertAlmostEqual(sum(m.body_mass), .820, places=12)
            for name, expected in [('jaw_soft',.201766),('trunk_base',.21398082)]:
                bid = mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,name)
                self.assertAlmostEqual(m.body_mass[bid],expected,places=12)
                original = next(b for b in MODEL['bodies'] if b['name']==name)
                for old, new in zip(original['inertia'],m.body_inertia[bid]):
                    self.assertAlmostEqual(new,old*expected/original['mass_kg'],places=12)
        old = self.config()
        apply_robot(old, {'servo_mass_model':'hd1910_23g'}, 'official_0151')
        self.assertAlmostEqual(sum(old.scene.entities['robot'].spec_fn().compile().body_mass),.81224318,places=12)
        battery = self.config()
        apply_robot(battery, {'servo_mass_model':'hd1910_battery150_v1'}, 'official_0151')
        compiled = battery.scene.entities['robot'].spec_fn().compile()
        self.assertAlmostEqual(sum(compiled.body_mass), .884, places=12)
        for name, expected in [('jaw_soft', .201766), ('trunk_base', .27798082)]:
            bid = mujoco.mj_name2id(compiled, mujoco.mjtObj.mjOBJ_BODY, name)
            self.assertAlmostEqual(compiled.body_mass[bid], expected, places=12)
            original = next(b for b in MODEL['bodies'] if b['name']==name)
            for old_i, new_i in zip(original['inertia'], compiled.body_inertia[bid]):
                self.assertAlmostEqual(new_i, old_i*expected/original['mass_kg'], places=12)
        trunk = next(b for b in MODEL['bodies'] if b['name']=='trunk_base')
        bid = mujoco.mj_name2id(compiled, mujoco.mjtObj.mjOBJ_BODY, 'trunk_base')
        profile = MASS_CLOSURE_PROFILES['hd1910_battery150_v1']
        expected_ipos = com_with_rear_mass(trunk['ipos'], .27798082, profile['rear_mass_g']/1000, profile['rear_mass_point_m'])
        for old, new, exp in zip(trunk['ipos'], compiled.body_ipos[bid], expected_ipos):
            self.assertAlmostEqual(new, exp, places=9)
        self.assertLess(compiled.body_ipos[bid][0], trunk['ipos'][0])
        eight = self.config()
        apply_robot(eight, {'servo_mass_model':'hd1910_820g_v1'}, 'official_0151')
        eight_model = eight.scene.entities['robot'].spec_fn().compile()
        eight_trunk = mujoco.mj_name2id(eight_model, mujoco.mjtObj.mjOBJ_BODY, 'trunk_base')
        for old, new in zip(trunk['ipos'], eight_model.body_ipos[eight_trunk]):
            self.assertAlmostEqual(old, new, places=9)
        self.assertEqual(MASS_CLOSURE_PROFILES['hd1910_820g_v1']['target_g'], 820.0)

    def test_manual_trunk_ipos_survives_battery_shift(self):
        cfg = self.config()
        ipos = [-0.04, 0.0, 0.001]
        apply_robot(cfg, {'servo_mass_model':'hd1910_battery150_v1', 'bodies':{'trunk_base':{'ipos':ipos}}}, 'official_0151')
        model = cfg.scene.entities['robot'].spec_fn().compile()
        bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, 'trunk_base')
        self.assertAlmostEqual(model.body_mass[bid], .27798082, places=8)
        for old, new in zip(ipos, model.body_ipos[bid]):
            self.assertAlmostEqual(old, new, places=9)

    def test_closure_respects_manual_mass_and_inertia(self):
        cfg = self.config()
        apply_robot(cfg, {'servo_mass_model':'hd1910_820g_v1', 'bodies':{
            'trunk_base':{'mass':.25}, 'jaw_soft':{'inertia':[1e-4,1e-4,1e-4]}}}, 'official_0151')
        m = cfg.scene.entities['robot'].spec_fn().compile()
        bid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,'trunk_base')
        self.assertAlmostEqual(m.body_mass[bid],.25)
        self.assertAlmostEqual(sum(m.body_mass),.820-.21398082+.25,places=12)
        bid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_BODY,'jaw_soft')
        for v in m.body_inertia[bid]:self.assertAlmostEqual(v,1e-4,places=12)

    def config(self):
        # Original frozen body inertials, without visual meshes or GPU training.
        root = ET.Element('mujoco'); world = ET.SubElement(root, 'worldbody')
        for b in MODEL['bodies']:
            body = ET.SubElement(world, 'body', name=b['name'])
            attrs = {'mass':str(b['mass_kg']), 'pos':' '.join(map(str,b['ipos'])),
                     'quat':' '.join(map(str,b['iquat'])),
                     'diaginertia':' '.join(map(str,b['inertia']))}
            if b['name'] == 'trunk_base':
                rotation = np.empty(9); mujoco.mju_quat2Mat(rotation,np.array(b['iquat']))
                rotation = rotation.reshape(3,3)
                tensor = rotation @ np.diag(b['inertia']) @ rotation.T
                attrs.pop('quat'); attrs.pop('diaginertia')
                attrs['fullinertia'] = ' '.join(str(tensor[i,j]) for i,j in [(0,0),(1,1),(2,2),(0,1),(0,2),(1,2)])
            ET.SubElement(body, 'inertial', attrs)
        xml = ET.tostring(root, encoding='unicode')
        robot = SimpleNamespace(spec_fn=lambda:mujoco.MjSpec.from_string(xml),
                                articulation=SimpleNamespace(actuators=[]))
        return SimpleNamespace(scene=SimpleNamespace(entities={'robot':robot}))

    def test_fifteen_servos_add_75g_with_consistent_inertia_and_no_drift(self):
        cfg = self.config(); original = cfg.scene.entities['robot'].spec_fn().compile()
        apply_robot(cfg, {'servo_mass_model':'hd1910_23g'}, 'official_0151')
        for _ in range(3):
            model = cfg.scene.entities['robot'].spec_fn().compile()
            self.assertAlmostEqual(sum(model.body_mass), .81224318, places=10)
            for b in MODEL['bodies']:
                bid = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,b['name'])
                delta = SERVO_MASS_PROFILE['body_counts'].get(b['name'],0)*.005
                self.assertAlmostEqual(model.body_mass[bid],b['mass_kg']+delta)
                for old, new in zip(original.body_inertia[bid],model.body_inertia[bid]):
                    self.assertAlmostEqual(new,old*(b['mass_kg']+delta)/b['mass_kg'],places=12)
                for old, new in zip(original.body_ipos[bid],model.body_ipos[bid]):
                    self.assertAlmostEqual(old,new,places=12)

    def test_absolute_manual_mass_wins_and_other_body_edits_survive(self):
        cfg = self.config()
        changes = {'servo_mass_model':'hd1910_23g','bodies':{
            'trunk_base':{'mass':.25}, 'ankle_left':{'pos':[.1,0,0]},
            'neck':{'inertia':[1e-5,1e-5,1e-5]}}}
        apply_robot(cfg,copy.deepcopy(changes),'official_0151')
        model = cfg.scene.entities['robot'].spec_fn().compile()
        trunk = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'trunk_base')
        neck = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'neck')
        ankle = mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'ankle_left')
        self.assertAlmostEqual(model.body_mass[trunk],.25)
        self.assertAlmostEqual(sum(model.body_mass),.73724318-.199224+.25+.065)
        self.assertAlmostEqual(model.body_pos[ankle,0],.1)
        for value in model.body_inertia[neck]:self.assertAlmostEqual(value,1e-5,places=12)

    def test_xl330_selection_keeps_original_mass(self):
        cfg = self.config(); apply_robot(cfg,{'servo_mass_model':'xl330_18g'},'official_0151')
        self.assertAlmostEqual(sum(cfg.scene.entities['robot'].spec_fn().compile().body_mass),.73724318)


if __name__ == '__main__': unittest.main()
