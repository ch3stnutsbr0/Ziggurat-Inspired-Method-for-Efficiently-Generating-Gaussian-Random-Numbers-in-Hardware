"""Verify optional warmup, full-precision reporting, and pipe-only sample transfer."""
import importlib.util
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

new,old,driver=sys.argv[1:]
repo=Path(old).resolve().parents[1]
sys.path.insert(0,str(repo/'experiments'))
spec=importlib.util.spec_from_file_location('layers_comparison',driver)
layers=importlib.util.module_from_spec(spec)
spec.loader.exec_module(layers)


def transfer(executable,args):
    # Regression data is held only in RAM; no test sample files are created.
    read_fd,write_fd=os.pipe()
    p=subprocess.Popen([executable,*args,'--output',f'/dev/fd/{write_fd}'],
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(write_fd,))
    os.close(write_fd)
    with os.fdopen(read_fd,'rb') as pipe:
        data=pipe.read()
    out,err=p.communicate()
    assert p.returncode==0,(out,err)
    return data,out.decode()

for algorithm,n in [('basic',128),('trapezoid',8)]:
    count=65539  # exercises the final partial 65536-value output chunk
    run=layers.parameters(algorithm,n,count)
    base=['--algorithm',algorithm,'--layers',str(n),'--samples',str(count),'--seed','1']
    if algorithm=='trapezoid':
        base+=['--head','2','--tail','4']
    expected,_=transfer(old,base)
    plain,plain_log=transfer(new,base+['--report-json'])
    warmed,warmed_log=transfer(new,base+['--report-json','--warmup','1000'])
    assert len(expected)==count*8 and plain==expected and warmed==expected
    a=layers.parse(plain_log,run,0)
    b=layers.parse(warmed_log,run,1000)
    assert all(a[k]==b[k] for k in ('checksum','mean','variance'))
    values,summary,_=layers.collect_samples(new,run)
    assert values.tobytes()==expected
    assert math.isclose(summary['mean'],float(values.mean()),abs_tol=1e-10)
    assert math.isclose(summary['variance'],float(values.var(ddof=1)),abs_tol=1e-10)
    direct=subprocess.run(layers.command(new,run,warmup=1000),text=True,capture_output=True,check=True)
    direct_summary=layers.parse(direct.stdout,run,1000)
    assert direct_summary['checksum']==summary['checksum']
    disabled=subprocess.run([new,*base],text=True,capture_output=True,check=True)
    assert 'Warm-up samples:' not in disabled.stdout and 'BENCHMARK_JSON:' not in disabled.stdout
    print(algorithm,'warmup/disabled/golden stream/pipe/precision checks PASS')
for bad in [('junk',),('-1',),('18446744073709551616',),()]:
    p=subprocess.run([new,'--samples','2','--warmup',*bad],capture_output=True)
    assert p.returncode!=0
print('Warmup input validation PASS')
