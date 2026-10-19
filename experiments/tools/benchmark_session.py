#!/usr/bin/env python3
"""Unprivileged GRNG session controller: baseline, software and BIOS modes.

Software --plan is read-only. Software execution requires the separately approved
administrative frequency_control supervisor. This script never invokes sudo.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

import cpu_benchmark as common
import frequency_control as control
import isolation_manager as isolation
import interference_monitor as interference

SESSIONS = common.REPOSITORY / 'experiments/results/linux_ryzen2700x/sessions'


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def inspect(cpu):
    allowed, node = common.validate_cpu(cpu)
    data = common.snapshot()
    data.update(cpu=cpu, inherited_affinity=allowed,
                physical_core=common.read(node / 'topology/core_id'),
                smt_siblings=common.read(node / 'topology/thread_siblings_list'),
                related_policies={p.name: common.read(p / 'related_cpus')
                                  for p in (common.CPU_ROOT / 'cpufreq').glob('policy*')},
                instruments={name: shutil.which(name) for name in ('sensors', 'perf', 'cpupower', 'turbostat')},
                perf_event_paranoid=common.read(Path('/proc/sys/kernel/perf_event_paranoid')),
                aperf_event=common.read(Path('/sys/bus/event_source/devices/msr/events/aperf')),
                mperf_event=common.read(Path('/sys/bus/event_source/devices/msr/events/mperf')),
                effective_frequency={'status': 'unavailable', 'value_khz': None,
                                     'reason': 'No calibrated/permission-verified APERF/MPERF collector configured; sysfs is reported frequency only'})
    return data


def verify(mode, target, state, tolerance):
    warnings = []
    if mode == 'software':
        for name, p in state['policies'].items():
            if any(p.get(key) != value for key, value in (
                    ('scaling_governor', 'userspace'), ('scaling_min_freq', str(target)),
                    ('scaling_max_freq', str(target)))):
                raise ValueError(f'{name}: software requested state not accepted')
    if mode in ('software', 'bios'):
        warnings.append('Effective fixed frequency UNVERIFIED: no reliable hardware frequency collector is active')
        for name, p in state['policies'].items():
            # related_cpus masks may contain ranges; include all policies conservatively.
            value = p.get('scaling_cur_freq')
            if isinstance(value, str) and value.isdecimal() and abs(int(value) - target) > target * tolerance:
                warnings.append(f'{name}: reported frequency {value} kHz differs from target; not an effective-clock measurement')
        if state['boost'] == '1':
            warnings.append('Boost is enabled; a fixed clock cannot be inferred')
    return {'requested_state_accepted': True if mode == 'software' else None, 'physical_clock_verified': False,
            'warnings': warnings}


COLUMNS = ['timestamp_utc', 'monotonic_ns', 'session_id', 'phase', 'selected_logical_cpu',
           'active_logical_cpu', 'active_cpu_status', 'physical_core', 'smt_siblings', 'policy',
           'related_cpus', 'driver', 'governor', 'requested_khz', 'reported_current_khz',
           'cpuinfo_current_khz', 'effective_frequency_khz', 'effective_frequency_status',
           'minimum_khz', 'maximum_khz', 'boost', 'temperatures_json', 'workload_exit_status']


def telemetry_rows(session_id, phase, cpu, target, pid=None, exit_status=None, state=None):
    state = common.snapshot() if state is None else state
    active = None
    if pid is not None:
        try:
            # Field 39 is processor; comm (field 2) may contain spaces/parentheses.
            active = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[36])
        except (OSError, ValueError, IndexError):
            pass
    for name, p in state['policies'].items():
        yield dict(zip(COLUMNS, [state['timestamp_utc'], time.monotonic_ns(), session_id, phase,
            cpu, active, 'last scheduled CPU of direct child only' if active is not None else 'unavailable',
            common.read(common.CPU_ROOT / f'cpu{cpu}/topology/core_id'),
            common.read(common.CPU_ROOT / f'cpu{cpu}/topology/thread_siblings_list'), name,
            p.get('related_cpus'), p.get('scaling_driver'), p.get('scaling_governor'), target,
            p.get('scaling_cur_freq'), p.get('cpuinfo_cur_freq'), None, 'unavailable',
            p.get('scaling_min_freq'), p.get('scaling_max_freq'), state['boost'],
            json.dumps(state['thermal']), exit_status]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolation', choices=('none','plan','active'), default='none')
    parser.add_argument('--monitor-mode', choices=('lightweight','diagnostic'), default='lightweight')
    parser.add_argument('--quality-thresholds', type=Path, help='JSON quality limits, validated nonnegative finite values')
    parser.add_argument('--mode', choices=('baseline', 'software', 'bios'), default='baseline')
    parser.add_argument('--cpu', type=int, default=7)
    parser.add_argument('--target-khz', type=int, default=3200000)
    parser.add_argument('--tolerance', type=float, default=0.05, help='Reported-frequency warning threshold; not clock verification')
    parser.add_argument('--telemetry-interval', type=float, default=1.0)
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not 1 <= args.target_khz <= 10000000 or not math.isfinite(args.telemetry_interval) or args.telemetry_interval < 0.2:
        parser.error('invalid target or telemetry interval (minimum 0.2 seconds)')
    if not math.isfinite(args.tolerance) or not 0 <= args.tolerance <= 1:
        parser.error('tolerance must be finite in [0,1]')
    if args.isolation == 'plan':
        print(json.dumps(isolation.plan(isolation.inspect()), indent=2))
        return 0
    active_isolation = None
    if args.isolation == 'active':
        if args.mode != 'bios' or args.cpu != 7 or 'GRNG_ISOLATION_SOCKET' not in os.environ:
            parser.error('Active isolation requires the approved isolation supervisor, BIOS read-only mode and CPU7')
        active_isolation = json.loads(os.environ['GRNG_ISOLATION_STATE'])
        state = common.snapshot()
        state.update(cpu=7, inherited_affinity=sorted(os.sched_getaffinity(0)), physical_core=common.read(common.CPU_ROOT/'cpu7/topology/core_id'),
                     smt_siblings=common.read(common.CPU_ROOT/'cpu7/topology/thread_siblings_list'),
                     related_policies={name:p['related_cpus'] for name,p in state['policies'].items()})
        if set(parse_cpus(state['smt_siblings'])) != {7,15}:
            parser.error('Reserved physical core topology changed')
    else:
        state = inspect(args.cpu)
    thresholds = None
    if args.quality_thresholds:
        thresholds = json.loads(args.quality_thresholds.read_text())
        allowed = {'max_competing_ns','max_irq_delta','max_frequency_variation_pct','max_tdie_c'}
        if not isinstance(thresholds,dict) or set(thresholds)-allowed or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in thresholds.values()):
            parser.error('Invalid quality thresholds')
    if args.mode == 'software' and args.isolation != 'none':
        parser.error('Frequency control is excluded from isolation sessions')
    if args.inspect or args.plan:
        result = {'mode': args.mode, 'state': state, 'will_execute': False}
        if args.mode != 'software':
            result['verification'] = verify(args.mode, args.target_khz, state, args.tolerance)
        if args.mode == 'software':
            result['control_plan'] = control.plan(args.target_khz)
        print(json.dumps(result, indent=2))
        return 0
    if os.geteuid() == 0:
        parser.error('Run this session controller as an unprivileged user')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or '--overwrite' in command:
        parser.error('Provide a command after --, without --overwrite')
    if args.mode == 'software' and not os.environ.get('GRNG_CONTROL_JOURNAL'):
        parser.error('Software execution requires the explicitly approved frequency_control supervisor; use --plan first')
    verification = verify(args.mode, args.target_khz, state, args.tolerance)
    broker_fd = None
    if active_isolation:
        broker_fd = int(os.environ['GRNG_ISOLATION_SOCKET'])
        invocation = [sys.executable, '-B', str(Path(__file__).with_name('isolation_manager.py')), 'proxy', '--', *command]
    else:
        invocation = common.affinity_argv(args.cpu, command)
    session_root = Path(os.environ.get('GRNG_SESSION_ROOT', str(SESSIONS)))
    if session_root.resolve() != SESSIONS.resolve():
        raise ValueError('Supervisor session root does not match the repository sessions directory')
    SESSIONS.mkdir(parents=True, exist_ok=True)
    with common.acquire_session_lock(SESSIONS) as lock:
        ident = os.environ.get('GRNG_ISOLATION_ID') or os.environ.get('GRNG_CONTROL_ID') or str(uuid.uuid4())
        ident = str(uuid.UUID(ident))
        session = SESSIONS / ident
        session.mkdir()  # Exclusive; never reuse a session path.
        print(f'Session: {session}', flush=True)
        env = {'state': state, 'verification': verification, 'uname': platform.uname()._asdict(),
               'python': sys.version, 'os_release': common.read(Path('/etc/os-release')),
               'lscpu': common.capture(['lscpu']), 'compiler': common.capture(['gcc', '--version']),
               'packages': common.capture([sys.executable, '-m', 'pip', 'freeze']),
               'git_commit': common.capture(['git', '-C', str(common.REPOSITORY), 'rev-parse', 'HEAD']),
               'git_status': common.capture(['git', '-C', str(common.REPOSITORY), 'status', '--short']),
               'git_diff': common.capture(['git', '-C', str(common.REPOSITORY), 'diff', '--no-ext-diff']),
               'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'monitor_sha256':hashlib.sha256(Path(interference.__file__).read_bytes()).hexdigest(),
               'isolation_source_sha256':hashlib.sha256(Path(isolation.__file__).read_bytes()).hexdigest()}
        executable = shutil.which(command[0])
        if executable:
            env['executable_sha256'] = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
        save(session / 'environment.json', env)
        record = {'session_id': ident, 'mode': args.mode, 'cpu': args.cpu, 'target_khz': args.target_khz,
                  'requested_khz': args.target_khz if args.mode == 'software' else None,
                  'command': command, 'taskset_argv': invocation, 'cwd': str(Path.cwd()),
                  'control_journal': os.environ.get('GRNG_CONTROL_JOURNAL'),
                  'physical_clock_verified': False, 'telemetry_interval_seconds': args.telemetry_interval,
                  'warmup': 'unchanged; only explicit command arguments apply', 'warnings': verification['warnings']}
        save(session / 'journal.json', {**record, 'status': 'prepared', 'system_changes': False})
        check = (lambda: isolation.effective_verify(active_isolation)) if active_isolation else None
        trace_fd = int(os.environ['GRNG_ISOLATION_TRACE_FD']) if 'GRNG_ISOLATION_TRACE_FD' in os.environ else None
        housekeeping = set(state['inherited_affinity']) - {7,15}
        observer = interference.Monitor(session,ident,housekeeping,args.telemetry_interval,args.monitor_mode,
                                        trace_fd,verify_isolation=check,thresholds=thresholds)
        if args.monitor_mode=='diagnostic' and trace_fd is None:
            record['warnings'].append('Scheduler trace access unavailable: diagnostic fallback uses snapshots and cannot prove uncontaminated execution')
        observer.proc_complete = bool(active_isolation and active_isolation.get('root_visibility_verified'))
        if active_isolation:
            save(session/'isolation_status.json',active_isolation)
        else:
            save(session/'isolation_status.json',{'verified':False,'status':'not_activated','frequency_writes':[]})
        child = None
        received = []
        stop = threading.Event()
        telemetry_errors = []
        observed_frequencies = []
        code = 125
        def forward(sig, frame):
            received.append(sig)
            if broker_fd is not None: isolation.cancel_request(broker_fd)
            if child is not None:
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
        previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        with (session / 'cpu_telemetry.csv').open('x', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            def emit(phase, snapshot=None):
                rows = list(telemetry_rows(ident, phase, args.cpu, args.target_khz if args.mode != 'baseline' else None,
                                           child.pid if child else None, code if phase=="after" else None, state=snapshot))
                for row in rows:
                    value = row['reported_current_khz']
                    if isinstance(value, str) and value.isdecimal() and args.cpu in parse_cpus(str(row['related_cpus']).replace(' ', ',')):
                        observed_frequencies.append({'phase': phase, 'reported_khz': int(value)})
                writer.writerows(rows)
                stream.flush()
            observer.telemetry_callback=emit
            try:
                observer.start()  # Affinity + initial observation must finish BEFORE launching workload.
                record['telemetry_cpu_affinity']=observer.monitor_affinity
                with (session / 'stdout.txt').open('xb') as stdout, (session / 'stderr.txt').open('xb') as stderr:
                    if received:
                        code = 128 + received[-1]
                    else:
                        record['started_at'] = datetime.now(timezone.utc).isoformat()
                        child = subprocess.Popen(invocation, stdout=stdout, stderr=stderr, start_new_session=True,
                                                 pass_fds=(broker_fd,) if broker_fd is not None else ())
                        if active_isolation is None:
                            observer.pid = child.pid
                        if received:
                            forward(received[-1], None)
                        # Bounded cancellation; no timeout imposed on an uninterrupted workload.
                        deadline = None
                        while child.poll() is None:
                            if observer.errors or observer.isolation_failed or not observer.thread.is_alive():
                                if not observer.thread.is_alive() and not observer.errors:
                                    observer.errors.append('Monitor exited unexpectedly during workload')
                                if broker_fd is not None: isolation.cancel_request(broker_fd)
                                record['monitor_failed'] = list(observer.errors)
                                common.signal_group(child.pid, signal.SIGTERM)
                                if deadline is None:
                                    deadline = time.monotonic()+5
                            if received and deadline is None:
                                deadline = time.monotonic() + 5
                            if deadline is not None and time.monotonic() >= deadline:
                                common.signal_group(child.pid, signal.SIGKILL)
                                if time.monotonic() >= deadline+2:
                                    raise RuntimeError('Workload did not exit after SIGKILL; cleanup requires review')
                            stop.wait(0.05)
                        raw = child.wait(timeout=2)
                        record['child_returncode'] = raw
                        code = raw if raw >= 0 else 128 - raw
            except (OSError, ValueError, RuntimeError) as exc:
                record['error'] = str(exc)
            finally:
                if child is not None and child.poll() is None:
                    common.signal_group(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        common.signal_group(child.pid, signal.SIGKILL)
                        try:
                            child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            record['cleanup_error']='Child remains after SIGKILL; manual recovery required'
                            observer.errors.append(record['cleanup_error'])
                stop.set()
                quality = observer.stop(code) if observer.thread.ident is not None else interference.quality({'monitor_errors':['Monitor never started']})
                if not (session/'benchmark_quality.json').exists():
                    save(session/'benchmark_quality.json',quality)
                record['environment_quality'] = quality['classification']
                record['monitoring_mode'] = args.monitor_mode
                restoration = {'required': args.mode == 'software' or bool(active_isolation),
                               'status': 'pending_isolation_supervisor' if active_isolation else 'pending_privileged_supervisor' if args.mode == 'software' else 'not_needed',
                               'journal': active_isolation['journal'] if active_isolation else record['control_journal']}
                if args.mode != 'software' and not active_isolation:
                    save(session / 'restoration.json', restoration)
                running = [v['reported_khz'] for v in observed_frequencies if v['phase'] == 'running']
                record['reported_frequency_observations'] = observed_frequencies
                if args.mode in ('bios', 'software') and any(abs(v - args.target_khz) > args.target_khz * args.tolerance for v in running):
                    record['warnings'].append('Under-load sysfs frequency reports differ from target; effective frequency remains unverified')
                if not running:
                    record['warnings'].append('Workload ended before an under-load frequency sample was collected')
                record.update(exit_status=code, signals=received, telemetry_errors=telemetry_errors,
                              status=('pending_restoration' if args.mode == 'software' or active_isolation else
                                      'successful' if code == 0 and not telemetry_errors and not observer.errors else 'failed'),
                              restoration=restoration, ended_at=datetime.now(timezone.utc).isoformat())
                save(session / 'session.json', record)
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
        print(json.dumps({'session_id': ident, 'exit_status': code, 'status': record['status'],
                          'warnings': record['warnings'], 'telemetry_errors': telemetry_errors}))
        return code


def parse_cpus(text):
    for part in text.replace(' ', ',').split(','):
        if not part:
            continue
        bounds = part.split('-')
        yield from range(int(bounds[0]), int(bounds[-1]) + 1)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(125)
