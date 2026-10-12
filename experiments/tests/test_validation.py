"""Run with python -B -m unittest discover -s experiments/tests -v."""

import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy import optimize, stats
import main
import validation as v
from utils import sha256_file, validation_settings

SETTINGS = {"significance_level": .05, "chi_square": {"bins": 100, "range": [-5., 5.], "minimum_expected_count": 5}}


class StatisticalValidationTests(unittest.TestCase):
    def test_adjacent_bins(self):
        obs, exp, edges = v.merge_adjacent_bins([1, 4, 8, 1], [1., 4., 8., 1.], [-np.inf, -1, 0, 1, np.inf], 5)
        np.testing.assert_array_equal(obs, [5, 9])
        np.testing.assert_array_equal(exp, [5, 9])
        np.testing.assert_array_equal(edges, [-np.inf, 0, np.inf])
        obs, exp, edges = v.merge_adjacent_bins([0, 5, 5, 0], [0, 5, 5, 0], [-np.inf, -1, 0, 1, np.inf], 5)
        np.testing.assert_array_equal(exp, [5, 5])
        self.assertEqual(edges[-1], np.inf)

    def test_too_few_bins(self):
        for expected in ([1., 1.], [4., 4.], [5., 0.]):
            with self.assertRaises(ValueError):
                v.merge_adjacent_bins([1, 1], expected, [-np.inf, 0, np.inf], 5)

    def test_tails_and_total_accounting(self):
        values=np.r_[np.linspace(-3, 3, 1000), -40, 40, -5, 5]
        result=v.chi_square_test(values, SETTINGS['chi_square'], .05)
        self.assertEqual(result['observed_total'], len(values))
        self.assertAlmostEqual(result['expected_total'], len(values), places=9)
        self.assertEqual(result['outside_range_count'], 2)
        self.assertTrue(all(x >= 5 for x in result['expected_counts']))
        self.assertEqual(result['degrees_of_freedom'], result['final_bins']-1)
        self.assertEqual(result['final_edges'][0], '-inf')
        self.assertEqual(result['final_edges'][-1], '+inf')
        expected=stats.chisquare(result['observed_counts'],result['expected_counts'],ddof=0)
        self.assertEqual(result['statistic'],expected.statistic)
        self.assertEqual(result['p_value'],expected.pvalue)
        result2=v.chi_square_test(values+20, SETTINGS['chi_square'], .05)
        self.assertEqual(result['final_edges'],result2['final_edges'])
        self.assertEqual(result['expected_counts'],result2['expected_counts'])

    def test_non_symmetric_range_and_extreme_tail(self):
        for interval in ([-1., 2.], [-40., 40.]):
            result=v.chi_square_test(np.linspace(-4,4,100000), {'bins':100,'range':interval,'minimum_expected_count':5}, .05)
            self.assertEqual(result['observed_total'],100000)
        with self.assertRaises(ValueError):
            v.chi_square_test(np.linspace(-4,4,1000), {'bins':10,'range':[8.,10.],'minimum_expected_count':5}, .05)

    def test_fixed_null_not_fitted(self):
        quantiles=stats.norm.ppf((np.arange(2000)+.5)/2000)
        reference=v.run_tests(quantiles,SETTINGS)
        self.assertTrue(all(not test['reject'] for test in reference.values()))
        for alternative in (quantiles+.5, quantiles*1.5):
            result=v.run_tests(alternative,SETTINGS)
            self.assertTrue(all(test['reject'] for test in result.values()))
            self.assertAlmostEqual(result['kolmogorov_smirnov']['statistic'],stats.kstest(alternative,'norm',args=(0.,1.),method='exact').statistic)
            self.assertAlmostEqual(result['cramer_von_mises']['statistic'],stats.cramervonmises(alternative,'norm',args=(0.,1.)).statistic)

    def test_ad_statistic_and_extreme_cdf(self):
        x=np.array([-2.,-1.,-.3,.1,.4,.8,1.2,2.])
        f=stats.norm.cdf(np.sort(x))
        expected=-len(x)-np.sum((2*np.arange(1,len(x)+1)-1)*(np.log(f)+np.log1p(-f[::-1])))/len(x)
        self.assertAlmostEqual(v.anderson_darling_statistic(x),expected,places=12)
        result=v.anderson_darling_test(np.array([-40.,-10.,0.,10.,40.]),.05)
        self.assertTrue(np.isfinite(result['statistic']))
        self.assertTrue(result['reject'])
        self.assertIsNone(result['p_value'])
        self.assertTrue(result['p_value_below_resolution'])
        critical=optimize.brentq(lambda z:v._ad_cdf(z,1000000)-.95,0,10)
        self.assertAlmostEqual(critical,2.492,delta=.002)

    def test_ad_reference_cdf_values(self):
        # Values independently evaluated with the authors' AnDarl.c supplement.
        for n,z,expected in ((10,.5,.2573659942339062), (64,2.,.9079722323238504),
                             (1000000,1.,.6427139843932328), (1000000,2.492,.9499859322781976)):
            self.assertAlmostEqual(v._ad_cdf(z,n),expected,places=12)
        values=np.array([-2.,-1.,-.3,.1,.4,.8,1.2,2.])
        result=v.anderson_darling_test(values,.05)
        self.assertAlmostEqual(result['p_value'],1-v._ad_cdf(result['statistic'],len(values)))

    def test_ad_null_calibration(self):
        # Independent empirical check under uniform probability-integral transforms.
        u=np.sort(np.random.default_rng(7291).uniform(size=(20000,64)),axis=1)
        weights=2*np.arange(1,65)-1
        statistic=-64-np.sum(weights*(np.log(u)+np.log1p(-u[:,::-1])),axis=1)/64
        critical=optimize.brentq(lambda z:v._ad_cdf(z,64)-.95,0,10)
        rate=np.mean(statistic>critical)
        self.assertTrue(.04<rate<.06,rate)

    def test_nonfinite_and_bad_settings(self):
        for x in ([0,np.nan],[0,np.inf],[0,-np.inf]):
            with self.assertRaises(ValueError):
                v.run_tests(x,SETTINGS)
        for key,value in (('bins',0),('range',[5,-5]),('minimum_expected_count',0)):
            section=copy.deepcopy(SETTINGS)
            section['chi_square'][key]=value
            with self.assertRaises(ValueError):
                validation_settings({'validation':section})

    def test_loader_rejects_incomplete_bad_size_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'basic_N8_seed1_validation'
            directory.mkdir()
            configuration={'algorithm':'basic','N':8,'seed':1,'num_samples':4}
            summary={'num_samples':4,'mean':0.,'variance':1.}
            (directory/'samples.bin').write_bytes(np.array([-1.,0.,0.,1.],dtype='<f8').tobytes())
            (directory/'config.json').write_text(json.dumps(configuration))
            (directory/'summary.json').write_text(json.dumps(summary))
            execution={'status':'failed','returncode':1,'mode':'validation','algorithm':'basic','N':8,'seed':1,'samples':4,'experiment_id':directory.name}
            def save():
                execution['output_files']={name:{'size_bytes':(directory/name).stat().st_size,'sha256':sha256_file(directory/name)} for name in ('samples.bin','config.json','summary.json')}
                (directory/'execution.json').write_text(json.dumps(execution))
            save()
            with self.assertRaisesRegex(ValueError,'successfully'):
                v.load_completed_run(directory)
            execution.update(status='successful',returncode=0)
            (directory/'samples.bin').write_bytes(b'123')
            save()
            with self.assertRaisesRegex(ValueError,'size'):
                v.load_completed_run(directory)
            (directory/'samples.bin').write_bytes(np.array([0.,0.,0.,np.inf],dtype='<f8').tobytes())
            save()
            with self.assertRaisesRegex(ValueError,'NaN/infinity'):
                v.load_completed_run(directory)

    def test_validate_cli_never_enters_benchmark_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'config.yaml'
            path.write_text('validation: {}\n')
            with patch.object(sys,'argv',['main.py','--config',str(path),'--validate']), patch('main.dry_run',side_effect=AssertionError('planner entered')), patch('main.execute_plan',side_effect=AssertionError('benchmark entered')), patch('subprocess.run',side_effect=AssertionError('subprocess entered')), patch('validation.validate_existing',return_value={'status':'successful'}) as validate, patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(main.main(),0)
                validate.assert_called_once()


if __name__=='__main__':
    unittest.main()
