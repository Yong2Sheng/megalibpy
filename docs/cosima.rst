Running Cosima
==============

``Cosima`` runs the external MEGAlib simulator. ``RunConfig`` describes a
``Run`` block in a source file and does not start a process. The wrapper does
not install MEGAlib, ROOT, or Geant4.

Prepare a small, known-working source file with one inline ``Run`` declaration
and one corresponding ``FileName`` directive. Its geometry and other input
files must be available on the machine running Cosima. Choose a short
simulation for the first integration test. The bundled source-file editing
template contains installation-specific external paths and is not a portable
simulation fixture.

Looking up the API
------------------

The :doc:`API reference <api/index>` provides signatures, parameter defaults
and units, return fields, and exception behavior. In Python or a Notebook, the
same docstrings are available without building the documentation:

.. code-block:: python

   from megalibpy import Cosima, MEGAlibRuntime, ExecutionResult, ExecutionError

   help(Cosima.simulate)
   help(MEGAlibRuntime.from_setup_script)
   help(ExecutionResult)
   help(ExecutionError)

Two runtime modes
-----------------

When the current environment can already run Cosima:

.. code-block:: python

   from megalibpy import Cosima, MEGAlibRuntime

   result = Cosima(MEGAlibRuntime.direct()).simulate(
       "small.source",
       output_dir="experiment/cosima-001",
       seed=12345,
       timeout=300,
   )
   print(result.outputs["sim"])
   print(result.manifest_path)

When MEGAlib needs its own environment, initialize it inside a separate Bash
process. That script must establish the executable and library search paths.
It may activate a different Conda environment. The script must be trusted;
loading it executes its Bash commands.

.. code-block:: python

   runtime = MEGAlibRuntime.from_setup_script("~/initialize-megalib.sh")
   result = Cosima(runtime).simulate(
       "small.source",
       output_dir="experiment/cosima-002",
       seed=12345,
       timeout=300,
   )

Both modes launch external processes. In setup-script mode, initialization and
``exec cosima`` occur in the same child process. The parent Python environment
and working directory are unchanged. The bootstrap is saved as ``logs/launch.sh``
and executed as a script file, avoiding multiline ``bash -c`` arguments that can
confuse shell detection in some ROOT initialization scripts. Common inherited Python and library
search-path variables are removed before sourcing the script, but this is not
a container or a guarantee of a hermetic environment. The script must fully
initialize the intended runtime. Do not source it into the analysis shell
before starting Python just to combine two Conda environments.

Configuration and provenance
----------------------------

Each call requires a new output directory and creates:

.. code-block:: text

   cosima-001/
   ├── inputs/
   │   ├── original.source
   │   ├── executed.source
   │   ├── setup.sh              # setup-script mode only
   │   └── dependency-0000.setup # small discovered/declared dependency snapshots
   ├── logs/
   │   ├── executable.txt
   │   ├── launch.sh             # setup-script mode bootstrap
   │   ├── stdout.log
   │   └── stderr.log
   ├── products/
   │   └── events.inc*.id*.sim.gz
   └── manifest.json

The original source is copied byte for byte. In the execution copy, the single
``FileName`` is redirected to ``products/events``. Comments and other directives
are retained. Supported relative geometry, orientation-file, and spectrum/beam
file references are rebased against the original source directory. Cosima runs
with that original directory as its working directory. Output-directory and
rewritten configuration paths cannot contain whitespace or ``$`` because the
wrapper does not assume that Cosima's configuration parser supports quoting.

The actual seed is always recorded, including when one is generated
implicitly. ``compressed=False`` selects Cosima's ``-u`` option; otherwise the
wrapper passes ``-z``. Output discovery returns a tuple of files and does not
assume ``inc1.id1``. Log streams go directly to disk.

The manifest records the command, timestamps, state, return code, package and
Python versions, an available local source revision and dirty flag, tool
executable SHA-256, configuration checksums, and dependency-capture scope. An
executable checksum identifies the binary; it does not identify every dynamic
library or substitute for a complete ROOT/Geant4 build record. Native tool
version information printed by an initialization script is preserved in logs.

