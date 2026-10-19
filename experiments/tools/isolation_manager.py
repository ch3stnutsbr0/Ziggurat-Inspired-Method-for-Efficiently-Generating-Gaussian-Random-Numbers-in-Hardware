#!/usr/bin/env python3
"""Session CPU placement using supported systemd runtime APIs, never CPU frequency writes.

Privileged commands require an approved root-owned deployment and python -I.
inspect/plan/status/verify are read-only. activate wraps benchmark_session.py.
"""
import argparse
import array
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid

CGROUP = Path('/sys/fs/cgroup')
CPU = Path('/sys/devices/system/cpu')
STATE = Path('/var/lib/grng-isolation')
RESERVED = {7, 15}
UNIT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:@\\-]*\.(slice|scope|service|mount|socket|swap)$')


def cpus(text):
    result = set()
    for item in str(text).replace(' ', ',').split(','):
        if item:
            pair = item.split('-')
            result.update(range(int(pair[0]), int(pair[-1])+1))
    return result


def mask(values):
    return ','.join(map(str, sorted(values)))


def read(path):
    try:
        return path.read_text().strip()
    except OSError as exc:
        return {'unavailable': str(exc)}


def durable(path, value):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory = os.open(path.parent,os.O_DIRECTORY|os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def trusted(path):
    for entry in (path.absolute(), *path.absolute().parents):
        value = entry.lstat()
        if stat.S_ISLNK(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            raise ValueError(f'Administrative code/state must be root-owned and non-writable: {entry}')


class Systemd:
    def run(self, args, check=True):
        result = subprocess.run(['/usr/bin/systemctl', *args],capture_output=True,text=True,timeout=15)
        if check and result.returncode:
            raise ValueError(result.stderr.strip() or f'systemctl failed: {args}')
        return result

    def show(self, unit):
        if not UNIT.fullmatch(unit): raise ValueError('Invalid unit name')
        result = self.run(['show',unit,'--property=Id,LoadState,ActiveState,ControlGroup,AllowedCPUs,EffectiveCPUs,FragmentPath,DropInPaths,Description,Transient,Delegate,CPUAffinity'],check=False)
        info=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        if result.returncode and info.get('LoadState')!='not-found':
            listing=self.run(['list-units','--all','--full','--plain','--no-legend',unit],check=False)
            if listing.returncode==0 and not listing.stdout.strip():
                return {'LoadState':'not-found','ActiveState':'inactive'}
            raise ValueError(result.stderr.strip() or 'Unable to query systemd unit')
        return info

    def provenance(self, unit):
        data = self.show(unit)
        files = ([data['FragmentPath']] if data.get('FragmentPath') else []) + data.get('DropInPaths','').split()
        result = {}
        for filename in files:
            path = Path(filename)
            if not path.is_absolute(): raise ValueError('Invalid systemd configuration path')
            result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def set(self, unit, value):
        cpus(value)  # Validate before handing an argument to systemctl.
        self.run(['set-property','--runtime',unit,'AllowedCPUs='+value])

    def stop(self, unit):
        self.run(['stop',unit],check=False)
        info = self.show(unit)
        if info.get('ActiveState') not in ('inactive','failed',None) and info.get('LoadState')!='not-found':
            raise ValueError(f'Owned unit did not stop: {unit}')



def affinity_snapshot(proc=Path('/proc'), getter=None):
    getter = os.sched_getaffinity if getter is None else getter
    values, errors = [], []
    for process in proc.glob('[0-9]*'):
        if int(process.name)==os.getpid(): continue  # Supervisor affinity is managed separately.
        try:
            group=(process/'cgroup').read_text().strip().split('::',1)[1]
            for thread in (process/'task').iterdir():
                try:
                    text=(thread/'stat').read_text().rsplit(')',1)[1].split()
                    if int(text[6])&0x200000: continue  # Never alter kernel-thread affinities.
                    values.append({'pid':int(process.name),'tid':int(thread.name),'start':text[19],
                                   'cgroup':group,'affinity':sorted(getter(int(thread.name)))})
                except (FileNotFoundError,ProcessLookupError): pass
        except (FileNotFoundError,ProcessLookupError): pass
        except (OSError,ValueError,IndexError) as exc: errors.append(str(exc))
    return {'tasks':values,'errors':errors[:20]}


def audit_affinities(snapshot, proc=Path('/proc'), getter=None):
    getter=os.sched_getaffinity if getter is None else getter
    conflicts=[]
    for item in snapshot.get('tasks',[]):
        thread=proc/str(item['pid'])/'task'/str(item['tid'])
        try:
            start=(thread/'stat').read_text().rsplit(')',1)[1].split()[19]
            if start!=item['start']: continue  # PID/TID reuse, not the original thread.
            group=(proc/str(item['pid'])/'cgroup').read_text().strip().split('::',1)[1]
            actual=sorted(getter(item['tid']))
            if group!=item['cgroup'] or actual!=item['affinity']:
                conflicts.append({'tid':item['tid'],'reason':'Original affinity/cgroup differs; no ambiguous administrator state overwritten',
                                  'original_affinity':item['affinity'],'actual_affinity':actual})
        except (FileNotFoundError,ProcessLookupError): pass
        except (OSError,ValueError,IndexError) as exc: conflicts.append({'tid':item['tid'],'error':str(exc)})
    return {'verified':not conflicts,'conflicts':conflicts,'scope':'Known original userspace threads; exited/reused IDs ignored; new tasks have no original snapshot'}

def inspect(backend=None, root=CGROUP, cpu_root=CPU, proc_root=Path("/proc")):
    backend = backend or Systemd()
    online = read(cpu_root/'online')
    siblings = read(cpu_root/'cpu7/topology/thread_siblings_list')
    result = {'kernel':os.uname().release, 'hierarchy': read(Path('/proc/self/cgroup')), 'online': online, 'siblings': siblings,
              'root_controllers': read(root/'cgroup.controllers'),
              'root_subtree_control': read(root/'cgroup.subtree_control'),
              'root_effective': read(root/'cpuset.cpus.effective'),
              'root_partition': read(root/'cpuset.cpus.partition'),
              'root_tasks': read(root/'cgroup.procs'), 'units': {}, 'errors': [],
              'frequency_management': 'out_of_scope_no_writes',
              'tracefs_instances_readable':os.access('/sys/kernel/tracing/instances',os.R_OK),
              'tracefs_instances_writable':os.access('/sys/kernel/tracing/instances',os.W_OK),
              'partition_strategy': 'No direct writes to systemd-owned cgroups; isolated partition support is not established'}
    try:
        if cpus(siblings)!=RESERVED or not RESERVED <= cpus(online):
            result['errors'].append('CPU7/15 topology or online state does not match the expected physical core')
        if 'cpuset' not in str(result['root_controllers']).split():
            result['errors'].append('cpuset controller unavailable')
        if not RESERVED <= cpus(result['root_effective']):
            result['errors'].append('Root effective cpuset excludes the reserved core')
    except (ValueError,TypeError):
        result['errors'].append('Topology/effective cpuset unavailable')
    if isinstance(online,str) and cpus(online)!=set(range(16)):
        result['errors'].append('Unexpected online topology; expected exactly CPUs0-15')
    housekeeping = cpus(online) - RESERVED if isinstance(online,str) else set()
    result['housekeeping'] = sorted(housekeeping)
    result['descendant_effective_cpus'] = {}
    def scan_error(exc): result['errors'].append('Cgroup descendant inspection incomplete: '+str(exc))
    for directory, children, files in os.walk(root, onerror=scan_error):
        path=Path(directory)
        if path==root or 'cpuset.cpus.effective' not in files: continue
        effective=read(path/'cpuset.cpus.effective')
        result['descendant_effective_cpus'][str(path.relative_to(root))]=effective
        try:
            if not cpus(effective) & housekeeping:
                result['errors'].append(f'{path}: descendant has no usable housekeeping CPU; refusing possible service starvation')
        except (ValueError,TypeError): result['errors'].append(f'{path}: descendant effective cpuset unavailable')
    if not housekeeping: result['errors'].append('No housekeeping CPUs')
    for child in sorted(root.iterdir()):
        if not child.is_dir(): continue
        if not UNIT.fullmatch(child.name):
            result['errors'].append(f'Unmanaged/unknown root cgroup: {child.name}')
            continue
        try:
            value = backend.show(child.name)
            value['provenance'] = backend.provenance(child.name)
            value['partition_file']=read(child/'cpuset.cpus.partition')
            value['cpuset_effective_file'] = read(child/'cpuset.cpus.effective')
            result['units'][child.name] = value
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            result['errors'].append(f'{child.name}: {exc}')
    root_tasks = result['root_tasks']
    result['task_affinities']=affinity_snapshot(proc_root)
    if result['task_affinities']['errors']: result['errors'].append('Userspace task-affinity snapshot is incomplete')
    result['root_task_affinities'] = {}
    if not isinstance(root_tasks,str):
        result['errors'].append('Root task visibility unavailable')
    else:
        for pid_text in root_tasks.split():
            if pid_text=='0':
                result['errors'].append('Root cgroup contains namespace-hidden PIDs; accounting cannot be verified')
                break
            try:
                pid = int(pid_text)
                text = (proc_root/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
                kernel = bool(int(text[6]) & 0x200000)
                affinity = sorted(os.sched_getaffinity(pid))
                result['root_task_affinities'][pid_text] = {'kernel_thread':kernel,'affinity':affinity}
                if not kernel and set(affinity)&RESERVED:
                    result['errors'].append(f'Root userspace task {pid} can run on the reserved core; not moved automatically')
            except FileNotFoundError:
                result['errors'].append(f'Root task {pid_text} disappeared during inspection; repeat preflight')
            except (OSError,ValueError,IndexError) as exc:
                result['errors'].append(f'Root task {pid_text}: {exc}')
    try:
        if read(cpu_root/'cpu7/topology/core_id')!=read(cpu_root/'cpu15/topology/core_id') or read(cpu_root/'cpu7/topology/physical_package_id')!=read(cpu_root/'cpu15/topology/physical_package_id') or cpus(read(cpu_root/'cpu15/topology/thread_siblings_list'))!=RESERVED:
            result['errors'].append('CPU7 and CPU15 physical core/socket mapping mismatch')
    except (ValueError,TypeError): result['errors'].append('Full sibling topology is unavailable')
    return result


def plan(state):
    errors = list(state['errors'])
    changes = []
    available = cpus(state['root_effective']) if isinstance(state['root_effective'],str) else set()
    housekeeping = set(state['housekeeping'])
    for name, info in state['units'].items():
        original = info.get('AllowedCPUs','')
        effective_file=info.get('cpuset_effective_file')
        effective = effective_file if isinstance(effective_file,str) and effective_file else info.get('EffectiveCPUs') or original or mask(available)
        target = cpus(effective) & housekeeping
        if not target:
            errors.append(f'{name}: housekeeping intersection is empty; refusing to starve essential services')
        changes.append({'unit':name,'original':original,'target':mask(target),
                        'original_provenance':info['provenance'],'original_effective':effective,
                        'expected_provenance':None,'phase':'untouched'})
    for task in state.get('task_affinities',{}).get('tasks',[]):
        group=task['cgroup'].strip('/').split('/')[0]
        if group in state['units'] and not set(task['affinity'])&housekeeping:
            errors.append(f"TID{task['tid']}: explicit affinity excludes housekeeping; not widened automatically")
    for essential in ('system.slice','user.slice','init.scope'):
        if essential not in state['units']: errors.append(f'Essential unit not verified: {essential}')
    return {'status':'blocked' if errors else 'ready_for_explicit_approval','errors':errors,
            'changes':changes,'reserved':[7,15],'benchmark_cpu':7,'housekeeping':sorted(housekeeping),
            'scope':'Runtime systemd CPU placement constraints, not exclusive scheduler/IRQ isolation',
            'partition':'No isolated partition created; unsupported/unverified hierarchy is never assumed exclusive',
            'frequency_writes':[], 'state':state}


def effective_verify(data, root=CGROUP, proc_root=Path('/proc'), getter=None):
    errors = []
    getter=os.sched_getaffinity if getter is None else getter
    try:
        for pid in (root/'cgroup.procs').read_text().split():
            if pid=='0':
                errors.append('Root task visibility became namespace-hidden'); break
            fields=(proc_root/pid/'stat').read_text().rsplit(')',1)[1].split()
            if not int(fields[6])&0x200000 and set(getter(int(pid)))&RESERVED:
                errors.append(f'Root userspace task {pid} can execute on the reserved core')
    except (OSError,ValueError,IndexError) as exc:
        errors.append('Root userspace coverage unavailable during verification: '+str(exc))
    for change in data['changes']:
        current = read(root/change['unit']/'cpuset.cpus.effective')
        try:
            actual = cpus(current)
            target = cpus(change['target'])
            if not actual or not actual<=target or actual&RESERVED:
                errors.append(f"{change['unit']}: effective cpuset {current} violates housekeeping constraints")
        except (ValueError,TypeError): errors.append(f"{change['unit']}: effective cpuset unavailable")
    owned=data.get('owned_units',[])
    for name in owned:
        path=root/name if name.endswith('.slice') else root/next((n for n in owned if n.endswith('.slice')),'')/name
        if path.exists():
            try:
                if cpus(read(path/'cpuset.cpus.effective'))!={7}: errors.append(f'{name}: benchmark effective cpuset is not exactly CPU7')
            except (ValueError,TypeError): errors.append(f'{name}: benchmark effective cpuset unavailable')
    known = {item['unit'] for item in data['changes']} | set(data.get('owned_units',[]))
    unexpected = [p.name for p in root.iterdir() if p.is_dir() and p.name not in known]
    if unexpected: errors.append('Unexpected root cgroups: '+','.join(unexpected))
    return {'verified':not errors,'errors':errors,'partition_exclusive':False,
            'root_kernel_threads_unconstrained':True,'hardware_interrupts_unconstrained':True,
            'root_visibility_verified':not data.get('state',{}).get('errors',[])}


def apply(data, backend, path, cancelled=None):
    for change in data['changes']:
        if cancelled and cancelled(): raise ValueError('Isolation activation cancelled between property operations')
        live = backend.show(change['unit'])
        if live.get('AllowedCPUs','')!=change['original'] or backend.provenance(change['unit'])!=change['original_provenance']:
            raise ValueError(f"Pre-apply administrator conflict: {change['unit']}")
        change['phase']='intent'
        durable(path,data)
        backend.set(change['unit'],change['target'])
        if cpus(backend.show(change['unit']).get('AllowedCPUs','')) != cpus(change['target']):
            raise ValueError('Requested AllowedCPUs readback failed')
        change['expected_provenance']=backend.provenance(change['unit'])
        change['phase']='applied'
        durable(path,data)


def restore(data, backend, checkpoint=None):
    errors, restored = [], []
    for change in reversed(data['changes']):
        if change['phase']=='untouched': continue
        try:
            if not UNIT.fullmatch(change['unit']): raise ValueError('Invalid recorded unit name')
            live = backend.show(change['unit']).get('AllowedCPUs','')
            if change['phase']=='intent':
                raise ValueError('Ambiguous apply intent; explicit review/acknowledgment of unchanged original state is required')
            files = backend.provenance(change['unit'])
            if cpus(live)==cpus(change['original']) and files in (change['original_provenance'],change.get('restored_provenance')):
                restored.append(change['unit']); continue
            if change['expected_provenance'] is None:
                raise ValueError('Interrupted apply has no verified configuration provenance; manual conflict review required')
            if cpus(live)!=cpus(change['target']) or files!=change['expected_provenance']:
                raise ValueError('Administrator/configuration conflict; refusing to overwrite current state')
            change['phase']='restore_intent'
            if checkpoint: checkpoint()
            backend.set(change['unit'],change['original'])
            if cpus(backend.show(change['unit']).get('AllowedCPUs',''))!=cpus(change['original']):
                raise ValueError('Restored property readback mismatch')
            change['phase']='restored'
            # Record new provenance so recovery can resume after interrupted restoration.
            change['restored_provenance']=backend.provenance(change['unit'])
            if checkpoint: checkpoint()
            restored.append(change['unit'])
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            errors.append(f"{change['unit']}: {exc}")
    return {'verified':not errors,'errors':errors,'restored_units':restored,
            'semantics':'Original AllowedCPUs values restored through systemd API',
            'runtime_override_residue_possible':True,
            'note':'Generated /run property drop-ins/controller enablement are not erased with broad revert; no persistent /etc changes'}


def recv_request(sock):
    raw, ancillary, flags, address = sock.recvmsg(65536,socket.CMSG_SPACE(2*array.array('i').itemsize))
    if not raw: raise ValueError('Benchmark proxy disconnected before requesting execution')
    fds = array.array('i')
    for level,kind,value in ancillary:
        if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS: fds.frombytes(value[:len(value)-len(value)%fds.itemsize])
    if flags & (socket.MSG_TRUNC|socket.MSG_CTRUNC) or len(fds)!=2:
        for fd in fds: os.close(fd)
        raise ValueError('Invalid/truncated benchmark proxy request')
    try:
        request=json.loads(raw)
        if not isinstance(request,dict): raise ValueError('Proxy request must be an object')
        return request,list(fds)
    except (ValueError,TypeError):
        for fd in fds: os.close(fd)
        raise


def proxy(command, fd):
    if os.geteuid()==0: raise ValueError('Proxy must run as an unprivileged user')
    sock = socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET,fileno=os.dup(fd))
    sock.settimeout(20)  # Supervisor sends heartbeats during long workloads.
    sock.sendmsg([json.dumps({'command':command}).encode()],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[1,2]))])
    while True:
        try:
            message = json.loads(sock.recv(65536))
            if message.get('heartbeat'): continue
            break
        except BlockingIOError:
            select.select([sock],[],[],1)
    if 'error' in message:
        print(message['error'],file=sys.stderr)
        return 125
    return int(message['exit_status'])



