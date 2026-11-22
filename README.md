# megalibpy

Python tools for editing MEGAlib/Cosima source files, running Cosima simulations,
reconstructing events with Revan, and selecting/analyzing events with Mimrec, with configuration snapshots and execution records.
The current parser supports one run with one source per file.

[Read the documentation](https://yong2sheng.github.io/megalibpy/)

## Installation

Conda manages the dependencies and development tools. Pip installs
`megalibpy` in editable mode so source changes take effect immediately.

### 1. Install Conda

Install Miniforge, Miniconda, or Anaconda if you do not already have Conda.

### 2. Clone the repository

```bash
git clone https://github.com/Yong2Sheng/megalibpy.git
cd megalibpy
```

### 3. Create and activate the environment

```bash
conda env create -f environment.yml
conda activate megalibpy
```

If `environment.yml` changes, update the environment with:

```bash
conda env update -n megalibpy -f environment.yml --prune
```

### 4. Install megalibpy

From the repository root, run:

```bash
python -m pip install -e . --no-deps --no-build-isolation
```

To enable the pre-push hook for this checkout, run `pre-commit install`
from the activated environment.

## Quick start

```python
from megalibpy import MEGAlibSource, test_data

config = MEGAlibSource(test_data / "GRB_ml_template.source")
config.list_all_params()
config.set_flux(8.5)
config.save_source_file("modified.source")
```

See the [source file tutorial](docs/tutorials/Source_file_interpretion.ipynb)
for more examples. To run it locally, install JupyterLab with
`conda install -c conda-forge jupyterlab`, then launch `jupyter lab` from the
activated environment.

`config.run_config` exposes the parameters of the source file's `Run` block;
it does not execute a simulation. The earlier `Run` class name and `config.run`
property remain available as compatibility aliases for `RunConfig` and
`config.run_config`.

Reading and editing source files works with the Python environment alone.
Running the saved file in Cosima requires a separate MEGAlib installation
and local paths for the geometry and orientation files referenced in the template.

## Running Cosima

Run MEGAlib's external Cosima simulator from Python, either in an already
initialized environment or through a trusted Bash initialization script:

```python
from megalibpy import Cosima, MEGAlibRuntime

runtime = MEGAlibRuntime.from_setup_script("~/initialize-megalib.sh")
# Use MEGAlibRuntime.direct() when the current environment already runs Cosima.
result = Cosima(runtime).simulate(
    "small.source", output_dir="experiment/cosima-001", seed=12345, timeout=300
)
print(result.outputs["sim"])
print(result.manifest_path)
```

MEGAlib must be installed separately. Each execution uses a new output directory
and saves source snapshots, checksums, logs, and a manifest. The first version
supports ordinary single-run simulations; dependency capture is incomplete and
real integration must be checked against your MEGAlib installation.

See the [Cosima guide](docs/cosima.rst) for both runtime modes, provenance limits,
and failure handling, and the [runnable example](examples/cosima_simulation.py)
for a small end-to-end invocation using your own source and geometry files.
Keep execution directories outside the public repository.

## Reconstructing events with Revan

Continue from an existing Cosima execution directory using an explicit Revan
configuration and optional geometry override:

```python
from megalibpy import MEGAlibRuntime, Revan

runtime = MEGAlibRuntime.from_setup_script("~/initialize-megalib.sh")
reconstructed = Revan(runtime).reconstruct(
    working_space="experiments/cosima-smoke-005",
    config_file="configurations/baseline.revan.cfg",
    task="baseline",
)
print(reconstructed.outputs["tra"])
```

The original simulation remains in place. Reconstruction attempts are stored
under the same experiment, with configuration snapshots, logs and explicit
upstream references. Native Revan controls external resources and settings; optional HOME isolation
can be enabled explicitly.

For a new experiment, pass `workspace=SimulationWorkspace("experiments/grb-001")`
to `Cosima.simulate()` instead of `output_dir`; passing its result to Revan
continues in that workspace. Separate task names organize different configurations,
and repeated attempts never overwrite earlier records. External sim/evta files
use `sim_path="received/events.sim.gz", output_dir="experiments/received-grb"`;
this creates the same experiment structure and records the external input in place. See the [Revan guide](docs/revan.rst),
[workspace guide](docs/workspaces.rst), and
[command-line example](examples/revan_reconstruction.py) for input selection,
legacy directories, explicit destinations and capture limits.

## Testing

With the environment activated, run the smoke tests, the full test suite with
coverage, or the lint checks:

```bash
python -m pytest -m smoke
python -m pytest --cov=megalibpy --cov-report=term-missing --cov-report=html
ruff check .
```

To run both pre-push checks on demand:

```bash
pre-commit run --all-files --hook-stage pre-push
```

GitHub Actions runs on pushes, pull requests, and manual dispatches. It
creates the same Conda environment on Ubuntu, lints the code, runs the full
test suite, and smoke-tests the built wheel. Download the HTML and XML coverage
reports from the workflow run. Set the repository secret `CODECOV_TOKEN`
to enable Codecov uploads.

## Documentation

Read the [online documentation](https://yong2sheng.github.io/megalibpy/) for
installation instructions, the tutorial notebook, and the API reference.
GitHub Actions builds and publishes the documentation after successful checks
on `develop`; no local installation is needed to read it.

### Build documentation locally

To contribute to the [documentation source](docs/index.rst), build it from the
repository root with the Conda environment activated and `megalibpy` installed.

```bash
sphinx-build -W -b html -d docs/_build/doctrees docs docs/_build/html
```

Open `docs/_build/html/index.html` to browse the result. GitHub Actions checks
the build and publishes the HTML as a downloadable workflow artifact.
Maintainers can enable hosting under **Settings → Pages → Build and deployment
→ Source → GitHub Actions**. Pull requests build the documentation for validation
without deploying it. The [Read the Docs configuration](.readthedocs.yaml) is
also available if a separate Read the Docs project is configured.

## Mimrec event selection and analysis

Use the selected Revan result or select its task from an existing experiment:

```python
from megalibpy import Mimrec, SimulationWorkspace

experiment = SimulationWorkspace("grb-localization-001")
reconstructed = experiment.select("revan", task="baseline")
mimrec = Mimrec(runtime)
selected = mimrec.extract_events(
    working_space=reconstructed,
    config_file="configurations/analysis.mimrec.cfg",
    task="event-selection",
)
image = mimrec.image(
    working_space=selected,
    task="image-selected",
    output_name="image.png",
)
print(image.outputs["image"])
```

Independent `extract_events`, `image`, `spectrum` and `arm` methods prepare native
`-x/-i/-s/-a` commands. External data uses `tra_path` with an explicit experiment
`output_dir`. Configurations pass through unchanged; `geometry=None` uses the
configuration, and keyword overrides become native `-C` arguments. Each command
records its own execution ID and exact upstream; Mimrec operations share a
data/configuration group, its configuration snapshot, inputs and logs. ROOT outputs remain
native files. Component workflows will be added after basic native validation.
See the [Mimrec guide](docs/mimrec.rst), [API reference](docs/api/index.rst) and
[command-line example](examples/mimrec_analysis.py).

For a complete simulation → reconstruction → event selection → spectrum/image
smoke test, use [the full-chain example](examples/end_to_end_smoke.py).
A workspace has one root manifest and one Cosima simulation under `cosima/`.
Revan/Mimrec data groups use `stage/attempt-NNN`; see the
[workspace guide](docs/workspaces.rst) for configuration reuse and old-layout inputs.

For large batches, the default runtime stores source/cfg contents in the root
manifest instead of retaining separate copies. Cosima references external
orientation/geometry files without copying or hashing them by default.
Set `log_mode="summary"` directly on `Cosima.simulate()` to retain stdout from
its final `Summary for run` line through EOF. The entire summary is preserved,
without any byte cap or tail fallback; runtime setup has no logging options.
Empty logs and temporary launch/path handoff files are removed. See the
[recording guide](docs/workspaces.rst) for archival opt-in and retention details.

Analysis branches can be bound once on the tool objects:

```python
revan = Revan(runtime, analysis_id="reconstruction-a")
reconstructed = revan.reconstruct(
    working_space=simulated, config_file="baseline.revan.cfg")
mimrec = Mimrec(
    runtime, revan_analysis_id="reconstruction-a", analysis_id="selection-b")
selected = mimrec.extract_events(
    working_space=experiment, config_file="analysis.mimrec.cfg", task="event-selected")
spectrum = mimrec.spectrum(working_space=experiment, output_name="spectrum.png")
```

Omitting Mimrec's own `analysis_id` defaults it to `revan_analysis_id`. Existing
extracted events in the own analysis are reused as input; otherwise the registered
entry or explicit Revan parent is selected. `task` names an operation output
folder; `execution_id` identifies one native command. See the workspace guide.
