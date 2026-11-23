"""Run Cosima -> Revan -> Mimrec extraction, spectrum and imaging in a fresh workspace."""

import argparse
from pathlib import Path

from megalibpy import Cosima, MEGAlibRuntime, Mimrec, Revan, SimulationWorkspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, help='Fresh experiment root')
    parser.add_argument('--source', required=True, help='Native Cosima .source input')
    parser.add_argument('--revan-config', required=True)
    parser.add_argument('--mimrec-config', required=True)
    parser.add_argument('--geometry', default=None)
    parser.add_argument('--setup-script', default=None)
    parser.add_argument('--analysis-id', default='baseline', help='Workspace-local Revan analysis name')
    parser.add_argument('--mimrec-analysis-id', default=None, help='Mimrec name; defaults to the Revan analysis name')
    parser.add_argument('--archive-inputs', action='store_true', help='Retain source/cfg snapshots; default stores them in manifest')
    parser.add_argument('--cosima-log-mode', choices=['full','summary'], default='summary')
    parser.add_argument('--seed', type=int, default=12345)
    parser.add_argument('--timeout', type=float, default=None, help='Timeout per native command in seconds')
    parser.add_argument('--sim-entry', default=None, help='Exact output basename when Cosima declares multiple sim files')
    parser.add_argument('--spectrum-name', default='spectrum.root')
    parser.add_argument('--image-name', default='image.root')
    args = parser.parse_args()
    if Path(args.workspace).expanduser().exists():
        parser.error('--workspace must be a fresh path; historical results are never overwritten')
    recording = dict(archive_inputs=args.archive_inputs)
    runtime = MEGAlibRuntime.from_setup_script(args.setup_script, **recording) if args.setup_script else MEGAlibRuntime.direct(**recording)
    workspace = SimulationWorkspace(args.workspace)
    simulated = Cosima(runtime).simulate(args.source, workspace=workspace, seed=args.seed, timeout=args.timeout, log_mode=args.cosima_log_mode)
    files = simulated.outputs['sim']
    if args.sim_entry is not None:
        files = tuple(p for p in files if p.name == args.sim_entry)
    if len(files) != 1:
        parser.error('Select exactly one Cosima entry using --sim-entry; completed simulation is retained')
    reconstructed = Revan(runtime, working_space=workspace, analysis_id=args.analysis_id,
                          config_file=args.revan_config, geometry=args.geometry).reconstruct(
        simulated.as_input('sim', paths=files), task='baseline', timeout=args.timeout)
    mimrec = Mimrec(runtime, working_space=workspace, revan_analysis_id=args.analysis_id,
                    analysis_id=args.mimrec_analysis_id, input_data=reconstructed,
                    config_file=args.mimrec_config, geometry=args.geometry)
    selected = mimrec.extract_events(
        task='event-selected', timeout=args.timeout)
    spectrum = mimrec.spectrum(output_name=args.spectrum_name, timeout=args.timeout)
    image = mimrec.image(task='image-selected', output_name=args.image_name, timeout=args.timeout)
    print('Workspace:', workspace.root)
    print('Manifest:', workspace.index_path)
    for result in (simulated, reconstructed, selected, spectrum, image):
        print(result.record['operation'], result.execution_id)
        for group, paths in result.outputs.items():
            for path in paths:
                print(f'  {group}: {path}')
        print('  stdout:', result.stdout_path)
        print('  stderr:', result.stderr_path)
    print('Native commands completed; scientific interpretation remains a separate check.')


if __name__ == '__main__':
    main()
