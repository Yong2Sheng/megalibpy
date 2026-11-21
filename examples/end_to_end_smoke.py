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
    parser.add_argument('--seed', type=int, default=12345)
    parser.add_argument('--timeout', type=float, default=None, help='Timeout per native command in seconds')
    parser.add_argument('--sim-entry', default=None, help='Exact output basename when Cosima declares multiple sim files')
    parser.add_argument('--spectrum-name', default='spectrum.png')
    parser.add_argument('--image-name', default='image.png')
    args = parser.parse_args()
    if Path(args.workspace).expanduser().exists():
        parser.error('--workspace must be a fresh path; historical results are never overwritten')
    runtime = MEGAlibRuntime.from_setup_script(args.setup_script) if args.setup_script else MEGAlibRuntime.direct()
    workspace = SimulationWorkspace(args.workspace)
    simulated = Cosima(runtime).simulate(args.source, workspace=workspace, seed=args.seed, timeout=args.timeout)
    files = simulated.outputs['sim']
    if args.sim_entry is not None:
        files = tuple(p for p in files if p.name == args.sim_entry)
    if len(files) != 1:
        parser.error('Select exactly one Cosima entry using --sim-entry; completed simulation is retained')
    reconstructed = Revan(runtime).reconstruct(
        simulated.as_input('sim', paths=files), config_file=args.revan_config,
        geometry=args.geometry, task='baseline', timeout=args.timeout)
    mimrec = Mimrec(runtime)
    selected = mimrec.extract_events(
        reconstructed, config_file=args.mimrec_config, geometry=args.geometry,
        task='event-selected', timeout=args.timeout)
    spectrum = mimrec.spectrum(selected, output_name=args.spectrum_name, timeout=args.timeout)
    image = mimrec.image(selected, task='image-selected', output_name=args.image_name, timeout=args.timeout)
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
