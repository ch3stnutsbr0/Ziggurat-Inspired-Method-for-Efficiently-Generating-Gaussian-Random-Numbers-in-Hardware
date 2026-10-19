"""Read-only environmental observations. /proc fallback NEVER certifies no interference."""
import csv
import json
import os
from pathlib import Path
import re
import threading
import time

import cpu_benchmark as common


def cpus(text):
    result = set()
    for item in str(text).replace(' ', ',').split(','):
        if item:
            pair = item.split('-')
            result.update(range(int(pair[0]), int(pair[-1]) + 1))
    return result


def task_stat(text):
    end = text.rindex(')')
    fields = text[end + 2:].split()
    return {'name': text[text.index('(')+1:end], 'state': fields[0],
            'ticks': int(fields[11]) + int(fields[12]), 'cpu': int(fields[36]),
            'start_ticks': int(fields[19])}


def proc_snapshot(root=Path('/proc')):
    tasks, errors, races = {}, [], 0
    for process in root.glob('[0-9]*'):
        try:
            for tid in (process / 'task').iterdir():
                try:
                    value = task_stat((tid / 'stat').read_text())
                    value.update(pid=int(process.name), tid=int(tid.name))
                    tasks[(value['tid'], value['start_ticks'])] = value
                except FileNotFoundError:
                    races += 1
                except (OSError, ValueError, IndexError) as exc:
                    errors.append(f'{tid}: {exc}')
        except FileNotFoundError:
            races += 1
        except OSError as exc:
            errors.append(f'{process}: {exc}')
    return tasks, errors, races


def cpu_counters(proc=Path('/proc')):
    data = {'cpus': {}, 'ctxt': None, 'interrupts': {}, 'softirqs': {}}
    for line in (proc / 'stat').read_text().splitlines():
        parts = line.split()
        if parts[0] in ('cpu7', 'cpu15'):
            values = list(map(int, parts[1:]))
            data['cpus'][parts[0]] = {'total': sum(values[:8]), 'idle': values[3] + values[4]}
        elif parts[0] == 'ctxt':
            data['ctxt'] = int(parts[1])
    for filename in ('interrupts', 'softirqs'):
        lines = (proc / filename).read_text().splitlines()
        if not lines:
            raise ValueError(f'/proc/{filename} is empty/unavailable')
        header = lines[0].split()
        indices = {cpu: header.index(f'CPU{cpu}') for cpu in (7, 15)}
        totals = {str(cpu): 0 for cpu in indices}
        for line in lines[1:]:
            if ':' not in line:
                continue
            parts = line.split(':', 1)[1].split()
            for cpu, index in indices.items():
                if len(parts) > index and parts[index].isdecimal():
                    totals[str(cpu)] += int(parts[index])
        data[filename] = totals
    return data



def reported_frequency(state, cpu=7):
    for policy in state['policies'].values():
        try:
            value=policy.get('scaling_cur_freq')
            if cpu in cpus(policy.get('related_cpus','')) and isinstance(value,str) and value.isdecimal():
                return int(value)
        except (ValueError,TypeError): pass
    return None


def cpu_temperatures(state):
    values={}
    for sensor in state['thermal'].values():
        if sensor.get('name')!='k10temp': continue
        for key,label in sensor.items():
            if key.endswith('_label') and label in ('Tdie','Tctl'):
                raw=sensor.get(key.replace('_label','_input'))
                if isinstance(raw,str) and raw.lstrip('-').isdecimal(): values[label]=int(raw)/1000
    return values

def deltas(old, new):
    result = {'utilization': {}, 'interrupts': {}, 'softirqs': {}, 'context_switches_global': None}
    if old is None:
        return result
    for cpu, current in new['cpus'].items():
        previous = old['cpus'][cpu]
        total, idle = current['total']-previous['total'], current['idle']-previous['idle']
        result['utilization'][cpu] = 100*(total-idle)/total if total > 0 else None
    for kind in ('interrupts', 'softirqs'):
        result[kind] = {cpu: value-old[kind][cpu] for cpu, value in new[kind].items()}
    if old['ctxt'] is not None and new['ctxt'] is not None:
        result['context_switches_global'] = new['ctxt']-old['ctxt']
    return result