def cancel_request(fd):
    # Passed descriptor is already a connected local SOCK_SEQPACKET capability.
    # Avoid socket reconstruction/getsockopt (not available in some sandboxes).
    original = None
    try:
        original=os.get_blocking(fd)
        os.set_blocking(fd,False)
        os.write(fd,json.dumps({'cancel':True}).encode())
    except OSError:
        pass  # Supervisor exit detection/finally is the independent fallback.
    finally:
        if original is not None:
            try: os.set_blocking(fd,original)
            except OSError: pass


def worker(command, cpu, placement, expected_unit):
    # Runs only AS THE BENCHMARK USER inside the transient service.
    if os.geteuid()==0: raise ValueError('Worker must run as an unprivileged user')
    group = Path('/proc/self/cgroup').read_text().strip().split('::',1)[1]
    if Path(group).name!=expected_unit: raise ValueError('Benchmark unit placement mismatch')
    effective = cpus((CGROUP/group.lstrip('/')/'cpuset.cpus.effective').read_text())
    if effective!={cpu} or set(os.sched_getaffinity(0))!={cpu}: raise ValueError('Benchmark effective cpuset/affinity is not CPU7')
    destination=Path(placement)
    temporary=destination.with_suffix('.tmp')
    owned=False
    try:
        with temporary.open('x') as stream:
            owned=True
            json.dump({'pid':os.getpid(),'unit':expected_unit,'cgroup':group,'effective':[cpu],
                       'affinity':[cpu],'start_ticks':pid_start(os.getpid()),'monotonic_ns':time.monotonic_ns(),'verified':True},stream)
            stream.flush(); os.fsync(stream.fileno())
        # Publish a complete document atomically, without replacing an existing path.
        os.link(temporary,destination)
    finally:
        if owned: temporary.unlink(missing_ok=True)
    # Reuse the original project's argv/validation, only after the unit constraint is checked.
    import cpu_benchmark as common
    argv = common.affinity_argv(cpu,command)
    os.execv(argv[0],argv)


