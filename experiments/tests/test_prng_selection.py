"""Small PRNG configuration and CLI checks; no statistics or sample files."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analysis
import experiment01
import runner
from utils import load_config, validate_config

REPOSITORY=Path(__file__).resolve().parents[2]
class PRNGTests(unittest.TestCase):
    def setUp(self):
        self.config=load_config(REPOSITORY/'experiments/prng_comparison.yaml')
    def test_config_and_collisions(self):
        default=copy.deepcopy(self.config); default.pop('prng')
        self.assertEqual(validate_config(default), [])
        a=runner.expand_configurations(default)
        self.assertEqual(a, runner.expand_configurations(self.config))
        variant=copy.deepcopy(self.config); variant['prng']['type']='xoshiro256plus'
        self.assertEqual(validate_config(variant), [])
        b=runner.expand_configurations(variant)
        self.assertFalse({r['parameter_id'] for r in a}&{r['parameter_id'] for r in b})
        for run in runner.build_runs(variant,b,REPOSITORY):
            self.assertIn('--prng',run['argv']); self.assertIn('xoshiro256plus',run['argv'])
            self.assertNotIn('--output-dir',run['argv'])
        invalid=copy.deepcopy(self.config); invalid['prng']['type']='xoshiro256**'
        self.assertTrue(validate_config(invalid))
        for section in (None, {}, {'type':'bad'}, {'type':'pcg32','unknown':1}):
            invalid['prng']=section; self.assertTrue(validate_config(invalid))
    def test_legacy_analysis_and_metadata(self):
        row=dict(algorithm='basic',N=128,H=None,T=None,seed=1,benchmark_sha256='example')
        self.assertEqual(analysis._key(row),analysis._key(dict(row,prng='pcg32')))
        self.assertNotEqual(analysis._key(row),analysis._key(dict(row,prng='xoshiro256plus')))
        for prng in ('pcg32','xoshiro256plus'):
            cfg=copy.deepcopy(self.config); cfg['prng']['type']=prng
            parameters=runner.expand_configurations(cfg)[0]
            run=runner.build_runs(cfg,[parameters],REPOSITORY)[0]; run['samples']=4096
            argv=run['argv'].copy(); argv[argv.index('--samples')+1]='4096'
            result=subprocess.run(argv+['--report-json'],capture_output=True,text=True,check=True)
            parsed=runner.parse_benchmark_stdout(result.stdout,run)
            self.assertEqual(parsed['prng'],prng)
            full=json.loads(next(s.split(': ',1)[1] for s in result.stdout.splitlines() if s.startswith('BENCHMARK_JSON:')))
            self.assertEqual(full['prng'],prng)
            wrong=dict(run,prng='xoshiro256plus' if prng=='pcg32' else 'pcg32')
            with self.assertRaises(ValueError): runner.parse_benchmark_stdout(result.stdout,wrong)
            ex=experiment01._run(parameters,'performance',1,4096,REPOSITORY,Path('/tmp'))
            self.assertEqual('--prng' in ex['argv'],prng!='pcg32')
            # Default output and explicit PCG still have identical checksums.
            if prng=='pcg32':
                explicit=subprocess.run(argv+['--prng','pcg32','--report-json'],capture_output=True,text=True,check=True)
                value=json.loads(next(s.split(': ',1)[1] for s in explicit.stdout.splitlines() if s.startswith('BENCHMARK_JSON:')))
                self.assertEqual(value['checksum'],full['checksum'])
    def test_invalid_cli(self):
        for args in (['--prng','invalid'],['--prng'],['--prng','xoshiro256plus','--profile-prng']):
            p=subprocess.run([str(REPOSITORY/'c/benchmark'),'--samples','2',*args],capture_output=True)
            self.assertEqual(p.returncode,2)
if __name__=='__main__': unittest.main()
