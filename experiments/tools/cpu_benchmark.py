#!/usr/bin/env python3
"""Launch an argument array with taskset; record a unique, non-overwriting session.

No governor changes or privilege escalation. Run from any working directory;
command paths remain relative to the caller's directory. Child processes inherit
CPU affinity unless they explicitly change it themselves.
"""
import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import uuid

REPOSITORY = Path(__file__).resolve().parents[2]
CPU_ROOT = Path('/sys/devices/system/cpu')


def read(path):
    try:
        return path.read_text().strip()
    except OSError as exc:
        return {'unavailable': str(exc)}


def capture(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=15)
        return {'argv': argv, 'returncode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'unavailable': str(exc)}


def snapshot():
    policies = {}
    for policy in sorted((CPU_ROOT / 'cpufreq').glob('policy*')):
        policies[policy.name] = {name: read(policy / name) for name in (
            'affected_cpus', 'related_cpus', 'scaling_driver', 'scaling_governor',
            'scaling_available_governors', 'scaling_min_freq', 'scaling_max_freq',
            'cpuinfo_min_freq', 'cpuinfo_max_freq', 'scaling_cur_freq', 'cpuinfo_cur_freq')}
    thermal = {}
    for hwmon in Path('/sys/class/hwmon').glob('hwmon*'):
        thermal[str(hwmon)] = {'name': read(hwmon / 'name'),
                              **{p.name: read(p) for p in hwmon.glob('temp*')
                                 if p.name.endswith(('_input', '_label', '_crit', '_max', '_crit_alarm', '_max_alarm'))}}
    return {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'policies': policies, 'boost': read(CPU_ROOT / 'cpufreq/boost'),
            'thermal': thermal, 'loadavg': read(Path('/proc/loadavg')),
            'proc_stat': read(Path('/proc/stat'))}



def validate_cpu(cpu_id):
    allowed = sorted(os.sched_getaffinity(0))
    cpu = CPU_ROOT / f'cpu{cpu_id}'
    if cpu_id not in allowed:
        raise ValueError(f'CPU {cpu_id} is outside inherited affinity {allowed}')
    if not cpu.is_dir() or ((cpu / 'online').exists() and read(cpu / 'online') != '1'):
        raise ValueError('selected CPU is missing or offline')
    return allowed, cpu


def affinity_argv(cpu_id, command):
    validate_cpu(cpu_id)
    taskset = shutil.which('taskset')
    if taskset is None:
        raise ValueError('taskset is unavailable; no packages were installed')
    return [taskset, '-c', str(cpu_id), *command]


def acquire_session_lock(parent):
    path = parent / '.controller.lock'
    inherited = os.environ.get('GRNG_SESSION_LOCK_FD')
    if inherited is not None:
        fd = os.dup(int(inherited))
        expected, actual = path.lstat(), os.fstat(fd)
        if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
            os.close(fd)
            raise ValueError('Inherited coordination lock does not match this workspace')
    else:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    lock = os.fdopen(fd, 'r' if inherited is not None else 'w')
    try:
        # Inherited descriptor shares the supervisor's locked open file description.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        lock.close()
        raise
    return lock


def signal_group(pid, signum):
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        pass

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu', type=int, default=7,
                        help='Logical CPU, default 7; recheck topology and load each session')
    parser.add_argument('command', nargs=argparse.REMAINDER,
                        help='Command and arguments after --; no shell evaluation')
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('supply a command after --')
    if '--overwrite' in command:
        parser.error('--overwrite is prohibited by this launcher')
    try:
        allowed, cpu = validate_cpu(args.cpu)
        invocation = affinity_argv(args.cpu, command)
    except ValueError as exc:
        parser.error(str(exc))
    # Exclusive mkdir/file creation; no result directory is ever reused.
    parent = REPOSITORY / 'experiments/results/linux_ryzen2700x/sessions'
    parent.mkdir(parents=True, exist_ok=True)
    coordination = acquire_session_lock(parent)
    session = parent / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex)
    session.mkdir()
    executable = shutil.which(command[0])
    metadata = {
        'command': command, 'taskset_argv': invocation,
        'cwd': str(Path.cwd()), 'selected_cpu': args.cpu, 'inherited_affinity': allowed,
        'core_id': read(cpu / 'topology/core_id'),
        'smt_siblings': read(cpu / 'topology/thread_siblings_list'),
        'uname': platform.uname()._asdict(), 'os_release': read(Path('/etc/os-release')),
        'python': sys.version, 'lscpu': capture(['lscpu']),
        'gcc': capture(['gcc', '--version']),
        'git_commit': capture(['git', '-C', str(REPOSITORY), 'rev-parse', 'HEAD']),
        'git_status': capture(['git', '-C', str(REPOSITORY), 'status', '--short']),
        'git_diff': capture(['git', '-C', str(REPOSITORY), 'diff', '--no-ext-diff']),
        'packages': capture([sys.executable, '-m', 'pip', 'freeze']),
        'executable': executable, 'governor_changes_requested': False,
        'note': 'Snapshots occur outside child execution; no continuous sampling. Command may create its own files; choose fresh output destinations.'}
    if executable and Path(executable).is_file():
        metadata['executable_sha256'] = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    child = None
    received = []
    def forward(signum, frame):
        received.append(signum)
        if child is not None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass
    previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    code = 127
    try:
        metadata['before'] = snapshot()
        with (session / 'before.json').open('x') as stream:
            json.dump(metadata, stream, indent=2)
        print(f'Session: {session}', flush=True)
        with (session / 'stdout.txt').open('xb') as stdout, (session / 'stderr.txt').open('xb') as stderr:
            # New process group lets interruption reach the command and descendants.
            if received:
                code = 128 + received[-1]
            else:
                child = subprocess.Popen(metadata['taskset_argv'], stdout=stdout, stderr=stderr,
                                         start_new_session=True)
                # Cover a signal arriving between the guard and Popen completion.
                if received:
                    forward(received[-1], None)
                raw_code = child.wait()
                metadata['child_returncode'] = raw_code
                code = raw_code if raw_code >= 0 else 128 - raw_code
    except OSError as exc:
        metadata['launch_error'] = str(exc)
        print(str(exc), file=sys.stderr)
    finally:
        metadata.update(after=snapshot(), returncode=code, received_signals=received)
        with (session / 'session.json').open('x') as stream:
            json.dump(metadata, stream, indent=2)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    coordination.close()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
