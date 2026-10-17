"""Small tests: at most 256 samples per subprocess and 64 KiB buffers."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from utils import load_config, validate_config
from analysis import uniform_speedups
ROOT=Path(__file__).resolve().parents[2]

class UniformTests(unittest.TestCase):
    def call(self,*args,code=0):
        result=subprocess.run([str(ROOT/'c/benchmark'),'--samples','256',*args,'--report-json'],capture_output=True,text=True)
        self.assertEqual(result.returncode,code,result.stderr)
        return json.loads(next(x.split(': ',1)[1] for x in result.stdout.splitlines() if x.startswith('BENCHMARK_JSON: ')))
    def test_streams_cache_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            for prng in ('pcg32','xoshiro256plus'):
                for algorithm in ('basic','trapezoid'):
                    common=['--algorithm',algorithm,'--prng',prng,'--seed','2','--warmup','10']
                    inline=self.call(*common)
                    cache=str(Path(tmp)/(prng+algorithm+'.cache'))
                    buffered=self.call(*common,'--uniform-mode','precomputed','--uniform-buffer-bytes','65536','--uniform-buffer-cache',cache)
                    repeated=self.call(*common,'--uniform-mode','precomputed','--uniform-buffer-bytes','65536','--uniform-buffer-cache',cache)
                    for key in ('checksum','mean','variance','uniform_values_consumed'):
                        self.assertEqual(inline[key],buffered[key]);self.assertEqual(buffered[key],repeated[key])
                    directory=Path(tmp)/(prng+algorithm)
                    output=self.call(*common,'--uniform-mode','precomputed','--uniform-buffer-bytes','65536','--output-dir',str(directory))
                    self.assertEqual(json.loads((directory/'summary.json').read_text())['uniform_values_consumed'],output['uniform_values_consumed'])
                    self.assertEqual((directory/'samples.bin').stat().st_size,256*8)
                    self.assertEqual(json.loads((directory/'config.json').read_text())['uniform_mode'],'precomputed')
    def test_exhaustion(self):
        for algorithm in ('basic','trapezoid'):
            for size in ('8','32','128'):
                result=self.call('--algorithm',algorithm,'--uniform-mode','precomputed','--uniform-buffer-bytes',size,code=3)
                self.assertFalse(result['complete']);self.assertTrue(result['buffer_exhausted'])
                self.assertIsNone(result['throughput_samples_per_second'])
                self.assertEqual(result['uniform_values_consumed'],int(size)//8)
    def test_harness(self):
        config=load_config(ROOT/'experiments/config.yaml')
        self.assertFalse(validate_config(config))
        config.update(uniform_mode='precomputed',uniform_buffer_size_bytes=65536)
        self.assertFalse(validate_config(config))
        configurations=runner.expand_configurations(config)
        run=runner.build_runs(config,configurations,ROOT)[0]
        self.assertIn('--uniform-mode',run['argv']);self.assertIn('_precomputed',run['experiment_id'])
        run['samples']=256
        text=subprocess.run([str(ROOT/'c/benchmark'),'--algorithm',run['algorithm'],'--layers',str(run['N']),'--samples','256','--uniform-mode','precomputed','--uniform-buffer-bytes','65536','--report-json'],capture_output=True,text=True,check=True).stdout
        result=runner.parse_benchmark_stdout(text,run)
        self.assertEqual(result['uniform_mode'],'precomputed')
        with self.assertRaises(ValueError):runner.check_summary(dict(result,complete=False),run)
        config['uniform_mode']='bad';self.assertTrue(validate_config(config))
    def test_small_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=load_config(ROOT/'experiments/config.yaml')
            config.update(uniform_mode='precomputed',uniform_buffer_size_bytes=65536,output_dir=tmp+'/runs')
            config['performance'].update(samples=128,repetitions=2)
            config['validation']['enabled']=False
            plan=runner.dry_run(config,ROOT)
            self.assertEqual(plan['status'],'valid',plan['errors'])
            report=runner.execute_plan(plan,ROOT,config)
            self.assertEqual(report['status'],'successful',report.get('errors'))
            cache_paths=[]
            for run in report['runs']:
                argv=run['actual_argv']
                cache_paths.append(argv[argv.index('--uniform-buffer-cache')+1])
                self.assertEqual(run['benchmark_results']['uniform_mode'],'precomputed')
            self.assertEqual(len(set(cache_paths)),1)
            self.assertFalse(Path(cache_paths[0]).exists())
            resumed=runner.execute_plan(runner.dry_run(config,ROOT,resume=True),ROOT,config,resume=True)
            self.assertEqual(resumed['skipped_runs'],6)

    def test_speedups(self):
        base=dict(algorithm='basic',N=8,H=None,T=None,prng='pcg32',seed=1,samples=256,status='successful',mode='performance',provenance={'benchmark_sha256':'same'})
        runs=[dict(base,uniform_mode=mode,benchmark_results={'complete':True,'throughput_samples_per_second':speed}) for mode,speed in [('inline',10),('precomputed',20)]]
        self.assertEqual(uniform_speedups(runs)[0]['speedup'],2)
        runs[1]['benchmark_results']['complete']=False
        self.assertEqual(uniform_speedups(runs),[])
if __name__=='__main__':unittest.main()