The setup script is archived for provenance but executed from its original
location, preserving scripts that locate resources using ``BASH_SOURCE``.
Keep it and external inputs unchanged during execution.

Additional external files can be declared explicitly:

.. code-block:: python

   result = Cosima(runtime).simulate(
       "small.source",
       output_dir="experiment/cosima-003",
       seed=12345,
       dependencies=["extra-input.dat"],
       hash_limit_bytes=64 * 1024 * 1024,
   )

Small discovered/declared files are hashed and copied; larger ones record size
and modification time without being reread in full. Set ``hash_limit_bytes=None``
to hash and archive all discovered/declared files. Manifest and snapshot files
may contain private paths and configuration: keep execution directories outside
the public repository and review them before sharing.

First-version limits
--------------------

* One inline run, ordinary event simulation. Source ``Include`` directives and
  activation/cross-section jobs are rejected. See the separate Revan and Mimrec
  guides for reconstruction and analysis.
* Dependency capture is explicitly incomplete: nested geometry include trees,
  arbitrary file-valued directives, and runtime-expanded paths are not
  automatically archived. External data is still read from its original
  location. Preserve those resources independently.
* Existing execution directories are never overwritten or automatically reused.
  There is no resume/cache implementation yet.
* Success requires exit status zero and nonempty simulation files. This does
  not establish event counts, physical correctness, or complete gzip integrity.
* Local stand-in-tool tests exercise subprocess behavior; only a real MEGAlib
  run on the target installation establishes native integration compatibility.

Failures and timeouts
---------------------

.. code-block:: python

   from megalibpy import ExecutionError

   try:
       result = Cosima(runtime).simulate(
           "small.source", output_dir="experiment/cosima-004", timeout=300
       )
   except ExecutionError as error:
       print(error.manifest_path)
       print(error.returncode)

Preparation errors, nonzero exit status, missing output, and timeouts are
recorded in the manifest. A setup script must return a nonzero status when its
initialization fails; a final successful ``echo`` can otherwise hide an earlier
failure. The wrapper does not treat every stderr message as fatal. Inspect
initialization logs as well as the manifest when validating a new runtime. On timeout or keyboard interruption the process group
is terminated, including ordinary child processes. A forcibly killed Python
process can leave ``preparing`` or ``running`` in its manifest; these states
must never be treated as completed executions.

Command-line example
--------------------

The repository includes ``examples/cosima_simulation.py``. Run it from the
repository root with a short source file and a new output path:

.. code-block:: bash

   python examples/cosima_simulation.py \
     --source small.source \
     --output experiment/cosima-001 \
     --seed 12345 \
     --timeout 300

Add ``--setup-script ~/initialize-megalib.sh`` for the separate-runtime mode.

Execution identity and upstream records
---------------------------------------

New manifests use schema version 2. Each execution, including failed attempts,
has an ``execution_id`` (UUID); successful results also expose
``result.execution_id``. This identifies an execution independently of the
output directory name. Repeating a command produces a new identity.

A Cosima simulation has an empty ``upstream`` list. Tool adapters can declare
explicit input selections using ``ExecutionPlan.upstream`` and
``result.as_input("sim")``. Before launching, the executor checks the upstream
record's successful status and selected product group, archives its exact JSON
in ``inputs/upstream-NNNN.json``, and records the manifest checksum, execution
ID, and selected file paths. It does not copy or read the product contents.
The adapter remains responsible for passing those selected files to its native
command; declaring lineage alone does not change that command.

Multiple consumers may reference the same upstream execution, and a plan can
reference multiple upstreams. The executor does not select a globally latest
result or impose a stage order. Legacy schema-1 manifests can be referenced
without modification: their identity field is null and their manifest path,
snapshot, checksum, and explicit product selection are retained.

These are execution-record interfaces, not a workspace scheduler. The current
Cosima interface still requires a new ``output_dir`` for each execution; it does
not allocate task directories, enforce one simulation per experiment, or render
workflow graphs.
