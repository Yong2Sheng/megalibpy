Revan event reconstruction
===========================

``Revan`` runs native event reconstruction with a native configuration and optional geometry override. It accepts a Cosima result, an experiment/legacy Cosima directory,
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

``config_file`` is required. Python checks that the supplied
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
resource paths retain that base. ``geometry=None`` (the default) omits ``-g``;
Revan uses the geometry selected by its configuration. A supplied geometry is
forwarded unchanged with ``-g``, allowing native override/path handling. Python
does not open, validate, hash or archive geometry or other external resources.
MEGAlib and the caller control native configuration resources; event input and
output flags remain explicit.

Changing configuration
------------------------

Pass arbitrary native setting paths as Python keyword arguments:

.. code-block:: python

   result = Revan(runtime).reconstruct(
       "experiments/cosima-smoke-005",
       config_file="configurations/baseline.revan.cfg",
       # geometry=None: no -g; use the configuration's geometry
       TotalEnergy_Min=100,
       TotalEnergy_Max=1000,
       BayesianComptonFile="$(MEGALIB)/responses/my_response.rsp",
       task="energy-selection",
   )

These produce repeated native options:

.. code-block:: text

   -C TotalEnergy.Min=100
   -C TotalEnergy.Max=1000
   -C BayesianComptonFile=$(MEGALIB)/responses/my_response.rsp

Only keyword names have underscores replaced by dots. Values are separate argv
items, preserving spaces, underscores, equals signs and native variable syntax;
booleans become ``true``/``false`` and other values use ``str``. No setting
whitelist, parameter-path discovery or value validation is performed. Native
Revan applies the overrides; the original configuration snapshot is unchanged.
Its CLI geometry/input/output precedence remains native behavior.

Use separate task names to compare settings, whether changing the base file or
passing different keyword overrides.

Reusing a task label creates the next attempt without overwriting prior results.
Labels organize executions; the API does not check that configuration contents
are identical between attempts. Use a new task name for a different setup.
No automatic configuration optimization, queueing or branch visualization is
performed. See :doc:`workspaces` for selection and index behavior.

Native settings isolation
---------------------------

Default execution retains the native HOME and normal settings behavior,
including Revan's reading/writing of ``~/.revan.cfg``. The wrapper does not
rewrite configuration paths to compensate for environment changes.

``isolate_settings=True`` is an explicit opt-in: setup still runs with the
original HOME, then only the native tool receives a private HOME under
``logs/native-home``. Configuration bytes remain unchanged, so HOME-based paths
then use that private directory. The caller's environment stays unchanged.
The CLI equivalent is ``--isolate-settings``.

Explicit inputs and multiple files
------------------------------------

A Cosima result with exactly one declared simulation file can be passed directly:

.. code-block:: python

   reconstructed = Revan(runtime).reconstruct(
       cosima_result,
       config_file="configurations/baseline.revan.cfg",
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

The manifest records the base configuration hashes, actual command flags,
geometry argument (or null when omitted), and ordered native setting overrides.
External configuration resources are not interpreted, checked or archived.
File use and diagnostics belong to native MEGAlib and the caller.

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
     --task baseline \
     --set TotalEnergy_Min=100 \
     --setup-script ~/initialize-megalib.sh

Omit ``--setup-script`` for direct execution. Use ``--workspace`` to choose an
experiment destination or ``--output`` for a standalone fresh attempt directory.
