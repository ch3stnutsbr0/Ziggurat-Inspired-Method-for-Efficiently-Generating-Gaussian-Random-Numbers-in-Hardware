"""Read-only fixture diagnostics and bounded harmless subprocess regressions."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0, str(TOOLS))
import isolation_readiness as ready
import isolation_manager as iso
import cpu_benchmark as common
import interference_monitor as monitor


def stat_text(tid, ticks=1, start=42, flags=0x200000, cpu=7, name='kworker/7:1'):
    fields = ['S']+['0']*45
    fields[6], fields[11], fields[12] = str(flags), str(ticks), '0'
    fields[19], fields[36] = str(start), str(cpu)
    return f'{tid} ({name}) '+ ' '.join(fields)


class ReadinessTests(unittest.TestCase):
    def fixture(self, base, tid=186, **kwargs):
        path=base/str(tid)/'task'/str(tid)
        path.mkdir(parents=True, exist_ok=True)
        (path/'stat').write_text(stat_text(tid, **kwargs))
        return path/'stat'

    def test_kernel_name_state_affinity_and_nonmigratable_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(Path(tmp), flags=0x4200000, name='worker with ) paren/7:1')
            snap=ready.thread_snapshot(Path(tmp), lambda tid: {7})
            row=next(iter(snap['tasks'].values()))
            self.assertTrue(row['kernel_thread'])
            self.assertTrue(row['affinity_user_change_forbidden'])
            self.assertTrue(row['per_cpu_name_hint'])
            self.assertEqual(row['last_cpu'], 7)
            self.assertEqual(row['state'], 'S')

    def test_tick_delta_does_not_claim_execution_on_last_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp))
            before=ready.thread_snapshot(Path(tmp), lambda tid: {0,7,15})
            path.write_text(stat_text(186, ticks=6, cpu=15))
            after=ready.thread_snapshot(Path(tmp), lambda tid: {0,7,15})
            row=ready.thread_deltas(before, after, hz=100)[0]
            self.assertEqual(row['cpu_seconds_delta'], .05)
            self.assertTrue(row['consumed_cpu_anywhere'])
            self.assertIn('UNVERIFIED', row['actual_execution_on_reserved_cpus'])

    def test_pid_reuse_does_not_create_cpu_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp), ticks=100, start=1)
            before=ready.thread_snapshot(Path(tmp), lambda tid: {7})
            path.write_text(stat_text(186, ticks=2, start=2))
            after=ready.thread_snapshot(Path(tmp), lambda tid: {7})
            rows=ready.thread_deltas(before, after)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row['cpu_ticks_delta'] is None for row in rows))

    def test_reuse_during_affinity_read_is_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=self.fixture(Path(tmp), start=1)
            def getter(tid):
                path.write_text(stat_text(tid, start=2)); return {7}
            result=ready.thread_snapshot(Path(tmp), getter)
            self.assertFalse(result['tasks'])
            self.assertEqual(result['races'], 1)

    def test_permission_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fixture(Path(tmp))
            def getter(tid): raise PermissionError('denied fixture')
            result=ready.thread_snapshot(Path(tmp), getter)
            self.assertIn('denied', result['errors'][0]['error'])
            self.assertFalse(result['tasks'])

    def test_blockers_separate_inspection_context_from_host(self):
        state={'siblings':'7,15', 'errors':['Failed to connect to bus: Operation not permitted',
               'Root cgroup contains namespace-hidden PIDs'], 'root_subtree_control':'memory pids'}
        rows={r['check']:r for r in ready.blockers(state, {'errors':state['errors']})}
        self.assertEqual(rows['system bus']['classification'], 'Requires administrative authorization')
        self.assertEqual(rows['host task visibility']['classification'], 'Not yet verified')
        self.assertEqual(rows['CPU7/15 topology']['classification'], 'Resolved')

    def test_hierarchy_records_empty_inheritance_and_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'system.slice').mkdir()
            (root/'cpuset.cpus').write_text('')
            (root/'cpuset.cpus.effective').write_text('0-15')
            rows=ready.hierarchy(root)
            self.assertEqual(rows[0]['files']['cpuset.cpus'], '')
            self.assertEqual(rows[0]['files']['cpuset.cpus.effective'], '0-15')
            self.assertIn('uid', rows[1])

    def test_metadata_command_timeout_is_unavailable(self):
        with patch.object(common.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['probe'], 15)) as run:
            self.assertIn('unavailable', common.capture(['probe']))
            self.assertEqual(run.call_args.kwargs['timeout'], 15)

    def test_finalizer_has_bounded_timeout(self):
        with patch.object(iso.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            iso.report_as_user('fixture', Path('/unused'), {}, TOOLS)
            self.assertEqual(run.call_args.kwargs['timeout'], 20)

    def test_proxy_heartbeat_and_exit_status_with_mock_socket(self):
        class Sock:
            def settimeout(self, seconds): self.timeout=seconds
            def sendmsg(self, *args): pass
            def recv(self, count): return next(self.responses)
        sock=Sock(); sock.responses=iter([b'{"heartbeat":true}', b'{"exit_status":9}'])
        with patch.object(iso.os, 'geteuid', return_value=1001), patch.object(iso.os,'dup',return_value=99), patch.object(iso.socket,'socket',return_value=sock):
            self.assertEqual(iso.proxy(['/bin/true'], 3), 9)
            self.assertEqual(sock.timeout, 20)

    def test_invalid_session_timeout_rejected_without_mutation(self):
        with patch.object(sys,'argv',['isolation_manager.py','plan','--session-timeout','nan']):
            with self.assertRaises(ValueError): iso.main()

    def test_pidfd_signal_checks_identity_and_closes_descriptor(self):
        import signal
        with patch.object(iso.os,'pidfd_open',return_value=99),patch.object(iso,'pid_start',return_value='new'),patch.object(iso.signal,'pidfd_send_signal') as send,patch.object(iso.os,'close') as close:
            with self.assertRaises(ValueError): iso.signal_identified(42,'old',signal.SIGTERM)
            send.assert_not_called(); close.assert_called_once_with(99)
        with patch.object(iso.os,'pidfd_open',return_value=99),patch.object(iso,'pid_start',return_value='old'),patch.object(iso.signal,'pidfd_send_signal') as send,patch.object(iso.os,'close'):
            iso.signal_identified(42,'old',signal.SIGTERM)
            send.assert_called_once_with(99,signal.SIGTERM)

    def test_probe_help_only_does_not_execute_workload(self):
        result=subprocess.run([sys.executable, '-B', str(TOOLS/'isolation_probe.py'), '--help'],
                              capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--duration', result.stdout)

    def test_lightweight_quality_never_certifies_no_interference(self):
        result=monitor.quality({'isolation_verified':True, 'trace_complete':False})
        self.assertNotEqual(result['classification'], 'PASS')
        self.assertEqual(result['scheduling_interference'], 'UNVERIFIED')
        denied=monitor.quality({'isolation_verified':True,'trace_coverage_complete':True,'trace_loss_verified_zero':True,'proc_visibility_complete':True,'monitor_errors':['denied']})
        self.assertEqual(denied['scheduling_interference'],'UNVERIFIED')


class ReadinessFixtureTests(unittest.TestCase):
    def setUp(self):
        from test_cpu_isolation import IsolationTests
        IsolationTests.setUp(self)

    def state(self):
        return iso.inspect(self.backend, self.cg, self.cpu, self.proc)

    def test_empty_systemd_properties_use_actual_effective_cpuset(self):
        self.backend.values['init.scope']['EffectiveCPUs']=''
        (self.cg/'init.scope/cpuset.cpus.effective').write_text('0-3')
        result=iso.plan(self.state())
        self.assertFalse(result['errors'])
        change=next(c for c in result['changes'] if c['unit']=='init.scope')
        self.assertEqual(iso.cpus(change['target']), {0,1,2,3})

    def test_nested_reserved_only_cgroup_blocks_service_starvation(self):
        child=self.cg/'system.slice/critical.service'
        child.mkdir(); (child/'cpuset.cpus.effective').write_text('7,15')
        result=iso.plan(self.state())
        self.assertTrue(any('starvation' in error for error in result['errors']))

    def test_partial_activation_cancellation_restores_completed_changes(self):
        data=iso.plan(self.state())
        with self.assertRaisesRegex(ValueError,'cancelled'):
            iso.apply(data,self.backend,self.path,cancelled=lambda:bool(self.backend.calls))
        self.assertEqual(len(self.backend.calls),1)
        self.assertEqual(data['changes'][0]['phase'],'applied')
        self.assertTrue(iso.restore(data,self.backend)['verified'])
        self.assertTrue(all(v['AllowedCPUs']=='' for v in self.backend.values.values()))

    def test_new_root_userspace_is_not_outside_verification(self):
        data=iso.plan(self.state()); iso.apply(data,self.backend,self.path)
        task=self.proc/'999'; task.mkdir()
        (task/'stat').write_text(stat_text(999,flags=0))
        (self.cg/'cgroup.procs').write_text('999')
        self.assertFalse(iso.effective_verify(data,self.cg,self.proc,lambda pid:{7})['verified'])
        self.assertTrue(iso.effective_verify(data,self.cg,self.proc,lambda pid:{0})['verified'])
        (task/'stat').write_text(stat_text(999,flags=0x200000))
        self.assertTrue(iso.effective_verify(data,self.cg,self.proc,lambda pid:{7})['verified'])
        (self.cg/'cgroup.procs').write_text('0')
        self.assertFalse(iso.effective_verify(data,self.cg,self.proc)['verified'])

    def test_interrupted_restore_retains_unrelated_administrator_changes(self):
        data=iso.plan(self.state()); iso.apply(data,self.backend,self.path)
        entry=data['changes'][0]; entry['phase']='restore_intent'
        self.backend.files[entry['unit']]['administrator.conf']='unrelated'
        result=iso.restore(data,self.backend)
        self.assertFalse(result['verified'])
        self.assertEqual(self.backend.files[entry['unit']]['administrator.conf'],'unrelated')

    def test_proxy_peer_timeout_is_not_success(self):
        class Sock:
            def settimeout(self, seconds): pass
            def sendmsg(self,*args): pass
            def recv(self,count): raise TimeoutError('supervisor heartbeat lost')
        with patch.object(iso.os,'geteuid',return_value=1001),patch.object(iso.os,'dup',return_value=99),patch.object(iso.socket,'socket',return_value=Sock()):
            with self.assertRaises(TimeoutError): iso.proxy(['/bin/true'],3)

    def test_monitor_unexpected_exit_cancels_harmless_child(self):
        import benchmark_session as session
        original=monitor.Monitor.sample
        count=[0]
        def sample(observer,*args):
            count[0]+=1
            if count[0]>1: raise SystemExit('fixture thread exit')
            return original(observer,*args)
        with tempfile.TemporaryDirectory() as tmp, patch.object(session,'SESSIONS',Path(tmp)),patch.object(common,'capture',return_value={}),patch.object(monitor.Monitor,'sample',sample),contextlib.redirect_stdout(io.StringIO()):
            code=session.main(['--telemetry-interval','0.2','--',sys.executable,'-c','import time;time.sleep(5)'])
            self.assertNotEqual(code,0)
            directory=next(p for p in Path(tmp).iterdir() if p.is_dir())
            result=json.loads((directory/'session.json').read_text())
            self.assertIn('Monitor exited unexpectedly', ' '.join(result['monitor_failed']))


if __name__ == '__main__':
    unittest.main()
