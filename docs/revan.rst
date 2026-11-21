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

``config_file`` and ``geometry`` are required. Python checks that the supplied
configuration is a readable, nonempty file, archives its bytes and passes an
identical copy to native Revan with ``-c``. It does not parse XML, inspect
configuration fields, rename tags, rewrite values, or normalize formatting.

MEGAlib uses its own XML-like format. Its writer and example files contain
``<SpectrumBefore)>``, which standard XML parsers reject. Interpretation belongs
to MEGAlib, including its handling of unsupported fields or invalid files.
Native software may diagnose an error or fall back to defaults; passing a file
explicitly is not a guarantee that every setting was accepted. Inspect logs.

Both ``inputs/original.revan.cfg`` and ``inputs/executed.revan.cfg`` preserve
the original bytes, with identical SHA-256 checksums. Comments, whitespace,
line endings, unknown names and literal values are unchanged.

The native child runs from the original configuration directory so relative
resource paths retain that base. Geometry and event input paths supplied to the
Python API resolve from the calling Python directory and are passed as absolute
CLI arguments, overriding saved file selections. Native environment-variable
expansion remains MEGAlib's responsibility. Additional resources can be recorded
explicitly with ``dependencies=[...]``; configuration contents are not scanned.

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
private HOME and native-saved configuration remain in the attempt directory.

Configuration text is never rewritten. When isolation is enabled, ``~`` or
``$HOME`` references inside the configuration refer to that private HOME. Use
absolute resource paths or other runtime variables, or explicitly set
``isolate_settings=False`` to preserve the original HOME. With isolation
disabled, Revan can read and overwrite the user's usual ``.revan.cfg``.
The CLI equivalent is ``--use-user-settings``. This is settings isolation,
not a security sandbox or hermetic environment.

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

The top-level geometry and explicitly declared ``dependencies`` use the
configurable hash/copy limit, default 64 MiB. Additional relative dependencies
are resolved from the configuration directory. The configuration is treated as opaque;
resources referenced inside it and geometry include trees are not automatically
inspected or recursively archived. These limits are
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
