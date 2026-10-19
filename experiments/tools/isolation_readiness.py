#!/usr/bin/env python3
"""Read-only, bounded host inspection. Never activates isolation or enables tracing."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time

import isolation_manager as iso
import interference_monitor as monitor

HISTORICAL_TIDS = (186, 288, 15162, 16252, 355, 15092, 15392)


def thread_snapshot(proc=Path('/proc'), getter=None):
    """Identity is (PID,TID,start_ticks); last_cpu is not an execution trace."""
    getter = os.sched_getaffinity if getter is None else getter
    tasks, errors, races = {}, [], 0
    for process in proc.glob('[0-9]*'):
        try:
            for thread in (process/'task').iterdir():
                try:
                    text = (thread/'stat').read_text()
                    value = monitor.task_stat(text)
                    fields = text.rsplit(')', 1)[1].split()
                    flags = int(fields[6])
                    affinity = sorted(getter(int(thread.name)))
                    # Verify lifetime across the affinity read; IDs can be reused.
                    if monitor.task_stat((thread/'stat').read_text())['start_ticks'] != value['start_ticks']:
                        races += 1
                        continue
                    kernel = bool(flags & 0x00200000)  # PF_KTHREAD
                    no_setaffinity = bool(flags & 0x04000000)  # PF_NO_SETAFFINITY
                    value.update(pid=int(process.name), tid=int(thread.name), flags=flags,
                                 kernel_thread=kernel, affinity=affinity,
                                 last_cpu=value.pop('cpu'),
                                 per_cpu_name_hint=bool(kernel and re.search(r'[/:-](7|15)(?:$|[-:])', value['name'])),
                                 affinity_user_change_forbidden=no_setaffinity,
                                 migratability=('kernel forbids userspace affinity changes' if no_setaffinity else
                                                'not established; affinity/name alone cannot prove migratability'))
                    tasks[(value['pid'], value['tid'], value['start_ticks'])] = value
                except (FileNotFoundError, ProcessLookupError):
                    races += 1
                except (OSError, ValueError, IndexError) as exc:
                    errors.append({'path': str(thread), 'error': str(exc)})
        except (FileNotFoundError, ProcessLookupError):
            races += 1
        except OSError as exc:
            errors.append({'path': str(process), 'error': str(exc)})
    return {'tasks': tasks, 'errors': errors, 'races': races, 'monotonic_ns': time.monotonic_ns()}


def thread_deltas(before, after, hz=None):
    hz = os.sysconf('SC_CLK_TCK') if hz is None else hz
    rows = []
    for identity in sorted(before['tasks'].keys() | after['tasks'].keys()):
        old, new = before['tasks'].get(identity), after['tasks'].get(identity)
        value = dict(new or old)
        if not (set(value['affinity']) & iso.RESERVED or value['last_cpu'] in iso.RESERVED):
            continue
        delta = new['ticks']-old['ticks'] if old and new else None
        value.update(lifetime='survived' if old and new else 'new_or_reused' if new else 'exited_or_invisible',
                     cpu_ticks_delta=delta, cpu_seconds_delta=delta/hz if delta is not None and delta >= 0 else None,
                     consumed_cpu_anywhere=delta > 0 if delta is not None and delta >= 0 else None,
                     affinity_before=old['affinity'] if old else None,
                     actual_execution_on_reserved_cpus='UNVERIFIED: no scheduler event collection')
        rows.append(value)
    return rows


def hierarchy(root=iso.CGROUP):
    rows = []
    for group in [root] + sorted(p for p in root.iterdir() if p.is_dir()):
        fields = {name: iso.read(group/name) for name in (
            'cgroup.controllers', 'cgroup.subtree_control', 'cgroup.type', 'cgroup.procs',
            'cpuset.cpus', 'cpuset.cpus.effective', 'cpuset.cpus.partition')}
        info = group.stat()
        rows.append({'path': str(group), 'uid': info.st_uid, 'gid': info.st_gid,
                     'mode': oct(info.st_mode & 0o777), 'files': fields})
    return rows


def blockers(state, proposed):
    """Classify scope and missing evidence, without equating empty properties to empty CPUs."""
    bus = any('connect to bus' in error or 'query systemd' in error for error in state['errors'])
    hidden = any('hidden PIDs' in error for error in state['errors'])
    return [
        {'check': 'CPU7/15 topology', 'classification': 'Resolved' if state.get('siblings') == '7,15' else 'Not yet verified'},
        {'check': 'system bus', 'classification': 'Requires administrative authorization' if bus else 'Resolved',
         'scope': 'Current inspection context; host administrative bus operation not demonstrated here'},
        {'check': 'host task visibility', 'classification': 'Not yet verified' if hidden else 'Resolved',
         'scope': 'Namespace-hidden IDs prevent a host-wide kernel-thread inventory'},
        {'check': 'scheduler tracing', 'classification': 'Requires administrative authorization',
         'scope': 'No trace collection attempted; lightweight snapshots cannot certify absence of interference'},
        {'check': 'descendant cpuset enablement', 'classification': 'Not yet verified' if 'cpuset' not in str(state.get('root_subtree_control')).split() else 'Resolved',
         'scope': 'Root controller availability is established; systemd runtime enablement requires an approved live test'},
        {'check': 'isolated cpuset partition', 'classification': 'Unsupported on this environment',
         'scope': 'No safe delegated isolated-partition implementation established for this systemd249/kernel5.15 hierarchy; managed-workload API strategy retained'},
        {'check': 'live restoration and broker path', 'classification': 'Not yet verified',
         'scope': 'Only fixture tests; restricted context cannot verify inherited-socket proxy or hardware restoration'},
        {'check': 'current plan', 'classification': 'Not yet verified' if proposed['errors'] else 'Resolved', 'errors': proposed['errors']},
    ]


def collect(interval=2, proc=Path('/proc')):
    state = iso.inspect(proc_root=proc)
    proposed = iso.plan(state)
    before = thread_snapshot(proc)
    try:
        counters_before = monitor.cpu_counters(proc)
        counter_error = None
    except (OSError, ValueError, KeyError, IndexError) as exc:
        counters_before = None
        counter_error = str(exc)
    time.sleep(interval)
    after = thread_snapshot(proc)
    try:
        counters_after = monitor.cpu_counters(proc)
        counter_change = monitor.deltas(counters_before, counters_after) if counters_before else {'unavailable': counter_error or 'No initial counters'}
    except (OSError, ValueError, KeyError, IndexError) as exc:
        counter_change = {'unavailable': str(exc)}
    return {'captured_at': datetime.now(timezone.utc).isoformat(), 'inspection': state,
            'plan': proposed, 'hierarchy': hierarchy(), 'blockers': blockers(state, proposed),
            'observation': {'requested_seconds': interval,
                            'actual_seconds': (after['monotonic_ns']-before['monotonic_ns'])/1e9,
                            'threads': thread_deltas(before, after),
                            'snapshot_errors': before['errors']+after['errors'],
                            'races': before['races']+after['races'],
                            'historical_tid_current_visibility': {str(tid): (proc/str(tid)).exists() for tid in HISTORICAL_TIDS},
                            'historical_tid_note': 'Invisible is not proof of host exit; historical IDs are not identities',
                            'cpu_counter_deltas': counter_change,
                            'execution_interference': 'UNVERIFIED: per-thread ticks are not per-CPU scheduler intervals'},
            'frequency_read_only': monitor.common.snapshot(),
            'readiness': 'NO-GO: requires unrestricted host evidence, explicit approval and live recovery verification'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval', type=float, default=2)
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval) or not .1 <= args.interval <= 10:
        parser.error('interval must be finite and between 0.1 and 10 seconds')
    print(json.dumps(collect(args.interval), indent=2))


if __name__ == '__main__':
    main()
