"""Experiment 01 schedule and full-data numerical regression tests."""
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import experiment01
import runner
import validation
from utils import load_config, validate_config


class Experiment01Tests(unittest.TestCase):
    def test_full_matrix_and_interleaving(self):
        config=load_config(Path(__file__).resolve().parents[1]/'experiment_01.yaml')
        self.assertEqual(validate_config(config),[])
        configurations,runs=experiment01.schedule(config,Path('/tmp/example-repository'))
        self.assertEqual(len(configurations),78)
        self.assertEqual(len(runs),936)
        self.assertEqual(sum(r['kind']=='performance' for r in runs),780)
        self.assertEqual(sum(r['kind']=='profiling' for r in runs),78)
        self.assertEqual(sum(r['kind']=='validation' for r in runs),78)
        self.assertEqual({r['repetition'] for r in runs[:78]},{1})
        self.assertEqual({r['repetition'] for r in runs[78:156]},{2})
        self.assertEqual(len({r['experiment_id'] for r in runs}),len(runs))
        self.assertEqual(sum(c['algorithm_label']=='trapezoid_refined' for c in configurations),72)
        self.assertFalse(any(c['algorithm_label']=='trapezoid_refined' and c['H']==0 and c['T']==0
                             for c in configurations))
        self.assertTrue(any(c['H']==0 and c['T']>0 for c in configurations if c['H'] is not None))
        self.assertTrue(any(c['T']==0 and c['H']>0 for c in configurations if c['T'] is not None))

    def test_chunked_statistics_match_existing_methods(self):
        settings={'significance_level':.05,'chi_square':{'bins':100,'range':[-5.,5.],
                  'minimum_expected_count':5}}
        values=np.random.default_rng(321).normal(size=10000)
        existing=validation.run_tests(values,settings)
        new=validation.run_tests_chunked(values,settings,[2.,3.,4.],block_size=307)
        for key in existing:
            self.assertAlmostEqual(existing[key]['statistic'],new['tests'][key]['statistic'],places=10)
            self.assertAlmostEqual(existing[key]['p_value'],new['tests'][key]['p_value'],places=10)
            self.assertEqual(existing[key]['reject'],new['tests'][key]['reject'])
        self.assertEqual(len(new['tails']),3)
        self.assertTrue(math.isfinite(new['mean']))
        self.assertTrue(math.isfinite(new['variance']))

    def test_old_smoke_configuration_remains_valid(self):
        config=load_config(Path(__file__).resolve().parents[1]/'config.yaml')
        self.assertEqual(validate_config(config),[])
        self.assertEqual(len(runner.expand_configurations(config)),3)


if __name__=='__main__':
    unittest.main()