SWITCH = re.compile(r'\[(\d+)\].*?\s(\d+\.\d+):\s+sched_switch:\s+prev_comm=(.*?) prev_pid=(\d+).*?next_comm=(.*?) next_pid=(\d+)')
MIGRATE = re.compile(r'\[(\d+)\].*?\s(\d+\.\d+):\s+sched_migrate_task:.*?pid=(\d+).*?orig_cpu=(\d+) dest_cpu=(\d+)')


class TraceParser:
    def __init__(self):
        self.switches = {7: [], 15: []}
        self.migrations=[]
        self.errors = 0
        self.lost_records = 0

    def feed(self, line):
        if not line.strip() or line.startswith('#'):
            return None
        if 'LOST' in line or 'overrun' in line.lower():
            self.lost_records += 1
            return {'kind': 'trace_loss', 'text': line.strip()}
        match = SWITCH.search(line)
        if match:
            cpu, stamp, prev_name, prev, next_name, nxt = match.groups()
            value = {'kind': 'sched_switch', 'cpu': int(cpu), 'timestamp_ns': int(float(stamp)*1e9),
                     'prev_tid': int(prev), 'tid': int(nxt), 'prev_name': prev_name, 'name': next_name}
            if value['cpu'] in self.switches:
                if len(self.switches[value['cpu']])<100000:
                    self.switches[value['cpu']].append(value)
                else:
                    self.errors += 1
            return value
        match = MIGRATE.search(line)
        if match:
            cpu, stamp, tid, origin, destination = match.groups()
            event={'kind': 'sched_migrate_task', 'cpu': int(cpu), 'timestamp_ns': int(float(stamp)*1e9),
                    'tid': int(tid), 'origin': int(origin), 'destination': int(destination)}
            if len(self.migrations)<100000: self.migrations.append(event)
            else: self.errors+=1
            return event
        self.errors += 1
        return {'kind': 'unparsed_trace', 'text': line.strip()}

    def assess(self, allowed, begin_ns, end_ns, confirmed_foreign=None):
        intervals, unclassified, coverage = [], [], True
        for cpu, switches in self.switches.items():
            if not switches or switches[0]['timestamp_ns'] > begin_ns or switches[-1]['timestamp_ns'] < end_ns:
                coverage = False
            for first, second in zip(switches, switches[1:]):
                if first['tid'] != second['prev_tid']:
                    coverage = False
                start, end = max(begin_ns, first['timestamp_ns']), min(end_ns, second['timestamp_ns'])
                if end > start and first['tid'] != 0 and not (cpu == 7 and first['tid'] in allowed):
                    destination=intervals if cpu==15 or confirmed_foreign is None or first['tid'] in confirmed_foreign else unclassified
                    destination.append({'cpu': cpu, 'tid': first['tid'], 'name': first['name'],
                                        'start_ns': start, 'duration_ns': end-start})
        return {'coverage_complete': coverage, 'competing_intervals': intervals, 'unclassified_intervals':unclassified,
                'parse_errors': self.errors, 'lost_record_markers': self.lost_records}


