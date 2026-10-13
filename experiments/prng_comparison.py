"""Run the focused four-way comparison; store summaries, never raw samples.
Build with make -C c O2, then run python3 experiments/prng_comparison.py.
"""
import argparse
import copy
import csv
import json
from pathlib import Path
import platform
import statistics
import subprocess

from runner import build_runs, expand_configurations
from utils import load_config, sha256_file, validate_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_suffix('.yaml'))
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    config = load_config(args.config)
    errors = validate_config(config)
    if errors or config['validation']['enabled'] or not config['performance']['enabled']:
        raise ValueError(f'Performance-only configuration required: {errors}')
    plans = []
    for prng in ('pcg32', 'xoshiro256plus'):
        variant = copy.deepcopy(config)
        variant['prng'] = {'type': prng}
        plans.extend(build_runs(variant, expand_configurations(variant), repository))
    # Alternate which PRNG runs first each repetition to reduce order bias.
    plans.sort(key=lambda r: (r['repetition'], r['algorithm'],
                             (r['prng'] == 'pcg32') == bool(r['repetition'] % 2)))
    output = Path(config['output_dir'])
    if not output.is_absolute():
        output = repository / output
    output.mkdir(parents=True, exist_ok=False)
    binary = repository / 'c/benchmark'
    digest = sha256_file(binary)
    runs = []
    for order, run in enumerate(plans, 1):
        if sha256_file(binary) != digest:
            raise ValueError('Benchmark executable changed during comparison')
        argv = run['argv'] + ['--report-json']
        assert '--output' not in argv and '--output-dir' not in argv
        result = subprocess.run(argv, text=True, capture_output=True, check=True)
        lines = [line for line in result.stdout.splitlines() if line.startswith('BENCHMARK_JSON: ')]
        if len(lines) != 1:
            raise ValueError('Missing or duplicate full precision benchmark report')
        summary = json.loads(lines[0].split(': ', 1)[1])
        if summary['compiler_optimization'] != 'O2':
            raise ValueError('Build benchmark with make -C c O2')
        if summary['prng'] != run['prng'] or summary['num_samples'] != run['samples']:
            raise ValueError('Benchmark report does not match planned run')
        runs.append(dict(run, execution_order=order, benchmark_results=summary,
                         stdout=result.stdout, stderr=result.stderr, command_argv=argv))
        print(f"{order}/{len(plans)} {run['algorithm']} {run['prng']}: "
              f"{summary['throughput_samples_per_second']/1e6:.3f} M/s", flush=True)
        (output / 'runs.json').write_text(json.dumps(runs, indent=2) + '\n')
    comparison = []
    for algorithm in sorted({r['algorithm'] for r in runs}):
        selected = [r for r in runs if r['algorithm'] == algorithm]
        grouped = {}
        for run in selected:
            key = (run['N'], run['H'], run['T'], run['samples'], run['seed'])
            grouped.setdefault(key, {}).setdefault(run['prng'], []).append(run)
        for (n, h, t, count, seed), pair in grouped.items():
            medians = {prng: statistics.median(r['benchmark_results']['throughput_samples_per_second'] / 1e6
                                               for r in repetitions)
                       for prng, repetitions in pair.items()}
            for prng, speed in medians.items():
                ratio = speed / medians['pcg32']
                comparison.append(dict(algorithm=algorithm, prng=prng, layers=n,
                    head_refinement=h, tail_refinement=t, samples=count, seed=seed,
                    repetitions=len(pair[prng]), median_Msamples_s=speed,
                    speedup_relative_to_pcg32=ratio, improvement_percent=(ratio-1)*100))
    with (output / 'comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparison[0]))
        writer.writeheader()
        writer.writerows(comparison)
    metadata = dict(benchmark_sha256=digest, machine=platform.machine(), platform=platform.platform(),
                    compiler=subprocess.check_output(['cc', '--version'], text=True),
                    compiler_flags='-std=c11 -Wall -Wextra -pedantic -O2', configuration=config,
                    timing='Existing C sampling loop; initialization and tables excluded; no warmup; volatile checksum retained')
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(comparison, indent=2))


if __name__ == '__main__':
    main()
