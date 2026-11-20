# megalibpy

Python tools for reading, inspecting, and editing MEGAlib/Cosima `.source` files.
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