def quality(facts, thresholds=None):
    limits = {'max_competing_ns': 0, 'max_irq_delta': 0, 'max_frequency_variation_pct': 5.0, 'max_tdie_c':None}
    limits.update(thresholds or {})
    failures, warnings, unknown = [], [], []
    if facts.get('monitor_errors') or facts.get('migration') or facts.get('isolation_failed'):
        failures.append('Monitor failure, placement drift or benchmark migration')
    if facts.get('competing_ns', 0) > limits['max_competing_ns']:
        failures.append('Traced competing execution exceeds threshold')
    if facts.get('sampled_competitors', 0):
        warnings.append('Periodic snapshots observed possible competing tasks (last CPU is not current execution proof)')
    if facts.get('irq_delta', 0) > limits['max_irq_delta']:
        warnings.append('Reserved-core interrupts exceed threshold')
    if limits.get('max_tdie_c') is not None and facts.get('tdie_max_c') is not None and facts['tdie_max_c']>limits['max_tdie_c']:
        warnings.append('CPU Tdie exceeded the configured observation threshold')
    if facts.get('policy_changes',0):
        warnings.append('Read-only CPU policy/boost observations changed during the session')
    if facts.get('frequency_variation_pct', 0) > limits['max_frequency_variation_pct']:
        warnings.append('Reported frequency variation exceeds threshold; effective clock is unverified')
    if facts.get('unclassified_execution_ns',0):
        unknown.append('Some traced CPU7 execution could not be attributed to the approved workload or a confirmed competitor')
    if not facts.get('isolation_verified'):
        unknown.append('Isolation preconditions are not verified')
    if not facts.get('trace_coverage_complete') or not facts.get('trace_loss_verified_zero'):
        unknown.append('Complete loss-free scheduler coverage is not established; snapshots cannot prove absence of interference')
    if facts.get('missed_sample_deadlines',0):
        unknown.append('Environmental sampling deadlines were missed')
    if not facts.get('proc_visibility_complete'):
        unknown.append('Task visibility is incomplete or unverified')
    classification = 'FAIL' if failures else 'WARNING' if warnings else 'UNVERIFIED' if unknown else 'PASS'
    scheduling = ('FAIL' if facts.get('competing_ns',0)>limits['max_competing_ns'] or facts.get('migration') else
                  'VERIFIED_WITHIN_THRESHOLDS' if facts.get('trace_coverage_complete') and facts.get('trace_loss_verified_zero') and facts.get('proc_visibility_complete') and facts.get('isolation_verified') and not facts.get('monitor_errors') and not facts.get('isolation_failed') and not facts.get('missed_sample_deadlines',0) and not facts.get('unclassified_execution_ns',0) else 'UNVERIFIED')
    return {'classification': classification, 'scheduling_interference': scheduling, 'failures': failures, 'warnings': warnings,
            'uncertainty': unknown, 'thresholds': limits, 'facts': facts,
            'scope': 'Environmental scheduling quality only; not RNG statistical accuracy or fixed-frequency attestation'}


