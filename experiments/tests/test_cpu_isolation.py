"""Non-invasive CPU isolation/monitoring tests: fixtures, mocks and harmless Python only."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0,str(TOOLS))
import isolation_manager as iso
import interference_monitor as mon
import benchmark_session as session


class Backend:
    def __init__(self,root):
        self.root=root
        self.values={name:{'AllowedCPUs':'','EffectiveCPUs':'0-15','LoadState':'loaded','ControlGroup':'/'+name}
                     for name in ('init.scope','system.slice','user.slice')}
        self.files={name:{} for name in self.values}
        self.calls=[]
        self.fail=None
    def show(self,unit): return dict(self.values.get(unit,{'LoadState':'not-found'}))
    def provenance(self,unit): return dict(self.files[unit])
    def set(self,unit,value):
        if self.fail==unit: raise ValueError('simulated systemd failure')
        self.calls.append((unit,value))
        self.values[unit]['AllowedCPUs']=value
        self.values[unit]['EffectiveCPUs']=value or '0-15'
        self.files[unit]={'runtime-AllowedCPUs.conf':value}
        (self.root/unit/'cpuset.cpus.effective').write_text(value or '0-15')


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name); self.cg=self.base/'cg'; self.cg.mkdir()
        self.proc=self.base/'proc'; self.proc.mkdir()
        self.cpu=self.base/'cpu'; (self.cpu/'cpu7/topology').mkdir(parents=True)
        (self.cpu/'online').write_text('0-15')
        for n in (7,15):
            node=self.cpu/f'cpu{n}/topology'; node.mkdir(parents=True,exist_ok=True)
            (node/'thread_siblings_list').write_text('7,15')
            (node/'core_id').write_text('7'); (node/'physical_package_id').write_text('0')
        for name,value in {'cgroup.controllers':'cpuset cpu memory','cgroup.subtree_control':'memory',
                           'cpuset.cpus.effective':'0-15','cgroup.procs':''}.items(): (self.cg/name).write_text(value)
        self.backend=Backend(self.cg)
        for name in self.backend.values:
            (self.cg/name).mkdir(); (self.cg/name/'cpuset.cpus.effective').write_text('0-15')
        self.path=self.base/'journal.json'
    def state(self): return iso.inspect(self.backend,self.cg,self.cpu,self.proc)
    def test_collected_unit_missing_is_not_a_stop_failure(self):
        backend=iso.Systemd()
        with patch.object(backend,'run',return_value=subprocess.CompletedProcess([],1,'LoadState=not-found\nActiveState=inactive\n','')):
            self.assertEqual(backend.show('grngfixture.service')['LoadState'],'not-found')

    def test_worker_checks_effective_cpuset_before_exec(self):
        unit='grngfixture.service'; group='/grngfixture.slice/'+unit
        path=self.cg/group.lstrip('/'); path.mkdir(parents=True)
        (path/'cpuset.cpus.effective').write_text('7')
        original=Path.read_text
        def reader(p,*args,**kwargs):
            if str(p)=='/proc/self/cgroup': return '0::'+group
            return original(p,*args,**kwargs)
        with patch.object(iso,'CGROUP',self.cg),patch.object(Path,'read_text',reader),patch.object(iso.os,'geteuid',return_value=1001),patch.object(iso.os,'sched_getaffinity',return_value={7}),patch.object(iso.os,'execv') as execute:
            iso.worker(['/bin/true'],7,self.base/'placement.json',unit)
            self.assertEqual(execute.call_args.args[1][-1],'/bin/true')
            self.assertTrue(json.loads((self.base/'placement.json').read_text())['verified'])
            (path/'cpuset.cpus.effective').write_text('7,15')
            with self.assertRaises(ValueError): iso.worker(['/bin/true'],7,self.base/'never.json',unit)
            self.assertFalse((self.base/'never.json').exists())
            (path/'cpuset.cpus.effective').write_text('7')
            pending=self.base/'preexisting.tmp'; pending.write_text('preserve existing data')
            with self.assertRaises(FileExistsError): iso.worker(['/bin/true'],7,self.base/'preexisting.json',unit)
            self.assertEqual(pending.read_text(),'preserve existing data')

    def test_topology_cgroup_and_safe_plan(self):
        plan=iso.plan(self.state())
        self.assertFalse(plan['errors'])
        self.assertEqual(plan['reserved'],[7,15])
        self.assertEqual(set(plan['housekeeping']),set(range(16))-{7,15})
        self.assertEqual(plan['frequency_writes'],[])
        self.assertFalse(self.backend.calls)
    def test_explicit_reserved_only_affinity_blocks_plan(self):
        state=self.state(); state['task_affinities']['tasks']=[{'tid':42,'cgroup':'/user.slice/foo','affinity':[7]}]
        self.assertTrue(any('affinity' in e for e in iso.plan(state)['errors']))

    def test_topology_mismatch_and_missing_controller(self):
        (self.cpu/'cpu7/topology/thread_siblings_list').write_text('6,14')
        (self.cg/'cgroup.controllers').write_text('cpu memory')
        self.assertGreaterEqual(len(iso.plan(self.state())['errors']),2)
    def test_affinity_snapshot_audit_and_tid_reuse(self):
        process=self.proc/'99999'; thread=process/'task/99999'; thread.mkdir(parents=True)
        (process/'cgroup').write_text('0::/user.slice/example.scope')
        fields=['S']+['0']*45; fields[19]='123'; fields[6]='0'
        (thread/'stat').write_text('99999 (fixture) '+' '.join(fields))
        snapshot=iso.affinity_snapshot(self.proc,lambda tid:{0,1,7})
        self.assertEqual(len(snapshot['tasks']),1)
        self.assertTrue(iso.audit_affinities(snapshot,self.proc,lambda tid:{0,1,7})['verified'])
        self.assertFalse(iso.audit_affinities(snapshot,self.proc,lambda tid:{0,1})['verified'])
        fields[19]='124'; (thread/'stat').write_text('99999 (reused) '+' '.join(fields))
        self.assertTrue(iso.audit_affinities(snapshot,self.proc,lambda tid:{0})['verified'])

    def test_namespace_hidden_root_tasks_block(self):
        (self.cg/'cgroup.procs').write_text('0\n')
        self.assertTrue(any('hidden' in e for e in iso.plan(self.state())['errors']))
    def test_never_starve_restricted_services(self):
        self.backend.values['init.scope']['EffectiveCPUs']='7'
        (self.cg/'init.scope/cpuset.cpus.effective').write_text('7')
        self.assertTrue(any('empty' in e for e in iso.plan(self.state())['errors']))
    def test_apply_verify_restore_and_repeat_recovery(self):
        data=iso.plan(self.state()); iso.durable(self.path,data)
        iso.apply(data,self.backend,self.path)
        self.assertTrue(iso.effective_verify(data,self.cg)['verified'])
        result=iso.restore(data,self.backend,lambda:iso.durable(self.path,data))
        self.assertTrue(result['verified'],result)
        self.assertTrue(iso.restore(json.loads(self.path.read_text()),self.backend)['verified'])
        self.assertTrue(all(info['AllowedCPUs']=='' for info in self.backend.values.values()))
    def test_partial_failure_recovery_does_not_guess_ambiguous_apply(self):
        data=iso.plan(self.state()); self.backend.fail='system.slice'
        with self.assertRaises(ValueError): iso.apply(data,self.backend,self.path)
        self.backend.fail=None
        data=json.loads(self.path.read_text())
        result=iso.restore(data,self.backend,lambda:iso.durable(self.path,data))
        self.assertFalse(result['verified'],result)
        iso.acknowledge_original_intents(data,self.backend)
        self.assertTrue(iso.restore(data,self.backend)['verified'])
    def test_admin_conflict_is_not_overwritten(self):
        data=iso.plan(self.state()); iso.apply(data,self.backend,self.path)
        self.backend.files['system.slice']['unrelated-admin.conf']='new'
        result=iso.restore(data,self.backend)
        self.assertFalse(result['verified'])
        self.assertIn('unrelated-admin.conf',self.backend.files['system.slice'])
        self.assertNotEqual(self.backend.values['system.slice']['AllowedCPUs'],'')
    def test_effective_constraints_and_new_root_cgroup(self):
        data=iso.plan(self.state()); iso.apply(data,self.backend,self.path)
        (self.cg/'user.slice/cpuset.cpus.effective').write_text('0-15')
        (self.cg/'unexpected.slice').mkdir()
        result=iso.effective_verify(data,self.cg)
        self.assertFalse(result['verified']); self.assertEqual(len(result['errors']),2)
    def test_manual_ack_does_not_overwrite_nonoriginal_state(self):
        data=iso.plan(self.state()); change=data['changes'][0]; change['phase']='intent'
        self.backend.set(change['unit'],change['target'])
        with self.assertRaises(ValueError): iso.acknowledge_original_intents(data,self.backend)
        self.assertEqual(self.backend.values[change['unit']]['AllowedCPUs'],change['target'])

    def test_ambiguous_restore_conflict(self):
        data=iso.plan(self.state()); iso.apply(data,self.backend,self.path)
        data['changes'][0]['expected_provenance']=None
        self.assertFalse(iso.restore(data,self.backend)['verified'])
    def test_boot_identity_blocks_stale_replay(self):
        self.assertFalse(iso.boot_matches({'boot_id':'different-boot'}))
        self.assertTrue(iso.boot_matches({'boot_id':iso.read(Path('/proc/sys/kernel/random/boot_id'))}))

    def test_cancel_preserves_changed_unit_identity(self):
        data={'id':'fixture','owned_units':['grngfixture.slice','grngfixture.service']}
        self.backend.values['grngfixture.service']={'LoadState':'loaded','Description':'unrelated administrator work'}
        with patch.object(self.backend,'stop',create=True) as stop:
            with self.assertRaises(ValueError): iso.stop_benchmark(data,self.backend)
            stop.assert_not_called()

    def test_monitor_cancel_is_scoped_broker_message(self):
        server,client=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        try:
            server.settimeout(1)
            iso.cancel_request(client.fileno())
            self.assertEqual(json.loads(server.recv(4096)),{'cancel':True})
        finally: server.close(); client.close()

    def test_broker_argument_array_and_descriptor_transfer(self):
        server,client=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        self.addCleanup(server.close); self.addCleanup(client.close)
        import array
        server.settimeout(1); client.settimeout(1)
        client.sendmsg([json.dumps({'command':['echo','literal;not-shell']}).encode()],
                       [(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[1,2]))])
        value,fds=iso.recv_request(server)
        try:
            self.assertEqual(value['command'][1],'literal;not-shell'); self.assertEqual(len(fds),2)
        finally:
            for fd in fds: os.close(fd)


class AffinityRestorationTests(unittest.TestCase):
    def setUp(self):
        IsolationTests.setUp(self)
        self.affinities={}; self.setter_calls=[]
        original_set=self.backend.set
        def set_property(unit,value):
            original_set(unit,value)
            for tid in self.affinities:
                path=self.proc/'99000'/'task'/str(tid)/'stat'
                if path.exists() and unit=='user.slice' and not int(path.read_text().rsplit(')',1)[1].split()[6])&0x200000:
                    self.affinities[tid]=iso.cpus(value or '0-15')
        self.backend.set=set_property

    def task(self,tid=99001,original=(0,),kernel=False):
        process=self.proc/'99000'; thread=process/'task'/str(tid)
        thread.mkdir(parents=True,exist_ok=True)
        fields=['S']+['0']*45; fields[19]='100'; fields[6]='0'
        (process/'stat').write_text('99000 (leader) '+' '.join(fields))
        (process/'cgroup').write_text('0::/user.slice')
        fields[19]=str(tid); fields[6]=str(0x200000 if kernel else 0)
        (thread/'stat').write_text(f'{tid} (worker) '+' '.join(fields))
        self.affinities[tid]=set(original)
        return thread/'stat'

    def getter(self,tid): return set(self.affinities[tid])

    def setter(self,tid,value):
        self.assertEqual(self.backend.values['user.slice']['AllowedCPUs'],'')
        saved=json.loads(self.path.read_text())['task_affinity_restoration']['entries'].values()
        self.assertTrue(any(e['task']['tid']==tid and e['state']=='intent' for e in saved))
        self.setter_calls.append((tid,set(value))); self.affinities[tid]=set(value)

    def prepare(self):
        data=iso.plan(iso.inspect(self.backend,self.cg,self.cpu,self.proc))
        data['state']['task_affinities']=iso.affinity_snapshot(self.proc,self.getter)
        iso.apply(data,self.backend,self.path)
        return data

    def restore(self,data,**kwargs):
        return iso.restore_cpu_state(data,self.backend,lambda:iso.durable(self.path,data),
                                     self.proc,self.cg,kwargs.get('getter',self.getter),kwargs.get('setter',self.setter))

    def test_narrow_thread_affinity_is_restored_after_constraints(self):
        self.task(); data=self.prepare()
        self.assertEqual(self.affinities[99001],set(range(16))-{7,15})
        result=self.restore(data)
        self.assertTrue(result['verified'],result)
        self.assertEqual(self.setter_calls,[(99001,{0})])
        self.assertEqual(self.affinities[99001],{0})
        self.assertEqual(len(result['affinity_restoration']['successful']),1)
        self.assertTrue(result['affinity_audit']['verified'])
        self.assertTrue(all(v['AllowedCPUs']=='' for v in self.backend.values.values()))
        self.assertTrue(self.restore(data)['verified'])
        self.assertEqual(len(self.setter_calls),1)

    def test_exited_thread_is_skipped(self):
        path=self.task(); data=self.prepare(); path.unlink()
        result=self.restore(data)
        self.assertTrue(result['verified'],result)
        self.assertFalse(self.setter_calls)
        self.assertEqual(result['affinity_restoration']['skipped'][0]['reason'],'exited')

    def test_reused_tid_is_not_modified(self):
        path=self.task(); data=self.prepare()
        fields=path.read_text().rsplit(')',1)[1].split(); fields[19]='200'
        path.write_text('99001 (reused) '+' '.join(fields))
        result=self.restore(data)
        self.assertTrue(result['verified'],result)
        self.assertFalse(self.setter_calls)
        self.assertEqual(result['affinity_restoration']['skipped'][0]['reason'],'reused_identity')

    def test_reused_process_identity_is_not_modified(self):
        self.task(); data=self.prepare(); path=self.proc/'99000/stat'
        path.write_text(path.read_text().replace('100','101'))
        result=self.restore(data)
        self.assertTrue(result['verified'],result)
        self.assertFalse(self.setter_calls)

    def test_kernel_thread_is_never_modified(self):
        self.task(original=(7,),kernel=True); data=self.prepare()
        self.assertFalse(data['state']['task_affinities']['tasks'])
        result=self.restore(data)
        self.assertTrue(result['verified'],result)
        self.assertFalse(self.setter_calls)
        self.assertEqual(self.affinities[99001],{7})
        self.assertEqual(result['affinity_restoration']['skipped'][0]['reason'],'kernel_thread')

    def test_admin_affinity_conflict_preserves_mask_and_parent_constraint(self):
        self.task(); data=self.prepare(); self.affinities[99001]={2}
        result=self.restore(data)
        self.assertFalse(result['verified'])
        self.assertFalse(self.setter_calls)
        self.assertEqual(self.affinities[99001],{2})
        self.assertNotEqual(self.backend.values['user.slice']['AllowedCPUs'],'')
        self.assertEqual(len(result['affinity_restoration']['conflicting']),1)
        self.assertEqual(self.backend.values['system.slice']['AllowedCPUs'],'')

    def test_no_cpuset_mutation_does_not_justify_overwriting_admin_mask(self):
        self.task()
        data=iso.plan(iso.inspect(self.backend,self.cg,self.cpu,self.proc))
        data['state']['task_affinities']=iso.affinity_snapshot(self.proc,self.getter)
        self.affinities[99001]=set(range(16))
        result=self.restore(data)
        self.assertFalse(result['verified'])
        self.assertFalse(self.setter_calls)
        self.assertFalse(self.backend.calls)
        self.assertEqual(self.affinities[99001],set(range(16)))

    def test_partial_task_failure_does_not_prevent_other_task_restoration(self):
        self.task(); self.task(99002,(1,)); data=self.prepare()
        def setter(tid,mask):
            if tid==99001: raise PermissionError('fixture affinity permission denied')
            self.setter(tid,mask)
        result=self.restore(data,setter=setter)
        self.assertFalse(result['verified'])
        self.assertEqual(self.affinities[99002],{1})
        self.assertEqual(len(result['affinity_restoration']['failed']),1)
        self.assertEqual(len(result['affinity_restoration']['successful']),1)
        self.assertEqual(len(result['affinity_restoration']['attempted']),2)

    def test_wrong_final_affinity_fails_readback_verification(self):
        self.task(); data=self.prepare()
        result=self.restore(data,setter=lambda tid,mask:None)
        self.assertFalse(result['verified'])
        self.assertIn('readback mismatch',result['affinity_restoration']['failed'][0]['reason'])

    def test_inaccessible_task_is_failed_and_not_modified(self):
        self.task(); data=self.prepare()
        def denied(tid): raise PermissionError('inaccessible fixture task')
        result=self.restore(data,getter=denied)
        self.assertFalse(result['verified'])
        self.assertFalse(self.setter_calls)
        self.assertIn('inaccessible',result['affinity_restoration']['failed'][0]['reason'])

    def test_admin_change_between_intent_and_task_write_is_not_overwritten(self):
        self.task(); data=self.prepare()
        def checkpoint():
            iso.durable(self.path,data)
            if any(e['state']=='intent' for e in data.get('task_affinity_restoration',{}).get('entries',{}).values()):
                self.affinities[99001]={3}
        result=iso.restore_cpu_state(data,self.backend,checkpoint,self.proc,self.cg,self.getter,self.setter)
        self.assertFalse(result['verified'])
        self.assertFalse(self.setter_calls)
        self.assertEqual(self.affinities[99001],{3})

    def test_crash_after_affinity_write_is_idempotently_recovered(self):
        self.task(); data=self.prepare()
        def crash(tid,mask):
            self.setter(tid,mask)
            raise RuntimeError('fixture crash after setter')
        with self.assertRaisesRegex(RuntimeError,'crash after setter'):
            self.restore(data,setter=crash)
        self.assertEqual(self.affinities[99001],{0})
        recovered=json.loads(self.path.read_text())
        self.assertTrue(self.restore(recovered)['verified'])
        self.assertEqual(len(self.setter_calls),1)

    def test_exit_during_affinity_attempt_is_recorded(self):
        path=self.task(); data=self.prepare()
        def exited(tid,mask):
            path.unlink(); raise ProcessLookupError('fixture exit')
        result=self.restore(data,setter=exited)
        self.assertTrue(result['verified'],result)
        entry=result['affinity_restoration']['skipped'][0]
        self.assertEqual(entry['attempts'][-1]['outcome'],'exited')

    def test_snapshot_identity_race_reports_incomplete_capture(self):
        path=self.task()
        def reused(tid):
            fields=path.read_text().rsplit(')',1)[1].split(); fields[19]='200'
            path.write_text('99001 (reused) '+' '.join(fields))
            return {0}
        snapshot=iso.affinity_snapshot(self.proc,reused)
        self.assertFalse(snapshot['tasks'])
        self.assertTrue(snapshot['errors'])

    def test_legacy_journal_does_not_guess_nonoriginal_affinity(self):
        self.task(); data=self.prepare(); data.pop('affinity_restore_version')
        result=self.restore(data)
        self.assertFalse(result['verified'])
        self.assertFalse(self.setter_calls)
        self.assertTrue(result['affinity_restoration']['conflicting'])

    def test_parent_configuration_conflict_blocks_task_write(self):
        self.task(); data=self.prepare()
        self.backend.files['user.slice']['admin.conf']='changed'
        result=self.restore(data)
        self.assertFalse(result['verified'])
        self.assertFalse(self.setter_calls)
        self.assertEqual(result['affinity_restoration']['failed'][0]['state'],'blocked')

    def test_interrupted_task_intent_is_resumed_by_orphan_recovery_cli(self):
        import argparse,pwd
        from types import SimpleNamespace
        self.task(); data=self.prepare()
        ident='12345678-1234-5678-1234-567812345678'
        state=self.base/'state'; state.mkdir()
        sessions=self.base/'sessions'; sessions.mkdir(); (sessions/'.controller.lock').touch()
        data.update(id=ident,owned_units=[],boot_id=iso.read(Path('/proc/sys/kernel/random/boot_id')),
                    user=pwd.getpwuid(os.getuid()).pw_name,session_root=str(sessions),controller_pid=None)
        self.path=state/(ident+'.json')
        crashed=[False]
        def checkpoint():
            iso.durable(self.path,data)
            if not crashed[0] and any(e['state']=='intent' for e in data.get('task_affinity_restoration',{}).get('entries',{}).values()):
                crashed[0]=True; raise RuntimeError('fixture supervisor crash before affinity write')
        with self.assertRaisesRegex(RuntimeError,'fixture supervisor crash'):
            iso.restore_cpu_state(data,self.backend,checkpoint,self.proc,self.cg,self.getter,self.setter)
        self.assertEqual(self.affinities[99001],set(range(16)))
        restore=iso.restore_cpu_state
        def recover(saved,backend,save):
            return restore(saved,backend,save,self.proc,self.cg,self.getter,self.setter)
        with patch.object(iso,'STATE',state),patch.object(iso,'Systemd',return_value=self.backend),patch.object(iso,'trusted'),patch.object(iso.os,'geteuid',return_value=0),patch.object(iso.sys,'flags',SimpleNamespace(isolated=1)),patch.object(iso.sys,'argv',['isolation_manager.py','recover','--approve-isolation','--journal',ident]),patch.object(iso,'restore_cpu_state',side_effect=recover) as call,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(iso.main(),0)
            call.assert_called_once()
        saved=json.loads(self.path.read_text())
        self.assertEqual(saved['status'],'restored')
        self.assertTrue(saved['restoration']['verified'])
        self.assertEqual(self.affinities[99001],{0})


class MonitoringTests(unittest.TestCase):
    def test_proc_stat_serialization_and_deltas(self):
        fields=['S']+['0']*49
        fields[11]='10'; fields[12]='2'; fields[19]='100'; fields[36]='7'
        info=mon.task_stat('42 (task with ) name) '+' '.join(fields))
        self.assertEqual(info['cpu'],7); self.assertEqual(info['ticks'],12)
        a={'cpus':{'cpu7':{'total':100,'idle':40}},'interrupts':{'7':10},'softirqs':{'7':2},'ctxt':10}
        b={'cpus':{'cpu7':{'total':200,'idle':60}},'interrupts':{'7':12},'softirqs':{'7':3},'ctxt':15}
        self.assertEqual(mon.deltas(a,b)['utilization']['cpu7'],80)
        self.assertEqual(mon.deltas(a,b)['interrupts']['7'],2)
    def test_shared_policy_and_labelled_temperatures(self):
        state={'policies':{'policy0':{'related_cpus':'0-15','scaling_cur_freq':'3200000'}},
               'thermal':{'sensor':{'name':'k10temp','temp2_label':'Tdie','temp2_input':'42500','temp1_label':'Tctl','temp1_input':'52500'}}}
        self.assertEqual(mon.reported_frequency(state),3200000)
        self.assertEqual(mon.cpu_temperatures(state),{'Tdie':42.5,'Tctl':52.5})
        self.assertEqual(mon.quality({'tdie_max_c':90},{'max_tdie_c':85})['classification'],'WARNING')

    def test_periodic_clean_snapshots_cannot_pass(self):
        report=mon.quality({'isolation_verified':True,'proc_visibility_complete':True})
        self.assertEqual(report['classification'],'UNVERIFIED')
    def test_quality_all_classes_and_thresholds(self):
        facts={'isolation_verified':True,'proc_visibility_complete':True,
               'trace_coverage_complete':True,'trace_loss_verified_zero':True}
        self.assertEqual(mon.quality(facts)['classification'],'PASS')
        self.assertEqual(mon.quality(dict(facts,competing_ns=100))['classification'],'FAIL')
        self.assertEqual(mon.quality(dict(facts,irq_delta=1))['classification'],'WARNING')
        self.assertEqual(mon.quality(dict(facts,competing_ns=100),{'max_competing_ns':101})['classification'],'PASS')
        self.assertEqual(mon.quality(dict(facts,monitor_errors=['lost']))['classification'],'FAIL')
    def test_scheduler_intervals_and_loss(self):
        parser=mon.TraceParser()
        parser.feed('idle-0 [007] d..2 1.000000: sched_switch: prev_comm=idle prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=other next_pid=99 next_prio=120')
        parser.feed('other-99 [007] d..2 1.010000: sched_switch: prev_comm=other prev_pid=99 prev_prio=120 prev_state=S ==> next_comm=bench next_pid=42 next_prio=120')
        parser.feed('bench-42 [007] d..2 1.020000: sched_switch: prev_comm=bench prev_pid=42 prev_prio=120 prev_state=S ==> next_comm=idle next_pid=0 next_prio=120')
        result=parser.assess({42},1000000000,1020000000)
        self.assertEqual(result['competing_intervals'][0]['duration_ns'],10000000)
        uncertain=parser.assess({42},1000000000,1020000000,confirmed_foreign=set())
        self.assertEqual(uncertain['competing_intervals'],[])
        self.assertEqual(uncertain['unclassified_intervals'][0]['duration_ns'],10000000)
        parser.feed('CPU:7 [LOST 3 EVENTS]')
        self.assertEqual(parser.lost_records,1)
        self.assertFalse(result['coverage_complete']) # no CPU15 coverage
    def test_diagnostic_missing_counters_stays_unverified(self):
        facts={'isolation_verified':True,'proc_visibility_complete':True,'trace_coverage_complete':True,
               'trace':{'parse_errors':0,'lost_record_markers':0},'read_budget_exhaustions_or_partial_records':0}
        report={'facts':facts,'thresholds':{}}
        final=mon.final_quality(report,{'restoration':{'verified':True}})
        self.assertEqual(final['classification'],'UNVERIFIED')
    def test_monitor_ready_affinity_and_serialization_before_workload(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            observer=mon.Monitor(directory,'fixture',set(range(16))-{7,15},interval=.2)
            observer.start()
            self.assertTrue(observer.ready.is_set())
            self.assertTrue(set(observer.monitor_affinity).isdisjoint({7,15}))
            report=observer.stop(0)
            self.assertEqual(report['facts']['exit_status'],0)
            self.assertTrue((directory/'environment_samples.csv').read_text().startswith('monotonic_ns,'))
            self.assertNotEqual(report['classification'],'PASS')
    def test_monitor_start_failure_prevents_workload(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(session,'SESSIONS',Path(temporary)),patch.object(session.common,'capture',return_value={}),patch.object(mon.Monitor,'start',side_effect=RuntimeError('monitor failed')),patch.object(session.subprocess,'Popen') as launch,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(session.main(['--','/bin/true']),125)
            launch.assert_not_called()
            directory=next(p for p in Path(temporary).iterdir() if p.is_dir())
            self.assertEqual(json.loads((directory/'benchmark_quality.json').read_text())['classification'],'FAIL')

    def test_monitor_crash_terminates_harmless_workload(self):
        original=mon.Monitor.sample
        calls=[]
        def crash(self,*args):
            calls.append(1)
            if len(calls)>1: raise OSError('fixture monitor crash')
            return original(self,*args)
        with tempfile.TemporaryDirectory() as temporary,patch.object(session,'SESSIONS',Path(temporary)),patch.object(session.common,'capture',return_value={}),patch.object(mon.Monitor,'sample',crash),contextlib.redirect_stdout(io.StringIO()):
            result=session.main(['--telemetry-interval','.2','--',sys.executable,'-c','import time;time.sleep(20)'])
            self.assertNotEqual(result,0)
            directory=next(p for p in Path(temporary).iterdir() if p.is_dir())
            self.assertEqual(json.loads((directory/'benchmark_quality.json').read_text())['classification'],'FAIL')

    def test_session_waits_for_monitor_and_harmless_child(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(session,'SESSIONS',Path(temporary)),patch.object(session.common,'capture',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            result=session.main(['--mode','bios','--monitor-mode','lightweight','--',sys.executable,'-c','import os;print(sorted(os.sched_getaffinity(0)))'])
            self.assertEqual(result,0)
            directory=next(p for p in Path(temporary).iterdir() if p.is_dir())
            self.assertEqual((directory/'stdout.txt').read_text().strip(),'[7]')
            self.assertTrue((directory/'benchmark_quality.json').is_file())
            self.assertEqual(json.loads((directory/'isolation_status.json').read_text())['status'],'not_activated')
            before=json.loads((directory/'environment_samples.csv').read_text().splitlines()[1].split(',"',1)[0].split(',')[0])
            self.assertGreater(before,0)





class ActivationFixtureTests(unittest.TestCase):
    setUp=IsolationTests.setUp
    state=IsolationTests.state
    # Reuse only fixture construction, not inherited test methods below.
    def test_approved_supervisor_mock_cycle(self):
        import argparse,pwd
        state_dir=self.base/'state'; state_dir.mkdir()
        # Regression: on the first activation the root supervisor runs before
        # benchmark_session, so no process has created this coordination file.
        sessions=self.base/'sessions'; sessions.mkdir()
        backend=self.backend
        def run(args,check=True):
            if args[0]=='start':
                unit=args[1]; backend.values[unit]={'AllowedCPUs':'','EffectiveCPUs':'0-15'}
                backend.files[unit]={}; (self.cg/unit).mkdir(); (self.cg/unit/'cpuset.cpus.effective').write_text('0-15')
            return subprocess.CompletedProcess([],0,'','')
        def stop(unit):
            if unit in backend.values and unit.startswith('grng'):
                (self.cg/unit/'cpuset.cpus.effective').unlink(); (self.cg/unit).rmdir()
                backend.values.pop(unit); backend.files.pop(unit)
        backend.run=run; backend.stop=stop
        class Process:
            pid=99999999
            def poll(self): return 5
            def wait(self,timeout=None): return 5
        state=self.state()
        original_verify=iso.effective_verify
        args=argparse.Namespace(user=pwd.getpwuid(os.getuid()).pw_name,command=['/bin/false'],session_root=sessions,
                                controller=TOOLS/'benchmark_session.py',python=sys.executable,
                                monitor_mode='lightweight',approve_scheduler_tracing=False,interval=1,quality_thresholds=None)
        with patch.object(iso,'STATE',state_dir),patch.object(iso,'inspect',return_value=state),patch.object(iso,'effective_verify',side_effect=lambda data:original_verify(data,self.cg)),patch.object(iso,'pid_start',return_value='fixture'),patch.object(iso.os,'sched_setaffinity'),patch.object(iso.subprocess,'Popen',return_value=Process()) as launch,patch.object(iso,'report_as_user',return_value={'delivered':True}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(iso.activate(args,backend),5)
        self.assertIn('--mode',launch.call_args.args[0])
        self.assertIn('bios',launch.call_args.args[0])
        lock=sessions/'.controller.lock'
        self.assertTrue(lock.is_file())
        self.assertEqual(lock.stat().st_uid,os.getuid())
        journal=json.loads(next(state_dir.glob('*.json')).read_text())
        self.assertTrue(journal['restoration']['verified'],journal['restoration'])
        self.assertTrue(all(info['AllowedCPUs']=='' for info in backend.values.values()))


if __name__=='__main__': unittest.main()
