Revan event reconstruction
===========================

``Revan`` runs native event reconstruction with an explicit geometry and native
MEGAlib configuration. It accepts a Cosima result, an experiment/legacy Cosima directory,
an explicit upstream product selection, or a standalone ``sim``/``evta`` file.
The native MEGAlib installation must provide ``revan``; PyROOT is not imported.

Continue an existing simulation in a notebook
----------------------------------------------

An existing Cosima execution directory can be used directly:

.. code-block:: python

   from megalibpy import MEGAlibRuntime, Revan

   runtime = MEGAlibRuntime.from_setup_script("~/initialize-megalib.sh")
   result = Revan(runtime).reconstruct(
       "experiments/cosima-smoke-005",
       config_file="configurations/baseline.revan.cfg",
       geometry="massmodel/detector.geo.setup",
       task="baseline",
   )
   print(result.workspace_dir)
   print(result.outputs["tra"])
   print(result.manifest_path)

Both runtime modes from :doc:`cosima` are supported. Use ``Revan()`` when the
current environment is already initialized. Restart a notebook kernel after
updating an editable installation, and record the tested Git revision.

With a legacy Cosima directory, its original execution manifest and products
are retained. An additional ``workspace.json`` indexes the experiment, while
reconstruction records appear below ``revan/baseline/attempt-001/``. The native
command is equivalent to:

.. code-block:: text

   revan -g GEOMETRY -c EXECUTED_CONFIGURATION -f INPUT -o OUTPUT -n -a

The explicit output argument prevents the native default of writing a tra next
to the input event file. Revan selects compression from the output suffix;
``compressed=False`` produces ``events.tra`` instead of ``events.tra.gz``.

Configuration handling
-----------------------

``config_file`` and ``geometry`` are required. The adapter does not select the
caller's ``~/.revan.cfg`` as an implicit configuration. An unreadable file or one
without a complete outer ``RevanConfigurationFile`` root fails preparation.
Configuration syntax and settings semantics are delegated to native Revan.

MEGAlib uses its own XML-like format rather than a strict standard XML parser.
For example, its configuration writer and example files contain the legacy tag
``<SpectrumBefore)>``; native text values are also not necessarily XML-escaped.
The wrapper therefore does not parse/re-serialize the configuration with a
standard XML library or silently rename fields. The root-envelope check is not
a full native syntax or scientific validation.

The attempt saves both:

- ``inputs/original.revan.cfg``: byte-for-byte original input.
- ``inputs/executed.revan.cfg``: native bytes supplied to Revan, with checksums
  for both versions. Without HOME-prefix edits this is byte-for-byte identical
  to the original, including whitespace, line endings, comments, unknown names
  and literal entity text. HOME-based leaf paths such as ``~/response.dat`` are
  expanded against the calling Python user's home before native HOME isolation.
  Only those prefix bytes are replaced; each edit is recorded in
  ``configuration.home_path_rewrites``. Comments are masked for inspection only
  and never rewritten as path values.

Relative configuration resources resolve from the original configuration
file's directory: that directory is used as the child working directory.
Geometry and event input paths supplied to the Python API resolve from the
calling Python directory and are passed as absolute CLI arguments. These CLI
selections override saved file selections in the configuration. Runtime-expanded resource
paths such as ``$(MEGALIB)/...`` are left for the native environment.

Changing configuration
------------------------

Use separate configuration files and task labels for comparisons:

.. code-block:: python

   a = Revan(runtime).reconstruct(
       "experiments/cosima-smoke-005",
       config_file="configurations/a.revan.cfg",
       geometry="massmodel/detector.geo.setup",
       task="configuration-a",
   )
   b = Revan(runtime).reconstruct(
       "experiments/cosima-smoke-005",
       config_file="configurations/b.revan.cfg",
       geometry="massmodel/detector.geo.setup",
       task="configuration-b",
   )