def trace_configuration(instance):
    return {name:read(instance/name) for name in (
        "tracing_on","trace_clock","tracing_cpumask","buffer_size_kb",
        "events/sched/sched_switch/enable","events/sched/sched_migrate_task/enable")}


def trace_prepare(ident, checkpoint=None):
    parent = Path('/sys/kernel/tracing/instances')
    instance = parent/('grng_'+ident.replace('-',''))
    instance.mkdir()
    if checkpoint: checkpoint(instance)
    try:
        for name,value in [('tracing_on','0'),('trace_clock','mono'),('buffer_size_kb','256'),
                           ('tracing_cpumask','8080'),('events/sched/sched_switch/enable','1'),
                           ('events/sched/sched_migrate_task/enable','1'),('tracing_on','1')]:
            (instance/name).write_text(value+'\n')
        config=trace_configuration(instance)
        if config['tracing_on']!='1' or '[mono]' not in str(config['trace_clock']) or int(str(config['tracing_cpumask']).replace(',',''),16)!=0x8080 or any(config[name]!='1' for name in ('events/sched/sched_switch/enable','events/sched/sched_migrate_task/enable')):
            raise ValueError('Trace configuration readback failed')
        return instance,os.open(instance/'trace_pipe',os.O_RDONLY|os.O_NONBLOCK)
    except BaseException:
        try: (instance/'tracing_on').write_text('0\n'); instance.rmdir()
        except OSError: pass
        raise


