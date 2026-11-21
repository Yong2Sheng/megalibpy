"""Reconstruct supplied MEGAlib events without importing PyROOT."""

import argparse

from megalibpy import MEGAlibRuntime, Revan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Event file or experiment/Cosima directory")
    parser.add_argument("--config", required=True, help="Native Revan configuration")
    parser.add_argument("--geometry", help="Optional -g override; otherwise use configuration geometry")
    parser.add_argument("--set", action="append", default=[], metavar="PATH=VALUE",
                        help="Native -C override; underscores in PATH become dots")
    destinations = parser.add_mutually_exclusive_group()
    destinations.add_argument("--workspace", help="Destination experiment root")
    destinations.add_argument("--output", help="Fresh standalone execution directory")
    parser.add_argument("--task", default="baseline", help="Configuration/task label")
    parser.add_argument("--setup-script", help="Trusted MEGAlib Bash initialization script")
    parser.add_argument("--timeout", type=float, help="Child wall-clock timeout in seconds")
    parser.add_argument("--isolate-settings", action="store_true",
                        help="Opt into a private native HOME after setup")
    parser.add_argument("--uncompressed", action="store_true", help="Write .tra rather than .tra.gz")
    args = parser.parse_args()
    configuration = {}
    for assignment in args.set:
        key, separator, value = assignment.partition("=")
        if not separator:
            parser.error("--set expects PATH=VALUE")
        configuration[key] = value
    runtime = (MEGAlibRuntime.from_setup_script(args.setup_script)
               if args.setup_script else MEGAlibRuntime.direct())
    result = Revan(runtime).reconstruct(
        args.input, config_file=args.config, geometry=args.geometry,
        workspace=args.workspace, output_dir=args.output, task=args.task,
        compressed=not args.uncompressed, timeout=args.timeout,
        isolate_settings=args.isolate_settings, **configuration,
    )
    print("Manifest:", result.manifest_path)
    print("Execution:", result.execution_id)
    for path in result.outputs["tra"]:
        print("Reconstructed events:", path)


if __name__ == "__main__":
    main()