Reusing a task label creates the next attempt without overwriting prior results.
Labels organize executions; the API does not check that configuration contents
are identical between attempts. Use a new task name for a different setup.
No automatic configuration optimization, queueing or branch visualization is
performed. See :doc:`workspaces` for selection and index behavior.

Native settings isolation
---------------------------

Native Revan reads and writes ``~/.revan.cfg``, even when a separate ``-c`` file
is used. Each attempt supplies its own HOME under ``logs/native-home`` so those
native settings do not overwrite or mix with the caller's defaults.

In setup-script mode, the original HOME remains in effect during environment
initialization. Only after that completes does the bootstrap apply the tool's
HOME override and execute Revan. The caller's environment is unchanged. The
private HOME and any native-saved configuration remain in the attempt directory.
This is settings isolation, not a security sandbox or hermetic environment.

Explicit inputs and multiple files
------------------------------------

A Cosima result with exactly one declared simulation file can be passed directly:

.. code-block:: python

   reconstructed = Revan(runtime).reconstruct(
       cosima_result,
       config_file="configurations/baseline.revan.cfg",
       geometry="massmodel/detector.geo.setup",
   )

If a declared upstream group has multiple files, the adapter requires an
explicit selection instead of choosing a filename or modification time:

.. code-block:: python

   selected_input = cosima_result.as_input(
       "sim", paths=[cosima_result.outputs["sim"][0]]
   )
   reconstructed = Revan(runtime).reconstruct(
       selected_input,
       config_file="configurations/baseline.revan.cfg",
       geometry="massmodel/detector.geo.setup",
   )

Select the intended native entry file deliberately. A native file may itself
reference continuation/include files; Revan handles those references. The
wrapper does not claim to merge independently generated simulation shards, and
it does not recursively archive native event-file continuations.

External files and explicit destinations
------------------------------------------

Standalone ``.sim``, ``.sim.gz``, ``.evta`` and ``.evta.gz`` files are accepted.
Without a destination, an adjacent ``<input-stem>-workspace`` experiment is
created. External data remain in place and record path/size/mtime rather than
being read or copied for provenance. A standalone file has no asserted upstream
execution ID.

Supply ``workspace=SimulationWorkspace("experiment")`` to choose the experiment,
or ``output_dir="standalone-reconstruction"`` to use only a fresh execution
directory without experiment indexing. These two destinations are mutually
exclusive. ``.tra`` inputs are rejected: those are reconstructed events for a
subsequent analysis adapter.

Records, failures and capture limits
--------------------------------------

Successful calls return ``ExecutionResult`` with ``outputs["tra"]``, logs,
execution ID, manifest path and, for managed executions, ``workspace_dir``.
The recorded upstream selection contains the exact event path passed to ``-f``;
its source manifest is snapshotted and hashed by the shared executor.

The geometry, known resource fields and explicit ``dependencies`` use the
configurable hash/copy limit, default 64 MiB. Additional relative dependencies
are resolved from the configuration directory. Discovery is best effort: an
unused native setting can contain a missing path or a resource basename rather
than a file, and unknown/runtime-expanded resources are not automatically
captured. Geometry include trees are not recursively archived. These limits are
recorded in ``dependency_capture``; external inputs must stay stable during use.

Preparation, launch, native exit, timeout and missing nonempty output failures
retain logs and manifests through ``ExecutionError``. Workspace indexes retain
failed attempts. Output checks are operational only; no image, event content or
scientific validation is performed by this adapter.

Command-line example
----------------------

.. code-block:: bash

   python examples/revan_reconstruction.py \
     --input experiments/cosima-smoke-005 \
     --config configurations/baseline.revan.cfg \
     --geometry massmodel/detector.geo.setup \
     --task baseline \
     --setup-script ~/initialize-megalib.sh

Omit ``--setup-script`` for direct execution. Use ``--workspace`` to choose an
experiment destination or ``--output`` for a standalone fresh attempt directory.