def pid_start(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]


def signal_identified(pid, start, signum):
    """Pin process identity before comparing /proc lifetime; never signal a reused PID."""
    if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
        raise ValueError('pidfd signaling unavailable; refusing racy administrative PID signal')
    fd=os.pidfd_open(pid,0)
    try:
        if pid_start(pid)!=start: raise ValueError('Supervisor PID lifetime mismatch')
        signal.pidfd_send_signal(fd,signum)
    finally:
        os.close(fd)


def report_as_user(user, directory, payload, tools=None):
    code = ('import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); d=json.load(sys.stdin); '
            'sys.path.insert(0,sys.argv[2]); import interference_monitor as m; '
            'quality=m.final_quality(json.loads((p/"benchmark_quality.json").read_text()),d["final"]); '
            '(p/"benchmark_quality_final.json").open("x").write(json.dumps(quality,indent=2)); '
            '[(p/name).open("x").write(json.dumps(d[key],indent=2)) for name,key in '
            '[("restoration.json","restoration"),("isolation_final.json","final")]]')
    result = subprocess.run(['/usr/sbin/runuser','-u',user,'--','/usr/bin/python3','-I','-c',code,str(directory),str(tools)],
                            input=json.dumps(payload),text=True,capture_output=True,timeout=20)
    return {'delivered':result.returncode==0,'error':result.stderr if result.returncode else None}