class Monitor:
    def __init__(self, directory, ident, housekeeping, interval=1.0, mode='lightweight', trace_fd=None,
                 placement=None, verify_isolation=None, thresholds=None, telemetry_callback=None):
        self.directory, self.ident = Path(directory), ident
        self.housekeeping, self.interval, self.mode = set(housekeeping), interval, mode
        self.trace_fd = trace_fd
        self.placement = Path(placement) if placement else self.directory / 'placement.json'
        self.verify_isolation = verify_isolation
        self.thresholds = thresholds
        self.telemetry_callback=telemetry_callback
        self.ready, self.stop_event = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.errors, self.races, self.dropped, self.samples = [], 0, 0, 0
        self.observation_errors = []
        self.observation_error_count = 0
        self.allowed, self.last_tasks, self.last_counters = set(), {}, None
        self.allow_starts={}
        self.parser, self.trace_pending = TraceParser(), ''
        self.events = []
        self.frequencies, self.irq_delta = [], 0
        self.temperatures=[]
        self.observed_competitors, self.migration = 0, False
        self.isolation_verified, self.isolation_failed = False, False
        self.policy_initial, self.policy_last, self.policy_changes = None,None,0
        self.missed_deadlines = 0
        self.proc_complete = False  # No process snapshot can certify namespace visibility on its own.
        self.started_ns, self.ended_ns, self.overhead_ns = None, None, 0
        self.pid = None

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            self.errors.append('Monitor readiness timeout')
        if self.errors:
            raise RuntimeError('; '.join(self.errors))

    def event(self, writer, kind, **fields):
        value = {'monotonic_ns': time.monotonic_ns(), 'session_id': self.ident, 'kind': kind, **fields}
        writer.writerow({'monotonic_ns': value['monotonic_ns'], 'session_id': self.ident,
                         'kind': kind, 'details_json': json.dumps(value)})
        if len(self.events)<100000:
            self.events.append(value)
        else:
            self.dropped += 1

    def sample(self, environment, events):
        begin = time.monotonic_ns()
        try:
            if self.placement.exists():
                p = json.loads(self.placement.read_text())
                self.allowed.add(int(p['pid']))
                if 'start_ticks' in p: self.allow_starts[int(p['pid'])]=int(p['start_ticks'])
                group = Path('/sys/fs/cgroup')/p.get('cgroup','').lstrip('/')
                try:
                    self.allowed.update(map(int,(group/'cgroup.threads').read_text().split()))
                except OSError:
                    pass
            if self.pid:
                self.allowed.add(self.pid)
            tasks, errors, races = proc_snapshot()
            self.races += races
            self.proc_complete &= not errors
            self.observation_error_count+=len(errors)
            self.observation_errors.extend(errors[:max(0,100-len(self.observation_errors))])
            for key, task in tasks.items():
                if task['tid'] in self.allowed and task['tid'] in self.allow_starts and task['start_ticks']!=self.allow_starts[task['tid']]:
                    self.allowed.discard(task['tid'])  # Reused ID is not the original benchmark thread.
                if task['tid'] in self.allowed:
                    self.allow_starts.setdefault(task['tid'],task['start_ticks'])
                    if task['cpu'] != 7:
                        self.migration = True
                        self.event(events, 'benchmark_migration', **task)
                    continue
                if task['cpu'] not in (7, 15):
                    continue
                previous = self.last_tasks.get(key)
                ticks = task['ticks']-previous['ticks'] if previous else None
                if task['state'] == 'R' or (ticks is not None and ticks > 0):
                    self.observed_competitors += 1
                    self.event(events, 'possible_competitor_snapshot', **task, delta_ticks=ticks,
                               limitation='Last scheduled CPU; tick delta may include execution elsewhere')
            self.last_tasks = tasks
            counters = cpu_counters()
            change = deltas(self.last_counters, counters)
            self.last_counters = counters
            self.irq_delta += sum(max(0, v) for v in change['interrupts'].values())
            state = common.snapshot()
            if self.telemetry_callback:
                phase='after' if self.stop_event.is_set() else 'before' if self.samples==0 else 'running'
                self.telemetry_callback(phase,state)
            policy = {name:{key:p.get(key) for key in ('scaling_driver','scaling_governor','scaling_min_freq','scaling_max_freq')} for name,p in state['policies'].items()}
            policy['boost']=state['boost']
            if self.policy_initial is None: self.policy_initial=policy
            elif policy!=self.policy_last:
                self.policy_changes+=1
                self.event(events,'read_only_policy_change',observed=policy)
            self.policy_last=policy
            freq = reported_frequency(state)
            if freq is not None: self.frequencies.append(freq)
            self.temperatures.append(cpu_temperatures(state))
            if self.verify_isolation:
                check = self.verify_isolation()
                self.isolation_verified = check['verified']
                self.isolation_failed |= not check['verified']
            value = {'monotonic_ns': begin, 'session_id': self.ident, 'cpu_affinity': sorted(os.sched_getaffinity(0)),
                     'state': state, 'counters': counters, 'deltas': change,
                     'task_scan_races': races, 'effective_frequency': 'unavailable', 'samples': self.samples}
            environment.writerow({'monotonic_ns': begin, 'session_id': self.ident,
                                  'observation_json': json.dumps(value)})
            self.samples += 1
        finally:
            self.overhead_ns += time.monotonic_ns()-begin

    def drain_trace(self, events):
        if self.trace_fd is None:
            return
        for _ in range(64):  # Bounded read budget; backlog is explicitly reported.
            try:
                raw = os.read(self.trace_fd, 65536)
            except BlockingIOError:
                return
            if not raw:
                return
            self.trace_pending += raw.decode(errors='replace')
            lines = self.trace_pending.split('\n')
            self.trace_pending = lines.pop()
            for line in lines:
                event = self.parser.feed(line)
                if event:
                    self.event(events, event.pop('kind'), **event)
        self.dropped += 1  # Budget exhausted: not a precise lost-event count.

    def _run(self):
        try:
            available = self.housekeeping & set(os.sched_getaffinity(0))
            if not available or available & {7, 15}:
                raise ValueError('Housekeeping affinity unavailable/unsafe')
            os.sched_setaffinity(0, available)
            self.monitor_affinity = sorted(os.sched_getaffinity(0))
            if self.trace_fd is not None:
                os.set_blocking(self.trace_fd, False)
            with (self.directory/'environment_samples.csv').open('x',newline='') as env, (self.directory/'interference_events.csv').open('x',newline='') as ev:
                e = csv.DictWriter(env,fieldnames=['monotonic_ns','session_id','observation_json'])
                w = csv.DictWriter(ev,fieldnames=['monotonic_ns','session_id','kind','details_json'])
                e.writeheader(); w.writeheader()
                self.sample(e,w)
                self.drain_trace(w)
                env.flush(); ev.flush()
                self.started_ns = time.monotonic_ns()
                self.ready.set()  # Initial observation and affinity precede benchmark launch.
                next_sample = time.monotonic()+self.interval
                while not self.stop_event.wait(.02 if self.mode=='diagnostic' else min(.2,self.interval)):
                    self.drain_trace(w)
                    if time.monotonic() >= next_sample:
                        self.sample(e,w)
                        env.flush(); ev.flush()
                        advances=max(1,int((time.monotonic()-next_sample)//self.interval)+1)
                        self.missed_deadlines+=advances-1
                        next_sample+=advances*self.interval
                self.drain_trace(w)
                self.sample(e,w)
                self.ended_ns = time.monotonic_ns()
        except Exception as exc:
            self.errors.append(f'{type(exc).__name__}: {exc}')
            self.ready.set()

    def stop(self, exit_status=None):
        self.stop_event.set()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            self.errors.append('Monitor did not stop within ten seconds')
        if self.trace_pending:
            self.dropped += 1
        begin, end = self.started_ns or 0, self.ended_ns or time.monotonic_ns()
        traced = self.parser.assess(self.allowed, begin, end,confirmed_foreign=set())
        self.migration |= any(e['tid'] in self.allowed and e['destination']!=7 for e in self.parser.migrations)
        variation = 100*(max(self.frequencies)-min(self.frequencies))/min(self.frequencies) if self.frequencies and min(self.frequencies)>0 else 0
        facts = {'monitor_errors': self.errors, 'migration': self.migration,
                 'isolation_failed': self.isolation_failed, 'isolation_verified': self.isolation_verified,
                 'sampled_competitors': self.observed_competitors,
                 'competing_ns': sum(v['duration_ns'] for v in traced['competing_intervals']),
                 'unclassified_execution_ns':sum(v['duration_ns'] for v in traced['unclassified_intervals']),
                 'irq_delta': self.irq_delta, 'policy_changes':self.policy_changes,
                 'reported_frequency_available':bool(self.frequencies),
                 'tdie_max_c':max((v['Tdie'] for v in self.temperatures if 'Tdie' in v),default=None),
                 'tctl_max_c':max((v['Tctl'] for v in self.temperatures if 'Tctl' in v),default=None), 'frequency_variation_pct': variation,
                 'trace_coverage_complete': traced['coverage_complete'],
                 'trace_loss_verified_zero': False,  # Privileged final per-CPU buffer stats are required.
                 'proc_visibility_complete': self.proc_complete, 'exit_status': exit_status,
                 'missed_sample_deadlines':self.missed_deadlines, 'scan_races': self.races, 'observation_errors':self.observation_errors[:100], 'observation_error_count':self.observation_error_count, 'read_budget_exhaustions_or_partial_records': self.dropped,
                 'trace': traced, 'reserved_context_switch_events':{str(cpu):len(events) for cpu,events in self.parser.switches.items()}, 'samples': self.samples, 'monitor_affinity': getattr(self,'monitor_affinity',None),
                 'sampling_work_ns': self.overhead_ns, 'monitoring_window_ns': max(0,end-begin),
                 'diagnostic_unavailable': self.mode=='diagnostic' and self.trace_fd is None}
        report = quality(facts, self.thresholds)
        report['limitations'] = ['Periodic scans miss short-lived tasks and cannot attribute tick deltas to a particular CPU',
                                'Scheduler trace windows may not bracket all execution; no PASS without verified coverage/loss accounting',
                                'Instrumentation shares cache/memory/package resources; no measured overhead calibration was run']
        with (self.directory/'benchmark_quality.json').open('x') as stream:
            json.dump(report,stream,indent=2)
        return report


def final_quality(report, privileged):
    """Incorporate root-instance loss counters without treating missing values as zero."""
    facts = dict(report['facts'])
    complete = bool(privileged.get('trace_instance')) and privileged.get('trace_config_verified',False)
    for snapshot in ('trace_initial_stats','trace_stats'):
        values = privileged.get(snapshot,{})
        for cpu in (7,15):
            text = values.get(f'per_cpu/cpu{cpu}/stats')
            if not isinstance(text,str):
                complete=False; continue
            counters = dict(line.split(':',1) for line in text.splitlines() if ':' in line)
            for key in ('overrun','commit overrun','dropped events'):
                if counters.get(key,'').strip()!='0': complete=False
    trace = facts.get('trace',{})
    facts['trace_loss_verified_zero'] = complete and not any((trace.get('parse_errors',1),trace.get('lost_record_markers',1),facts.get('read_budget_exhaustions_or_partial_records',1)))
    if not privileged.get('restoration',{}).get('verified'):
        facts['isolation_failed']=True
    return quality(facts,report.get('thresholds'))
