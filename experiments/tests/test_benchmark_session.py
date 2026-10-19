"""Only temporary sysfs fixtures and harmless Python workloads; no RNG invocations."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import benchmark_session as session
import frequency_control as control


class FrequencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for n in (7, 15):
            p = self.root / f'cpufreq/policy{n}'
            p.mkdir(parents=True)
            for key, value in {'scaling_driver': 'acpi-cpufreq', 'scaling_governor': 'schedutil', 'scaling_min_freq': '2200000',
                               'scaling_max_freq': '3700000', 'scaling_available_frequencies': '3700000 3200000 2200000',
                               'scaling_available_governors': 'schedutil userspace performance',
                               'related_cpus': str(n), 'scaling_setspeed': '<unsupported>',
                               'cpuinfo_min_freq': '2200000', 'cpuinfo_max_freq': '3700000'}.items():
                (p / key).write_text(value)
        (self.root / 'cpufreq/boost').write_text('1')

    def test_plan_apply_restore_both_smt_policies(self):
        data = control.plan(3200000, True, self.root)
        self.assertEqual(len(data['policies']), 2)
        self.assertFalse(data['physical_clock_verified'])
        self.assertEqual(control.read(self.root / 'cpufreq/policy7/scaling_governor'), 'schedutil')
        journal = self.root / 'journal.json'
        control.durable(journal, data)
        control.apply(data, self.root)
        self.assertEqual(control.read(self.root / 'cpufreq/policy15/scaling_min_freq'), '3200000')
        self.assertEqual(control.read(self.root / 'cpufreq/boost'), '0')
        restored = control.restore(json.loads(journal.read_text()), self.root)
        self.assertTrue(restored['verified'], restored)
        self.assertEqual(control.read(self.root / 'cpufreq/policy7/scaling_governor'), 'schedutil')
        self.assertEqual(control.read(self.root / 'cpufreq/boost'), '1')
        self.assertFalse(journal.with_suffix('.tmp').exists())

    def test_unsupported_frequency_and_missing_userspace(self):
        with self.assertRaises(ValueError): control.plan(3300000, root=self.root)
        (self.root / 'cpufreq/policy7/scaling_available_governors').write_text('schedutil')
        with self.assertRaises(ValueError): control.plan(3200000, root=self.root)

    def test_partial_apply_restores_originals(self):
        data = control.plan(3200000, root=self.root)
        original_write = control.write
        def fail(path, value):
            if path.parent.name == 'policy15' and path.name == 'scaling_setspeed':
                raise OSError('simulated control rejection')
            original_write(path, value)
        try:
            with patch.object(control, 'write', side_effect=fail):
                control.apply(data, self.root)
        except OSError:
            pass
        else:
            self.fail('expected rejection')
        self.assertTrue(control.restore(data, self.root)['verified'])

    def test_restore_attempts_all_policies_and_governors_after_limit_failure(self):
        data = control.plan(3200000, root=self.root)
        control.apply(data, self.root)
        original_write = control.write
        def fail(path, value):
            if path.parent.name == 'policy7' and path.name == 'scaling_min_freq':
                raise OSError('simulated permission loss')
            original_write(path, value)
        with patch.object(control, 'write', side_effect=fail):
            report = control.restore(data, self.root)
        self.assertFalse(report['verified'])
        self.assertEqual(control.read(self.root / 'cpufreq/policy7/scaling_governor'), 'schedutil')
        self.assertEqual(control.read(self.root / 'cpufreq/policy15/scaling_min_freq'), '2200000')

    def test_original_userspace_setpoint_and_malicious_journal(self):
        p = self.root / 'cpufreq/policy7'
        (p / 'scaling_governor').write_text('userspace')
        (p / 'scaling_setspeed').write_text('2200000')
        data = control.plan(3200000, root=self.root)
        control.apply(data, self.root)
        self.assertTrue(control.restore(data, self.root)['verified'])
        self.assertEqual(control.read(p / 'scaling_setspeed'), '2200000')
        data['policies'][0]['policy'] = '../../escape'
        with self.assertRaises(ValueError): control.validate_journal(data)


class SessionTests(unittest.TestCase):
    def test_bios_warns_without_claiming_effective_clock(self):
        state = {'policies': {'policy7': {'scaling_cur_freq': '3700000'}},
                 'related_policies': {}, 'boost': '1'}
        report = session.verify('bios', 3200000, state, .05)
        self.assertFalse(report['physical_clock_verified'])
        self.assertEqual(len(report['warnings']), 3)

    def test_software_requires_matching_requested_state(self):
        state = {'policies': {'policy7': {'scaling_governor': 'schedutil'}}, 'boost': '1'}
        with self.assertRaises(ValueError): session.verify('software', 3200000, state, .05)

    def test_baseline_exit_code_logs_and_affinity(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(session, 'SESSIONS', Path(temporary)), patch.object(session.common, 'capture', return_value={}), contextlib.redirect_stdout(io.StringIO()):
            code = session.main(['--mode', 'baseline', '--', sys.executable, '-c',
                                 'import os,json,sys;print(json.dumps(sorted(os.sched_getaffinity(0))));sys.exit(9)'])
            self.assertEqual(code, 9)
            directories = [p for p in Path(temporary).iterdir() if p.is_dir()]
            self.assertEqual(len(directories), 1)
            p = directories[0]
            self.assertEqual(json.loads((p / 'stdout.txt').read_text()), [7])
            self.assertEqual(json.loads((p / 'restoration.json').read_text())['status'], 'not_needed')
            self.assertIn('unavailable', (p / 'cpu_telemetry.csv').read_text())
            self.assertEqual(json.loads((p / 'session.json').read_text())['exit_status'], 9)

    def test_inherited_lock_and_legacy_launcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / 'experiments/results/linux_ryzen2700x/sessions'
            parent.mkdir(parents=True)
            with session.common.acquire_session_lock(parent) as lock:
                code = ('import sys;from pathlib import Path;'
                        f'sys.path.insert(0,{str(TOOLS)!r});import cpu_benchmark as c;'
                        'lock=c.acquire_session_lock(Path(sys.argv[1]));print("inherited lock verified")')
                env = dict(os.environ, GRNG_SESSION_LOCK_FD=str(lock.fileno()))
                result = subprocess.run([sys.executable,'-B','-c',code,str(parent)],
                                        pass_fds=(lock.fileno(),),env=env,capture_output=True,text=True,check=True,timeout=10)
                self.assertIn('verified',result.stdout)
            with patch.object(session.common,'REPOSITORY',root), patch.object(session.common,'capture',return_value={}), contextlib.redirect_stdout(io.StringIO()):
                result = session.common.main(['--cpu','7','--',sys.executable,'-c','raise SystemExit(4)'])
            self.assertEqual(result,4)
            directory=next(p for p in parent.iterdir() if p.is_dir())
            self.assertTrue((directory/'before.json').is_file())
            self.assertEqual(json.loads((directory/'session.json').read_text())['returncode'],4)

    def test_software_unapproved_never_launches(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(session.subprocess, 'Popen') as launch, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): session.main(['--mode', 'software', '--', '/bin/true'])
            launch.assert_not_called()

    def test_signals_overlap_and_harmless_process(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=signum):
                self.check_signal(signum)

    def check_signal(self, signum):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ready = root / 'ready'
            workload = f'from pathlib import Path;import time;Path({str(ready)!r}).write_text("ready");time.sleep(20)'
            bootstrap = ('import sys;from pathlib import Path;'
                         f'sys.path.insert(0,{str(TOOLS)!r});import benchmark_session as s;'
                         f's.SESSIONS=Path({str(root)!r});s.common.capture=lambda argv:{{}};'
                         f'raise SystemExit(s.main(["--telemetry-interval","0.2","--",sys.executable,"-c",{workload!r}]))')
            env = {k:v for k,v in os.environ.items() if not k.startswith('GRNG_')}
            process = subprocess.Popen([sys.executable, '-B', '-c', bootstrap], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 8
                while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(.02)
                self.assertTrue(ready.exists())
                with patch.object(session, 'SESSIONS', root), patch.object(session.common, 'capture', return_value={}), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(BlockingIOError): session.main(['--', '/bin/true'])
                time.sleep(.25)  # Permit one telemetry sample, not an RNG benchmark.
                process.send_signal(signum)
                stdout, stderr = process.communicate(timeout=8)
                self.assertEqual(process.returncode, 128 + signum, (stdout, stderr))
                directory = next(p for p in root.iterdir() if p.is_dir())
                data = json.loads((directory / 'session.json').read_text())
                self.assertEqual(data['signals'], [signum])
                self.assertIn('running', (directory / 'cpu_telemetry.csv').read_text())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=3)



class SupervisorTests(unittest.TestCase):
    """Mock administrative guard/process launch; all writes target temporary fixtures."""
    setUp = FrequencyTests.setUp

    def exercise(self, rc=5, interrupted=False, interrupted_status=-15, report_rc=0):
        from contextlib import ExitStack
        original_plan, original_apply, original_restore = control.plan, control.apply, control.restore
        state = self.root / 'state'
        sessions = self.root / 'sessions'
        sessions.mkdir()
        (sessions / '.controller.lock').touch()
        class Process:
            pid = 99999999
            returncode = None if interrupted else rc
            def wait(self, timeout=None):
                if self.returncode is None and timeout is None:
                    self.returncode = interrupted_status
                    raise InterruptedError(signal.SIGTERM)
                return self.returncode
            def poll(self): return self.returncode
        args = ['frequency_control.py', '--approve-temporary-control', '--user',
                control.pwd.getpwuid(os.getuid()).pw_name, '--session-root', str(sessions), '--', '/bin/false']
        with ExitStack() as stack:
            stack.enter_context(patch.object(control, 'STATE', state))
            stack.enter_context(patch.object(control, 'require_admin'))
            stack.enter_context(patch.object(control, 'trusted'))
            stack.enter_context(patch.object(control, 'plan', side_effect=lambda t,b=False: original_plan(t,b,self.root)))
            stack.enter_context(patch.object(control, 'apply', side_effect=lambda d: original_apply(d,self.root)))
            stack.enter_context(patch.object(control, 'restore', side_effect=lambda d: original_restore(d,self.root)))
            launch = stack.enter_context(patch.object(control.subprocess, 'Popen', return_value=Process()))
            stack.enter_context(patch.object(control.subprocess, 'run', return_value=subprocess.CompletedProcess([],report_rc)))
            stack.enter_context(patch.object(sys, 'argv', args))
            output = io.StringIO()
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            status = control.main()
        expected = (interrupted_status if interrupted_status >= 0 else 128 - interrupted_status) if interrupted else rc
        self.assertEqual(status, expected)
        if report_rc:
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1])['status'], 'failed')
        self.assertEqual(launch.call_args.args[0][:3], ['/usr/sbin/runuser', '-u', control.pwd.getpwuid(os.getuid()).pw_name])
        journal = json.loads(next(state.glob('*.json')).read_text())
        self.assertEqual(journal['status'], 'restored')
        self.assertTrue(journal['restoration']['verified'])
        self.assertEqual(control.read(self.root / 'cpufreq/policy15/scaling_governor'), 'schedutil')
        return state, journal

    def test_supervisor_failure_exit_and_finally_restoration(self): self.exercise()
    def test_supervisor_interruption_and_finally_restoration(self): self.exercise(interrupted=True)

    def test_supervisor_preserves_handled_signal_exit_status(self):
        self.exercise(interrupted=True, interrupted_status=9)

    def test_report_delivery_failure_keeps_workload_status(self):
        self.exercise(rc=0, report_rc=1)

    def test_recovery_replays_durable_originals(self):
        state, journal = self.exercise()
        control.apply(journal, self.root)
        path = next(state.glob('*.json'))
        journal['status'] = 'applied'
        control.durable(path, journal)
        original_restore = control.restore
        with patch.object(control, 'STATE', state), patch.object(control, 'CPU', self.root), patch.object(control, 'require_admin'), patch.object(control, 'trusted'), patch.object(control, 'restore', side_effect=lambda d: original_restore(d,self.root)), patch.object(sys,'argv', ['frequency_control.py','--approve-temporary-control','--recover',journal['journal_id'],'--confirm-workload-stopped']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(control.main(), 0)
        self.assertEqual(json.loads(path.read_text())['status'], 'recovered')
        self.assertEqual(control.read(self.root / 'cpufreq/policy7/scaling_min_freq'), '2200000')


if __name__ == '__main__':
    unittest.main()