def stop_benchmark(data, backend):
    unit=next(name for name in data['owned_units'] if name.endswith('.service'))
    info=backend.show(unit)
    if info.get('LoadState')=='not-found': return
    if info.get('Description')!='GRNG isolation '+data['id']:
        raise ValueError('Benchmark unit identity conflict; refusing to stop unrelated work')
    backend.stop(unit)

def stop_owned(data, backend):
    errors=[]
    for owned in reversed(data['owned_units']):
        try:
            info=backend.show(owned)
            if info.get('LoadState')=='not-found': continue
            if owned.endswith('.service'):
                if not data.get('workload_requested'): continue
                if info.get('Description')!='GRNG isolation '+data['id']:
                    raise ValueError('Owned service identity conflict')
            else:
                if not data.get('slice_start_intent'): continue
                if data.get('slice_provenance') is None:
                    raise ValueError('Slice creation was interrupted before provenance verification; manual review required')
                if backend.provenance(owned)!=data['slice_provenance']:
                    raise ValueError('Owned slice configuration conflict')
            backend.stop(owned)
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            errors.append(str(exc))
    return errors

def signal_group(pid, signum):
    try: os.killpg(pid,signum)
    except ProcessLookupError: pass

def activate(args, backend):
    account = pwd.getpwnam(args.user)
    if account.pw_uid==0: raise ValueError('Benchmark user must not be root')
    command = args.command[1:] if args.command[:1]==['--'] else args.command
    if not command or '--overwrite' in command: raise ValueError('A foreground benchmark argv without --overwrite is required')
    current = inspect(backend)
    data = plan(current)
    if data['errors']: raise ValueError('Isolation preflight failed: '+'; '.join(data['errors']))
    ident = str(uuid.uuid4()); prefix='grng'+ident.replace('-','')
    data.update(id=ident,status='prepared',user=args.user,command=command,
                boot_id=read(Path('/proc/sys/kernel/random/boot_id')),
                supervisor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                session_root=str(args.session_root.absolute()), owned_units=[prefix+'.slice',prefix+'.service'],
                supervisor_pid=os.getpid(),supervisor_start=pid_start(os.getpid()),controller_pid=None,
                controller_start=None,trace_instance=None, trace_requested=args.monitor_mode=='diagnostic',
                session_timeout_seconds=getattr(args,'session_timeout',None),controller_startup_timeout_seconds=60)
    journal = STATE/(ident+'.json')
    lockfd = os.open(args.session_root/'.controller.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    info = os.fstat(lockfd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=account.pw_uid: raise ValueError('Invalid user coordination lock')
    fcntl.flock(lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    original_affinity = sorted(os.sched_getaffinity(0))
    data['supervisor_original_affinity']=original_affinity
    durable(journal,data)
    unit, controller, trace_fd, instance = None,None,None,None
    server,client = socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
    server.setblocking(False)
    signals=[]
    def cancel(sig,frame): signals.append(sig)
    previous={sig:signal.signal(sig,cancel) for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
    rc=125; cleanup_errors=[]
    try:
        os.sched_setaffinity(0,set(data['housekeeping']))
        # All mutations use documented systemd APIs, never cgroup filesystem writes.
        existing=backend.show(prefix+'.slice')
        implicit=(existing.get('ActiveState')=='inactive' and not existing.get('FragmentPath') and not existing.get('DropInPaths') and not (CGROUP/(prefix+'.slice')).exists())
        if existing.get('LoadState')!='not-found' and not implicit:
            raise ValueError('Unique slice name already exists; refusing to reuse it')
        data['slice_start_intent']=True; durable(journal,data)
        if signals: raise ValueError('Isolation activation cancelled before slice creation')
        backend.run(['start',prefix+'.slice'])
        backend.set(prefix+'.slice','7')
        data['slice_provenance']=backend.provenance(prefix+'.slice')
        durable(journal,data)
        apply(data,backend,journal,cancelled=lambda:bool(signals))
        verified=effective_verify(data)
        if not verified['verified']: raise ValueError(str(verified['errors']))
        data['status']='active'; durable(journal,data)
        if args.monitor_mode=='diagnostic':
            if not args.approve_scheduler_tracing: raise ValueError('Diagnostic tracing requires explicit separate approval')
            # Intent journal exists before tracefs writes; only this unique instance is touched.
            data['trace_instance']='grng_'+ident.replace('-',''); durable(journal,data)
            def record_trace_created(node):
                data['trace_inode']=[node.stat().st_dev,node.stat().st_ino]; durable(journal,data)
            instance,trace_fd=trace_prepare(ident,record_trace_created)
            data['trace_expected_config']=trace_configuration(instance)
            data['trace_config_verified']=True
            data['trace_initial_stats']={str(p.relative_to(instance)):read(p) for p in instance.glob('per_cpu/cpu*/stats')}
            durable(journal,data)
        active={**verified,'housekeeping':data['housekeeping'],'id':ident,'changes':data['changes'],
                'owned_units':data['owned_units'],'root':str(CGROUP),'journal':str(journal)}
        env=dict(os.environ,GRNG_ISOLATION_STATE=json.dumps(active),GRNG_ISOLATION_ID=ident,
                 GRNG_ISOLATION_SOCKET=str(client.fileno()),GRNG_SESSION_LOCK_FD=str(lockfd),
                 GRNG_SESSION_ROOT=str(args.session_root.absolute()))
        inherited=[client.fileno(),lockfd]
        if trace_fd is not None:
            env['GRNG_ISOLATION_TRACE_FD']=str(trace_fd); inherited.append(trace_fd)
        launch=['/usr/sbin/runuser','-u',args.user,'--',args.python,'-B',str(args.controller),
                '--mode','bios','--cpu','7','--isolation','active','--monitor-mode',args.monitor_mode,
                '--telemetry-interval',str(args.interval),'--',*command]
        if args.quality_thresholds:
            boundary=launch.index('--',launch.index(str(args.controller)))
            launch[boundary:boundary]=['--quality-thresholds',str(args.quality_thresholds)]
        if signals: raise ValueError('Isolation activation cancelled before controller startup')
        controller=subprocess.Popen(launch,env=env,start_new_session=True,pass_fds=tuple(inherited))
        data.update(controller_pid=controller.pid,controller_start=pid_start(controller.pid)); durable(journal,data)
        client.close()
        requested=False; sent=False; interrupted_at=None
        supervisor_started=time.monotonic(); heartbeat=supervisor_started
        timeout=getattr(args,'session_timeout',None)
        while controller.poll() is None:
            now=time.monotonic()
            if not requested and now-supervisor_started>60:
                raise ValueError('Controller did not request workload within 60 seconds')
            if timeout is not None and now-supervisor_started>timeout:
                raise ValueError('Explicit session deadline exceeded; terminating owned workload')
            if requested and not sent and now-heartbeat>=5:
                server.send(json.dumps({'heartbeat':True}).encode()); heartbeat=now
            if signals:
                if interrupted_at is None:
                    interrupted_at=time.monotonic(); signal_group(controller.pid,signals[-1])
                    stop_benchmark(data,backend)
                elif time.monotonic()-interrupted_at>10: raise ValueError('Controller did not exit after cancellation; bounded teardown required')
                elif time.monotonic()-interrupted_at>8: signal_group(controller.pid,signal.SIGKILL)
                time.sleep(.05)
                continue  # Never accept/launch a new workload after cancellation.
            if not requested:
                try: request,fds=recv_request(server)
                except BlockingIOError: pass
                else:
                    try:
                        if request.get('command')!=command: raise ValueError('Proxy argv differs from explicitly approved command')
                        if not effective_verify(data)['verified']: raise ValueError('Isolation drift before workload launch')
                        path=args.session_root/ident
                        worker_source=args.controller.parent/'isolation_manager.py'
                        data['workload_requested']=True; durable(journal,data)
                        unitargv=['/usr/bin/systemd-run','--wait','--pipe','--collect','--service-type=exec',
                                  '--unit='+prefix+'.service','--slice='+prefix+'.slice',
                                  '--description=GRNG isolation '+ident,
                                  '--property=AllowedCPUs=7','--property=CPUAffinity=7',
                                  '--property=Restart=no','--property=KillMode=control-group','--property=SendSIGKILL=yes','--property=TimeoutStopSec=5s',
                                  '--uid='+str(account.pw_uid),'--gid='+str(account.pw_gid),
                                  '--working-directory='+str(Path.cwd()),'--',args.python,'-B',str(worker_source),
                                  'worker','--placement',str(path/'placement.json'),'--unit',prefix+'.service','--',*command]
                        unitargv.insert(1,'--property=TimeoutStartSec=15s')
                        if timeout is not None: unitargv.insert(1,'--property=RuntimeMaxSec='+str(timeout)+'s')
                        unit=subprocess.Popen(unitargv,stdout=fds[0],stderr=fds[1],start_new_session=True)
                        requested=True
                    finally:
                        for fd in fds: os.close(fd)
            if requested and unit is not None and unit.poll() is None:
                try:
                    packet=server.recv(4096)
                    if not packet: raise ValueError('Benchmark broker disconnected during workload')
                    if packet and json.loads(packet).get('cancel') is True:
                        data['workload_cancel_requested']=True; durable(journal,data)
                        stop_benchmark(data,backend)
                except BlockingIOError: pass
            if unit is not None and unit.poll() is not None and not sent:
                status=unit.returncode if unit.returncode>=0 else 128-unit.returncode
                try: server.send(json.dumps({'exit_status':status}).encode())
                except BrokenPipeError: pass
                sent=True
            time.sleep(.05)
        rc=controller.wait(timeout=2); rc=rc if rc>=0 else 128-rc
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        data['error']=str(exc)
    finally:
        for sig in previous: signal.signal(sig,signal.SIG_IGN)
        try:
            if controller is not None and controller.poll() is None:
                signal_group(controller.pid,signal.SIGTERM)
                try: controller.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    signal_group(controller.pid,signal.SIGKILL)
                    try: controller.wait(timeout=2)
                    except subprocess.TimeoutExpired: cleanup_errors.append('Controller remains after SIGKILL; manual recovery required')
            cleanup_errors.extend(stop_owned(data,backend))
            if unit is not None and unit.poll() is None:
                try: unit.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    signal_group(unit.pid,signal.SIGTERM)
                    try: unit.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        signal_group(unit.pid,signal.SIGKILL)
                        try: unit.wait(timeout=2)
                        except subprocess.TimeoutExpired: cleanup_errors.append('Unit launcher remains after SIGKILL')
                    cleanup_errors.append('Transient-unit launcher did not acknowledge normal stop; explicit recovery review required')
            if instance is None and data.get('trace_instance'):
                leftover=Path('/sys/kernel/tracing/instances')/data['trace_instance']
                if leftover.exists(): cleanup_errors.append('Incomplete trace setup remains; explicit recovery review required')
            if instance:
                try:
                    if trace_configuration(instance)!=data.get('trace_expected_config'):
                        raise ValueError('Trace configuration conflict; preserving current administrator state')
                    data['trace_stop_intent']=True; durable(journal,data)
                    (instance/'tracing_on').write_text('0\n')
                    data['trace_stats']={str(p.relative_to(instance)):read(p) for p in instance.glob('per_cpu/cpu*/stats')}
                    if trace_fd is not None: os.close(trace_fd); trace_fd=None
                    instance.rmdir()
                except (OSError,ValueError) as exc: cleanup_errors.append('Trace cleanup: '+str(exc))
            restoration=restore(data,backend,lambda:durable(journal,data)) if not cleanup_errors else {'verified':False,'errors':cleanup_errors,'blocked':'Owned workload/trace teardown must be verified before restoring constraints'}
            affinity=audit_affinities(data['state'].get('task_affinities',{}))
            restoration['affinity_audit']=affinity
            restoration['verified']=restoration['verified'] and affinity['verified']
            data.update(restoration=restoration,status='restored' if restoration['verified'] else 'restore_failed',exit_status=rc)
            durable(journal,data)
            try:
                delivery=report_as_user(args.user,args.session_root/ident,{'restoration':restoration,'final':data},args.controller.parent)
            except (OSError,subprocess.SubprocessError) as exc:
                delivery={'delivered':False,'error':str(exc)}
            print(json.dumps({'id':ident,'exit_status':rc,'restoration':restoration,'delivery':delivery}),flush=True)
        finally:
            if trace_fd is not None: os.close(trace_fd)
            server.close(); client.close(); os.close(lockfd)
            os.sched_setaffinity(0,original_affinity)
            for sig,handler in previous.items(): signal.signal(sig,handler)
    return rc


def validate_journal(data):
    uuid.UUID(data['id'])
    if data['reserved']!=[7,15] or data['benchmark_cpu']!=7: raise ValueError('Unexpected journal CPU scope')
    for change in data['changes']:
        if not UNIT.fullmatch(change['unit']): raise ValueError('Invalid recorded unit')
        for value in ('original','target'): cpus(change[value])
        if not cpus(change['target']) or cpus(change['target'])&RESERVED: raise ValueError('Unsafe recorded housekeeping target')
    if any(not name.startswith('grng'+data['id'].replace('-','')) for name in data['owned_units']):
        raise ValueError('Invalid owned unit identity')



def boot_matches(data):
    current=read(Path('/proc/sys/kernel/random/boot_id'))
    return isinstance(current,str) and data.get('boot_id')==current


def acknowledge_original_intents(data, backend):
    reviewed=[]
    for change in data['changes']:
        if change['phase']!='intent': continue
        live=backend.show(change['unit']).get('AllowedCPUs','')
        if cpus(live)!=cpus(change['original']) or backend.provenance(change['unit'])!=change['original_provenance']:
            raise ValueError('Ambiguous state does not exactly match original value/provenance; preserving it for manual review')
        change['phase']='restored'; change['restored_provenance']=change['original_provenance']
        reviewed.append(change['unit'])
    data['reviewed_original_intents']={'units':reviewed,'monotonic_ns':time.monotonic_ns()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('inspect','plan','activate','verify','deactivate','recover','status','proxy','worker'))
    parser.add_argument('--approve-isolation',action='store_true')
    parser.add_argument('--approve-scheduler-tracing',action='store_true')
    parser.add_argument('--acknowledge-new-boot',action='store_true')
    parser.add_argument('--acknowledge-unchanged-original',action='store_true')
    parser.add_argument('--monitor-mode',choices=('lightweight','diagnostic'),default='lightweight')
    parser.add_argument('--interval',type=float,default=1.0)
    parser.add_argument('--session-timeout',type=float,help='Optional wall-time deadline including controller startup; seconds')
    parser.add_argument('--quality-thresholds',type=Path)
    parser.add_argument('--user')
    parser.add_argument('--controller',type=Path)
    parser.add_argument('--python',default='/usr/bin/python3')
    parser.add_argument('--session-root',type=Path)
    parser.add_argument('--journal')
    parser.add_argument('--placement',type=Path)
    parser.add_argument('--unit')
    # REMAINDER after positional action would swallow options: split explicit -- argv.
    raw=sys.argv[1:]
    command=raw[raw.index('--')+1:] if '--' in raw else []
    options=raw[:raw.index('--')] if '--' in raw else raw
    # Parse normal options first, append only the separately delimited command.
    args=parser.parse_args(options); args.command=command
    backend=Systemd()
    if args.session_timeout is not None and (not math.isfinite(args.session_timeout) or not 10<=args.session_timeout<=86400):
        raise ValueError('Session timeout must be finite and between 10 and 86400 seconds')
    if not math.isfinite(args.interval) or args.interval<0.2: raise ValueError('Monitoring interval must be finite and at least 0.2 seconds')
    if args.action=='proxy': return proxy(command,int(os.environ['GRNG_ISOLATION_SOCKET']))
    if args.action=='worker': return worker(command,7,args.placement,args.unit)
    if args.action in ('inspect','plan'):
        state=inspect(backend); print(json.dumps(state if args.action=='inspect' else plan(state),indent=2)); return 0
    if args.action=='status' and not args.journal:
        try:
            result={'unavailable':'Administrative journal access required'} if STATE.exists() and not os.access(STATE,os.R_OK|os.X_OK) else [p.stem for p in STATE.glob('*.json')]
        except OSError: result={'unavailable':'Administrative journal access required'}
        print(json.dumps({'journals':result,'activation_performed':False})); return 0
    if args.action in ('verify','status'):
        if not args.journal:
            state=inspect(backend); print(json.dumps({'verified':False,'preflight':plan(state)},indent=2)); return 0
        ident=str(uuid.UUID(args.journal)); path=STATE/(ident+'.json')
        data=json.loads(path.read_text()); validate_journal(data)
        print(json.dumps(data if args.action=='status' else effective_verify(data) if boot_matches(data) else {'verified':False,'reason':'Journal is from another boot; no replay is permitted'},indent=2)); return 0
    if os.geteuid()!=0 or not sys.flags.isolated or not args.approve_isolation:
        raise ValueError('Mutation requires explicit approval, root-owned deployment and an existing administrative terminal with python -I; no sudo is invoked')
    trusted(Path(__file__))
    if not STATE.exists(): STATE.mkdir(mode=0o700)
    trusted(STATE)
    if args.action=='deactivate' and args.journal:
        path=STATE/(str(uuid.UUID(args.journal))+'.json'); trusted(path); data=json.loads(path.read_text()); validate_journal(data)
        if not boot_matches(data): raise ValueError('Stale boot journal: use recover --acknowledge-new-boot after manual inspection; no process will be signalled')
        pid=data.get('supervisor_pid')
        if pid and Path(f'/proc/{pid}').exists() and pid_start(pid)==data.get('supervisor_start'):
            signal_identified(pid,data.get('supervisor_start'),signal.SIGTERM)
            print(json.dumps({'requested':'deactivate','id':data['id'],'note':'Active supervisor will restore; inspect journal/status afterward'})); return 0
    fd=os.open(STATE/'isolation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action in ('recover','deactivate'):
            path=STATE/(str(uuid.UUID(args.journal))+'.json'); trusted(path)
            data=json.loads(path.read_text()); validate_journal(data)
            if not boot_matches(data):
                if not args.acknowledge_new_boot: raise ValueError('Boot changed; refusing stale replay. Inspect current state, then explicitly acknowledge the new boot')
                data.update(status='reconciled_new_boot',restoration={'verified':False,'status':'not_replayed_across_boot','current_inspection':inspect(backend)})
                durable(path,data); print(json.dumps({'status':'reconciled_new_boot','settings_written':False})); return 0
            if data.get('controller_pid') and Path(f"/proc/{data['controller_pid']}").exists():
                raise ValueError('Controller PID exists; inspect PID identity/workload before recovery')
            session_root=Path(data['session_root'])
            coordination=os.open(session_root/'.controller.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            try:
                info=os.fstat(coordination)
                if info.st_uid!=pwd.getpwnam(data['user']).pw_uid or not stat.S_ISREG(info.st_mode):
                    raise ValueError('Recovery coordination lock identity conflict')
                fcntl.flock(coordination,fcntl.LOCK_EX|fcntl.LOCK_NB)
                errors=stop_owned(data,backend)
                if errors: raise ValueError(str(errors))
                trace=data.get('trace_instance')
                if trace:
                    if not re.fullmatch('grng_[0-9a-f]{32}',trace): raise ValueError('Invalid trace instance')
                    instance=Path('/sys/kernel/tracing/instances')/trace
                    if instance.exists():
                        node=instance.stat()
                        if data.get('trace_inode')!=[node.st_dev,node.st_ino]: raise ValueError('Trace instance ownership identity conflict')
                        expected=dict(data.get('trace_expected_config') or {})
                        actual=trace_configuration(instance)
                        if data.get('trace_stop_intent') and actual.get('tracing_on')=='0': expected['tracing_on']='0'
                        if not expected or actual!=expected: raise ValueError('Trace state conflict; manual review required')
                        (instance/'tracing_on').write_text('0\n'); instance.rmdir()
                if args.acknowledge_unchanged_original:
                    acknowledge_original_intents(data,backend); durable(path,data)
                restoration=restore(data,backend,lambda:durable(path,data))
                affinity=audit_affinities(data['state'].get('task_affinities',{}))
                restoration['affinity_audit']=affinity
                restoration['verified']=restoration['verified'] and affinity['verified']
            finally: os.close(coordination)
            data.update(restoration=restoration,status='restored' if restoration['verified'] else 'restore_failed')
            durable(path,data); print(json.dumps(restoration,indent=2)); return 0 if restoration['verified'] else 1
        if not args.user or not args.controller or not args.session_root: raise ValueError('activate requires --user, --controller and --session-root')
        if args.monitor_mode=='diagnostic' and not args.approve_scheduler_tracing: raise ValueError('Diagnostic tracing needs separate explicit approval')
        for path in STATE.glob('*.json'):
            if json.loads(path.read_text()).get('status') not in ('restored','reconciled_new_boot'): raise ValueError(f'Unfinished journal requires recovery: {path.stem}')
        return activate(args,backend)


if __name__=='__main__':
    try: raise SystemExit(main())
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr); raise SystemExit(125)
