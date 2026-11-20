"""Run one small, user-supplied Cosima source file and inspect its records."""

import argparse

from megalibpy import Cosima, ExecutionError, MEGAlibRuntime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Single-run .source file")
    parser.add_argument("--output", required=True, help="New execution directory")
    parser.add_argument("--setup-script", help="Optional trusted MEGAlib Bash initialization script")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--timeout", type=float, default=300, help="Seconds, including initialization")
    args = parser.parse_args()
    runtime = (MEGAlibRuntime.from_setup_script(args.setup_script)
               if args.setup_script else MEGAlibRuntime.direct())
    try:
        result = Cosima(runtime).simulate(
            args.source, output_dir=args.output, seed=args.seed, timeout=args.timeout,
        )
    except ExecutionError as exc:
        print(f"Execution failed: {exc}")
        return 1
    print(f"Manifest: {result.manifest_path}")
    print(f"Stdout: {result.stdout_path}")
    print(f"Stderr: {result.stderr_path}")
    for path in result.outputs["sim"]:
        print(f"Simulation output: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
