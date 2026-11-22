"""Run one recorded native Mimrec operation; see the Mimrec documentation."""

import argparse

from megalibpy import MEGAlibRuntime, Mimrec, SimulationWorkspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revan-analysis-id', default=None, help='Explicit upstream Revan analysis name')
    parser.add_argument('--analysis-id', default=None, help='Bind a workspace-local analysis group')
    parser.add_argument('operation', choices=['extract_events', 'image', 'spectrum', 'arm'])
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--working-space')
    inputs.add_argument('--tra-path')
    parser.add_argument('--output-dir', help='Destination experiment root; required with --tra-path')
    parser.add_argument('--config', help='Required for new groups; omitted to reuse a saved group')
    parser.add_argument('--attempt', help='Existing Mimrec group, e.g. attempt-001')
    parser.add_argument('--geometry', default=None)
    parser.add_argument('--task')
    parser.add_argument('--revan-task', help='Select a named Revan task in the input workspace')
    parser.add_argument('--output-name')
    parser.add_argument('--setup-script')
    parser.add_argument('--timeout', type=float)
    args = parser.parse_args()
    if args.tra_path and not args.output_dir:
        parser.error('--tra-path requires --output-dir')
    if args.revan_task and not args.working_space:
        parser.error('--revan-task requires --working-space')
    runtime = MEGAlibRuntime.from_setup_script(args.setup_script) if args.setup_script else MEGAlibRuntime.direct()
    selected = args.working_space
    if args.revan_task:
        selected = SimulationWorkspace(selected).select('revan', task=args.revan_task)
    options = dict(working_space=selected, tra_path=args.tra_path, output_dir=args.output_dir,
                   config_file=args.config, geometry=args.geometry, timeout=args.timeout, attempt=args.attempt)
    if args.task is not None:
        options['task'] = args.task
    if args.output_name is not None:
        options['output_name'] = args.output_name
    result = getattr(Mimrec(runtime, revan_analysis_id=args.revan_analysis_id, analysis_id=args.analysis_id), args.operation)(**options)
    print('Workspace:', result.workspace_dir)
    print('Manifest:', result.manifest_path)
    print('Stdout log:', result.stdout_path)
    print('Stderr log:', result.stderr_path)
    for group, paths in result.outputs.items():
        for path in paths:
            print(f'{group}: {path}')


if __name__ == '__main__':
    main()
