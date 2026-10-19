"""Output isolation checks; fixtures and subprocess output live only in temporary directories."""
import copy
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runner
import validation
import analysis
import plotting
from utils import load_config, result_paths, validate_config
ROOT = Path(__file__).resolve().parents[2]


class ResultPathsTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / 'experiments/config_linux_ryzen2700x.yaml')

    def test_schedule_and_defaults(self):
        original = load_config(ROOT / 'experiments/config.yaml')
        expected = dict(self.config)
        expected.pop('results_root')
        self.assertEqual(expected, original)
        self.assertEqual(validate_config(self.config), [])
        self.assertEqual(result_paths(original, ROOT)['raw'], ROOT / 'experiments/results/raw')
        legacy = dict(original, output_dir='custom/raw')
        self.assertEqual(result_paths(legacy, ROOT)['raw'], ROOT / 'custom/raw')
        self.assertEqual(result_paths(legacy, ROOT)['processed'], ROOT / 'experiments/results/processed')
        runs = runner.build_runs(self.config, runner.expand_configurations(self.config), ROOT)
        old = runner.build_runs(original, runner.expand_configurations(original), ROOT)
        self.assertEqual([r['experiment_id'] for r in runs], [r['experiment_id'] for r in old])
        self.assertEqual(len(runs), 12)
        for run in runs:
            self.assertTrue(Path(run['output_directory']).is_relative_to(ROOT / self.config['results_root']))

    def test_analysis_cli_modes(self):
        help_text = subprocess.check_output([sys.executable, "-B", str(ROOT / "experiments/analysis.py"), "--help"], text=True)
        self.assertIn("--config", help_text)
        self.assertIn("--uniform-speedups", help_text)
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.check_output([sys.executable, "-B", str(ROOT / "experiments/analysis.py"), "--uniform-speedups", temporary], text=True)
            self.assertEqual(json.loads(result), [])

    def test_invalid_roots(self):
        for value in ('', '/tmp/absolute', '../escape', 'bad\npath', None):
            self.assertTrue(validate_config(dict(self.config, results_root=value)))
        self.assertTrue(validate_config(dict(self.config, output_dir='other')))

    def test_collision_resume_and_validation_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'c').mkdir()
            (root / 'c/benchmark.c').write_text((ROOT / 'c/benchmark.c').read_text())
            paths = result_paths(self.config, root)
            first = runner.build_runs(self.config, runner.expand_configurations(self.config), root)[0]
            directory = Path(first['output_directory'])
            directory.mkdir(parents=True)
            sentinel = directory / 'keep.txt'
            sentinel.write_text('preserve')
            self.assertEqual(runner.dry_run(self.config, root)['status'], 'invalid')
            with patch('runner.benchmark_identity', return_value={'sha256': 'test'}), patch('runner.resume_action', return_value={'action': 'skip'}):
                self.assertEqual(runner.dry_run(self.config, root, resume=True)['status'], 'valid')
            with patch('validation._save_results') as save:
                report = validation.validate_existing(self.config, root)
                self.assertEqual(report['benchmark_executions_performed'], 0)
                self.assertEqual(save.call_args.args[1], paths['processed'])
            self.assertEqual(sentinel.read_text(), 'preserve')

    def test_small_run_resume_analysis_plot_and_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = copy.deepcopy(self.config)
            # Existing output_dir remains supported for an absolute temporary raw path.
            # Patch resolution so all derived products also stay in this temporary tree.
            paths = {key: Path(temporary) / value for key, value in
                     {'root': '.', 'raw': 'raw', 'processed': 'processed', 'figures': 'figures', 'reports': 'raw/_reports'}.items()}
            config['performance'].update(samples=128, repetitions=1)
            config['validation']['samples'] = 128
            with patch('utils.result_paths', return_value=paths), patch('runner.result_paths', return_value=paths):
                plan = runner.dry_run(config, ROOT)
                self.assertEqual(plan['status'], 'valid', plan['errors'])
                report = runner.execute_plan(plan, ROOT, config)
                self.assertEqual(report['status'], 'successful', report.get('errors'))
                self.assertEqual(runner.dry_run(config, ROOT)['status'], 'invalid')
                resumed = runner.execute_plan(runner.dry_run(config, ROOT, resume=True), ROOT, config, resume=True)
                self.assertEqual(resumed['skipped_runs'], 6)
                self.assertEqual(analysis.analyze_runs(config, ROOT), paths['processed'] / 'performance_results.csv')
                self.assertEqual(plotting.plot_runs(config, ROOT), paths['figures'])
                with patch('validation.run_tests', return_value={}):
                    # Statistical machinery has its own tests; check routing here.
                    validated = validation.validate_existing(config, ROOT)
                self.assertEqual(validated['datasets_validated'], 3)
                self.assertTrue((paths['processed'] / 'validation_results.json').is_file())
                self.assertFalse(any(Path(temporary).rglob('*.cache')))


if __name__ == '__main__':
    unittest.main()
