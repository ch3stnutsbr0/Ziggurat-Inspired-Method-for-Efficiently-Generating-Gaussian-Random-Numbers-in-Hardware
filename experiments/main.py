"""Plan, execute or statistically validate Gaussian RNG experiments."""

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required but unavailable in this Python environment; no packages were installed.")

from runner import dry_run, execute_plan
from utils import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate and print the schedule (default)")
    mode.add_argument("--run", action="store_true", help="Execute the validated schedule sequentially using YAML prng.type (default pcg32)")
    mode.add_argument("--validate", action="store_true", help="Test existing validation samples against fixed N(0,1); never execute benchmarks")
    parser.add_argument("--resume", action="store_true", help="Verify and skip completed runs; archive and retry incomplete attempts")
    parser.add_argument("--refresh-performance", action="store_true", help="With --resume, explicitly archive and regenerate all performance results")
    args = parser.parse_args()
    if args.validate and (args.resume or args.refresh_performance):
        parser.error("--validate cannot be combined with benchmark resume/refresh options")
    if args.refresh_performance and not args.resume:
        parser.error("--refresh-performance requires --resume")
    try:
        config = load_config(args.config)
        repository = Path(__file__).resolve().parents[1]
        if isinstance(config, dict) and config.get("experiment_id") == "experiment_01":
            if args.validate:
                raise ValueError("Experiment 01 validates each dataset during --run; use --resume to continue")
            from experiment01 import preflight, execute
            report = execute(config, repository, resume=args.resume) if args.run else preflight(config, repository, resume=args.resume)
            report["yaml_syntax"] = "valid"
        elif args.validate:
            from validation import validate_existing
            report = validate_existing(config, repository)
        else:
            report = dry_run(config, repository, resume=args.resume, refresh_performance=args.refresh_performance)
            report["yaml_syntax"] = "valid"
            if args.run and report["status"] == "valid":
                report = execute_plan(report, repository, config, resume=args.resume, refresh_performance=args.refresh_performance)
    except (OSError, ValueError, yaml.YAMLError, ImportError) as exc:
        report = {"status": "invalid", "errors": [str(exc)]}
    report["config_file"] = str(args.config.resolve())
    print(json.dumps(report, indent=2, allow_nan=False))
    if report["status"] == "failed":
        return 1
    return 0 if report["status"] in ("valid", "successful") else 2


if __name__ == "__main__":
    raise SystemExit(main())
