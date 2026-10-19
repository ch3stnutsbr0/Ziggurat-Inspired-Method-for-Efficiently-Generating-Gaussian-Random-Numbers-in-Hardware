#!/usr/bin/env python3
"""Explicit administrative supervisor. No sudo, shell evaluation or automatic installation.

For live use deploy THIS FILE alone into a root-owned, non-writable directory.
Run with python -I. All benchmark commands execute as a named non-root user.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import subprocess
import sys
import uuid

CPU = Path('/sys/devices/system/cpu')
STATE = Path('/var/lib/grng-benchmark')
FIELDS = ('scaling_governor', 'scaling_min_freq', 'scaling_max_freq')


def read(path):
    return path.read_text().strip()


def durable(path, data):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def plan(target, disable_boost=False, root=CPU):
    if type(target) is not int or not 1 <= target <= 10000000:
        raise ValueError('target-khz must be an integer in [1, 10000000]')
    policies = []
    for p in sorted((root / 'cpufreq').glob('policy*')):
        if read(p / 'scaling_driver') != 'acpi-cpufreq':
            raise ValueError(f'{p.name}: this control implementation supports acpi-cpufreq only')
        original = {key: read(p / key) for key in FIELDS}
        states = read(p / 'scaling_available_frequencies').split()
        if str(target) not in states or 'userspace' not in read(p / 'scaling_available_governors').split():
            raise ValueError(f'{p.name}: target state/userspace is unsupported')
        if original['scaling_governor'] == 'userspace':
            value = read(p / 'scaling_setspeed')
            if not value.isdecimal():
                raise ValueError(f'{p.name}: original userspace setpoint cannot be recovered')
            original['scaling_setspeed'] = value
        policies.append({'policy': p.name, 'original': original,
                         'related_cpus': read(p / 'related_cpus')})
    if not policies:
        raise ValueError('No CPUFreq policies available')
    if read(root / 'cpufreq/boost') not in ('0', '1'):
        raise ValueError('Boost state is unavailable; software control is not planned')
    data = {'target_khz': target, 'disable_boost': disable_boost,
            'original_boost': read(root / 'cpufreq/boost'), 'policies': policies,
            'scope': 'All exposed policies: SMT/shared hardware control is not fully described by Linux policy masks',
            'physical_clock_verified': False,
            'writes_per_policy': ['scaling_min_freq (lower if needed)', 'scaling_max_freq',
                                 'scaling_min_freq', 'scaling_governor=userspace', 'scaling_setspeed=target'],
            'limitation': 'Accepted P-state/limits do not prove an exact effective physical clock'}
    validate_journal(data, root)
    return data


def write(path, value):
    with path.open('w') as stream:
        stream.write(str(value) + '\n')


def limits(p, minimum, maximum):
    # Expand safely before narrowing, including restoration from min=max.
    write(p / 'scaling_min_freq', min(int(read(p / 'scaling_min_freq')), int(minimum)))
    write(p / 'scaling_max_freq', maximum)
    write(p / 'scaling_min_freq', minimum)


def apply(data, root=CPU):
    for item in data['policies']:
        p = root / 'cpufreq' / item['policy']
        target = data['target_khz']
        limits(p, target, target)
        write(p / 'scaling_governor', 'userspace')
        write(p / 'scaling_setspeed', target)
        for key, expected in [('scaling_governor', 'userspace'), ('scaling_min_freq', str(target)),
                              ('scaling_max_freq', str(target)), ('scaling_setspeed', str(target))]:
            if read(p / key) != expected:
                raise ValueError(f'Control verification failed: {p.name}/{key}')
    if data['disable_boost']:
        write(root / 'cpufreq/boost', '0')
        if read(root / 'cpufreq/boost') != '0':
            raise ValueError('Boost disable verification failed')


def restore(data, root=CPU):
    errors = []
    # Independent attempts: a limit failure must not prevent governor recovery.
    for item in data['policies']:
        p = root / 'cpufreq' / item['policy']
        original = item['original']
        operations = [('limits', lambda: limits(p, original['scaling_min_freq'], original['scaling_max_freq'])),
                      ('governor', lambda: write(p / 'scaling_governor', original['scaling_governor']))]
        if 'scaling_setspeed' in original:
            operations.append(('setpoint', lambda: write(p / 'scaling_setspeed', original['scaling_setspeed'])))
        for label, operation in operations:
            try:
                operation()
            except (OSError, ValueError) as exc:
                errors.append(f"{item['policy']}/{label}: {exc}")
        for key, expected in original.items():
            try:
                if read(p / key) != expected:
                    raise ValueError('readback differs')
            except (OSError, ValueError) as exc:
                errors.append(f"{item['policy']}/{key}: {exc}")
    if data['disable_boost']:
        try:
            write(root / 'cpufreq/boost', data['original_boost'])
            if read(root / 'cpufreq/boost') != data['original_boost']:
                raise ValueError('boost readback differs')
        except (OSError, ValueError) as exc:
            errors.append(f'boost: {exc}')
    return {'verified': not errors, 'errors': errors}


def trusted(path):
    path = path.absolute()
    for p in (path, *path.parents):
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError(f'Root control requires root-owned non-writable deployment: {p}')


def validate_journal(data, root=None):
    root = CPU if root is None else root
    if type(data.get('target_khz')) is not int or data.get('original_boost') not in ('0', '1'):
        raise ValueError('Invalid journal values')
    if type(data.get('disable_boost')) is not bool or not data.get('policies'):
        raise ValueError('Invalid journal scope')
    for item in data['policies']:
        name = item['policy']
        if not name.startswith('policy') or not name[6:].isdecimal():
            raise ValueError('Invalid policy name')
        p = root / 'cpufreq' / name
        original = item['original']
        if set(original) not in (set(FIELDS), set(FIELDS) | {'scaling_setspeed'}):
            raise ValueError('Invalid original settings')
        if original['scaling_governor'] not in read(p / 'scaling_available_governors').split():
            raise ValueError('Original governor no longer supported')
        low, high = int(read(p / 'cpuinfo_min_freq')), int(read(p / 'cpuinfo_max_freq'))
        for key in ('scaling_min_freq', 'scaling_max_freq', 'scaling_setspeed'):
            if key in original and (not original[key].isdecimal() or not low <= int(original[key]) <= high):
                raise ValueError('Original frequency outside current hardware limits')
        if int(original['scaling_min_freq']) > int(original['scaling_max_freq']):
            raise ValueError('Invalid limit ordering')



def require_admin(approved):
    if os.geteuid() != 0 or not approved:
        raise ValueError('Live control/recovery requires explicit approval and a normal administrative terminal; no sudo is invoked')
    if not sys.flags.isolated:
        raise ValueError('Administrative invocation requires python3 -I')
    trusted(Path(__file__))


def lock_session(root, uid):
    fd = os.open(root / '.controller.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != uid:
            raise ValueError('Coordination lock must be a regular file owned by the benchmark user')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-khz', type=int, default=3200000)
    parser.add_argument('--disable-boost', action='store_true')
    parser.add_argument('--approve-boost-change', action='store_true')
    parser.add_argument('--approve-temporary-control', action='store_true')
    parser.add_argument('--user', help='Non-root benchmark account')
    parser.add_argument('--session-root', type=Path, help='User-owned standard sessions directory; required for execution')
    parser.add_argument('--confirm-workload-stopped', action='store_true')
    parser.add_argument('--recover', help='Journal UUID from the fixed state directory')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(plan(args.target_khz, args.disable_boost), indent=2))
        return 0
    require_admin(args.approve_temporary_control)
    if args.disable_boost and not args.approve_boost_change:
        parser.error('Boost changes require separate approval')
    if not STATE.exists():
        STATE.mkdir(mode=0o700)
    trusted(STATE)
    lockfd = os.open(STATE / 'control.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lockfd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.recover:
            if not args.confirm_workload_stopped:
                raise ValueError('Recovery requires --confirm-workload-stopped after inspecting orphan processes')
            ident = str(uuid.UUID(args.recover))
            path = STATE / f'{ident}.json'
            trusted(path)
            data = json.loads(path.read_text())
            validate_journal(data)
            # Refuse recovery while an orphan workload may still be alive.
            if data.get('child_pid') and Path(f"/proc/{data['child_pid']}").exists():
                raise ValueError('Recorded workload PID exists; inspect and stop it before recovery (PID reuse is possible)')
            coordination = lock_session(Path(data['session_root']), data['benchmark_uid'])
            try:
                result = restore(data)
            finally:
                os.close(coordination)
            data.update(restoration=result, status='recovered' if result['verified'] else 'restore_failed')
            durable(path, data)
            print(json.dumps(result, indent=2))
            return 0 if result['verified'] else 1
        # Refuse a new session until all durable unfinished transactions are recovered.
        for prior in STATE.glob('*.json'):
            if json.loads(prior.read_text()).get('status') not in ('restored', 'recovered'):
                raise ValueError(f'Unfinished control journal requires recovery: {prior.name}')
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command or not args.user or pwd.getpwnam(args.user).pw_uid == 0:
            parser.error('Provide a non-root --user and a command after --')
        if args.session_root is None:
            parser.error('--session-root is required')
        account = pwd.getpwnam(args.user)
        coordination = lock_session(args.session_root, account.pw_uid)
        data = plan(args.target_khz, args.disable_boost)
        ident = str(uuid.uuid4())
        path = STATE / f'{ident}.json'
        data.update(status='prepared', child_pid=None, journal_id=ident,
                    session_root=str(args.session_root.absolute()), benchmark_uid=account.pw_uid)
        durable(path, data)  # fsync originals BEFORE the first sysfs write
        print(f'Control journal: {path}', flush=True)
        child = None
        rc = 125
        cancel_signal = None
        def interrupted(sig, frame):
            raise InterruptedError(sig)
        previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        try:
            apply(data)
            data['status'] = 'applied'
            durable(path, data)
            # Pass only non-secret identifiers; user command never runs with root UID.
            env = dict(os.environ, GRNG_CONTROL_JOURNAL=str(path),
                       GRNG_CONTROL_ID=ident, GRNG_SESSION_LOCK_FD=str(coordination),
                       GRNG_SESSION_ROOT=str(args.session_root.absolute()))
            child = subprocess.Popen(['/usr/sbin/runuser', '-u', args.user, '--', *command],
                                     env=env, start_new_session=True, pass_fds=(coordination,))
            data['child_pid'] = child.pid
            durable(path, data)
            rc = child.wait()
            rc = rc if rc >= 0 else 128 - rc
        except InterruptedError as exc:
            cancel_signal = int(exc.args[0])
            rc = 128 + cancel_signal
        except (OSError, ValueError) as exc:
            data['error'] = str(exc)
        finally:
            for sig in previous:
                signal.signal(sig, signal.SIG_IGN)
            if child is not None and child.poll() is None:
                os.killpg(child.pid, cancel_signal or signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            if cancel_signal is not None and child is not None and child.poll() is not None:
                child_status = child.poll()
                rc = child_status if child_status >= 0 else 128 - child_status
            result = restore(data)
            data.update(restoration=result, status='restored' if result['verified'] else 'restore_failed',
                        workload_exit_status=rc, child_pid=None)
            durable(path, data)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            final = {'journal': str(path), **result, 'workload_exit_status': rc,
                     'status': 'successful' if rc == 0 and result['verified'] else 'failed'}
            # All writes into the user workspace execute AS THAT USER, never as root.
            # Controller reserves its UUID directory; absent directory is an error.
            report_code = (
                'import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); '
                'data=json.load(sys.stdin); '
                'session=json.loads((p/"session.json").read_text()); '
                'data["status"]="failed" if session.get("telemetry_errors") or session.get("error") else data["status"]; '
                'f=(p/"restoration.json").open("x"); json.dump(data,f,indent=2); f.close(); '
                'f=(p/"final_status.json").open("x"); json.dump(data,f,indent=2); f.close(); print(json.dumps(data))')
            report = subprocess.run(['/usr/sbin/runuser', '-u', args.user, '--',
                                     '/usr/bin/python3', '-I', '-c', report_code,
                                     str(args.session_root / ident)],
                                    input=json.dumps(final), text=True, capture_output=True, check=False)
            if report.returncode:
                final['report_delivery_failed'] = True
                final['status'] = 'failed'
                print('User report delivery failed; root journal remains authoritative', file=sys.stderr)
            elif report.stdout:
                final['status'] = json.loads(report.stdout)['status']
            print(json.dumps(final), flush=True)
            os.close(coordination)
        # Keep original workload status even when restoration fails; journal is authoritative.
        return rc


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(125)
