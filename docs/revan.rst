Revan event reconstruction
==========================

``Revan`` runs native event reconstruction with a native configuration and optional geometry override. Use ``working_space`` for an existing experiment/result, or ``sim_path`` with
``output_dir`` to start an experiment from an external event file.
The native MEGAlib installation must provide ``revan``; PyROOT is not imported.

Continue an existing simulation in a notebook
---------------------------------------------

An existing Cosima execution directory can be used directly:

.. code-block:: python

   from megalibpy import MEGAlibRuntime, Revan

   runtime = MEGAlibRuntime.from_setup_script("~/initialize-megalib.sh")
   revan = Revan(
       runtime,
       working_space="experiments/cosima-smoke-005",
       analysis_id="reconstruction-a",
       config_file="configurations/baseline.revan.cfg",
   )
   result = revan.reconstruct(task="baseline")
   print(result.workspace_dir)
   print(result.outputs["tra"])
   print(result.manifest_path)

Both runtime modes from :doc:`cosima` are supported. Use ``Revan()`` when the
current environment is already initialized. Restart a notebook kernel after
updating an editable installation, and record the tested Git revision.

Legacy Cosima directories remain readable and unchanged. To continue from one,
supply a fresh output_dir; new reconstruction records appear below ``revan/attempt-001/``. The native
command is equivalent to:

.. code-block:: text

   revan -g GEOMETRY -c EXECUTED_CONFIGURATION -f INPUT -o OUTPUT -n -a

The explicit output argument prevents the native default of writing a tra next
to the input event file. Revan selects compression from the output suffix;
``compressed=False`` produces ``events.tra`` instead of ``events.tra.gz``.

Configuration handling
----------------------

A main ``config_file`` is required when defining a new analysis, and belongs
in the Revan constructor. Python checks that the supplied
configuration is a readable, nonempty file, archives its bytes and passes an
identical copy to native Revan with ``-c``. It does not parse XML, inspect
configuration fields, rename tags, rewrite values, or normalize formatting.

MEGAlib uses its own XML-like format. Its writer and example files contain
``<SpectrumBefore)>``, which standard XML parsers reject. Interpretation belongs
to MEGAlib, including its handling of unsupported fields or invalid files.
Native software may diagnose an error or fall back to defaults; passing a file
explicitly is not a guarantee that every setting was accepted. Inspect logs.

The manifest-recorded configuration preserves
the original bytes, with identical SHA-256 checksums. Comments, whitespace,
line endings, unknown names and literal values are unchanged.

The native child runs from the original configuration directory so relative
resource paths retain that base. ``geometry=None`` in a new definition omits ``-g``;
Revan uses the geometry selected by its configuration. A supplied geometry is
forwarded unchanged with ``-g``, allowing native override/path handling. Python
does not open, validate, hash or archive geometry or other external resources.
MEGAlib and the caller control native configuration resources; event input and
output flags remain explicit.

Changing configuration
----------------------

Pass arbitrary native setting paths as Python keyword arguments:

.. code-block:: python

   revan = Revan(
       runtime, working_space="experiments/cosima-smoke-005",
       analysis_id="reconstruction-a",
       config_file="configurations/baseline.revan.cfg",
   )
   result = revan.reconstruct(
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

For a constructor-bound definition, choose a new analysis_id for a different
main file, resource cwd, geometry or baseline overrides. task only labels a
command; changing task does not redefine the analysis. Method keyword changes
are recorded per execution and leave the constructor baseline intact.

Repeated calls retain distinct execution IDs and do not overwrite products.
Calls without an analysis_id use the legacy numbered-group allocation.
No automatic configuration optimization, queueing or branch visualization is
performed. See :doc:`workspaces` for selection and index behavior.

Native settings isolation
-------------------------

Default execution retains the native HOME and normal settings behavior,
including Revan's reading/writing of ``~/.revan.cfg``. The wrapper does not
rewrite configuration paths to compensate for environment changes.

``isolate_settings=True`` is an explicit opt-in: setup still runs with the
original HOME, then only the native tool receives a private HOME under
``logs/native-home``. Configuration bytes remain unchanged, so HOME-based paths
then use that private directory. The caller's environment stays unchanged.
The CLI equivalent is ``--isolate-settings``.

Explicit inputs and multiple files
----------------------------------

A Cosima result with exactly one declared simulation file can be passed directly:

.. code-block:: python

   reconstructed = Revan(runtime).reconstruct(
       working_space=cosima_result,
       config_file="configurations/baseline.revan.cfg",
   )

If a declared upstream group has multiple files, the adapter requires an
explicit selection instead of choosing a filename or modification time:

.. code-block:: python

   selected_input = cosima_result.as_input(
       "sim", paths=[cosima_result.outputs["sim"][0]]
   )
   reconstructed = Revan(runtime).reconstruct(
       working_space=selected_input,
       config_file="configurations/baseline.revan.cfg",
   )

Select the intended native entry file deliberately. A native file may itself
reference continuation/include files; Revan handles those references. The
wrapper does not claim to merge independently generated simulation shards, and
it does not recursively archive native event-file continuations.

External files and explicit destinations
----------------------------------------

Use exactly one input entry point:

- ``working_space=...`` continues from an experiment/legacy Cosima directory,
  result object or explicit upstream reference.
- ``sim_path=...`` receives a standalone ``.sim``, ``.sim.gz``, ``.evta`` or
  ``.evta.gz`` file and requires ``output_dir=...`` for the experiment root.

For example:

.. code-block:: python

   received = Revan(runtime).reconstruct(
       sim_path="received/events.sim.gz",
       output_dir="experiments/received-grb",
       config_file="configurations/baseline.revan.cfg",
       task="baseline",
   )

This creates an experiment index at ``experiments/received-grb/manifest.json``
and an attempt below ``revan/attempt-001/``. ``output_dir`` is always
an experiment root, not a single-execution directory. The external event file
stays in place; its contents are not read, copied or hashed for provenance.
Its path is registered as ``origin`` in the root manifest, with no invented
Cosima execution or upstream UUID.

Continue or branch within the new experiment through its recorded input:

.. code-block:: python

   alternate = Revan(runtime).reconstruct(
       working_space="experiments/received-grb",
       config_file="configurations/baseline.revan.cfg",
       task="alternate",
       TotalEnergy_Min=100,
   )

Reusing the same external input and output root allocates another attempt;
a different event-file origin is rejected for an already established experiment.
Existing experiments can optionally be referenced into a new destination with
``working_space=..., output_dir=...``. There is no separate destination
``workspace`` parameter. A workspace cannot combine a registered external input
with another Cosima origin. ``.tra`` files belong to the later analysis adapter.

Records, failures and capture limits
------------------------------------

Successful calls return ``ExecutionResult`` with ``outputs["tra"]``, logs,
execution ID, manifest path and, for managed executions, ``workspace_dir``.
The recorded upstream selection contains the exact event path passed to ``-f``;
same-workspace parents use ID links; selected external records are snapshotted and hashed.

The manifest records the base configuration hashes, actual command flags,
geometry argument (or null when omitted), and ordered native setting overrides.
External configuration resources are not interpreted, checked or archived.
File use and diagnostics belong to native MEGAlib and the caller.

Preparation, launch, native exit, timeout and missing nonempty output failures
retain logs and manifests through ``ExecutionError``. Workspace indexes retain
failed attempts. Output checks are operational only; no image, event content or
scientific validation is performed by this adapter.

Command-line example
--------------------

.. code-block:: bash

   python examples/revan_reconstruction.py \
     --working-space experiments/cosima-smoke-005 \
     --config configurations/baseline.revan.cfg \
     --task baseline \
     --set TotalEnergy_Min=100 \
     --setup-script ~/initialize-megalib.sh

Omit ``--setup-script`` for direct execution. For external data use
``--sim-path received/events.sim.gz --output-dir experiments/received-grb``.
The input flags are mutually exclusive.

Current workspace layout
------------------------

See :doc:`workspaces` for the authoritative data-oriented layout. Revan calls
use ``revan/<analysis_id>`` when bound, or numbered ``revan/attempt-NNN``
groups when unbound, without a task directory level.
The task label remains queryable metadata. All executions are stored in the
root manifest; use ``result.record`` to read one command by execution ID.
Mimrec may reuse the selected reconstructed data across extraction and analysis.

Compact recording
-----------------

See :doc:`workspaces` for the default manifest-based source/config retention,
temporary native inputs and launch helpers, optional archival mode and keyword-based
summary capture. Empty logs are removed and their result paths are None. A physical
configuration snapshot is retained only when runtime.archive_inputs is true.

Named reconstruction analyses
-----------------------------

Bind the experiment root, analysis_id and main configuration when constructing
Revan. MEGAlibRuntime controls process startup; it does not own analysis settings.

.. code-block:: python

   revan = Revan(
       runtime, working_space=experiment, analysis_id="reconstruction-a",
       config_file="baseline.revan.cfg", geometry="detector.geo.setup",
   )
   reconstructed = revan.reconstruct()

The directory is revan/reconstruction-a. Construction freezes the cfg bytes,
resource cwd, literal geometry and baseline native -C text without starting a
process or creating workspace files. Configuration remains opaque. Repeated
calls retain separate execution IDs and non-overwriting products.

Individual native overrides affect one command only:

.. code-block:: python

   variant = revan.reconstruct(Some_Native_Setting=100)
   baseline = revan.reconstruct()  # uses the constructor baseline again

Use actual setting names supported by your native Revan version. Baseline and
execution overrides are separately recorded in the root manifest. The first
execution's temporary settings do not become group defaults. Different main cfg
bytes/resource cwd, geometry or constructor baseline overrides require another
analysis_id. A different sim/evta entry also requires another analysis ID.
Native fields, paths and values are never parsed or validated by Python.

.. code-block:: python

   # Reopen the recorded definition; the original cfg need not still exist.
   reopened = Revan(
       runtime, working_space=experiment, analysis_id="reconstruction-a")
   reconstructed_again = reopened.reconstruct()

The original method-level config_file/geometry entry remains available for legacy
groups without a bound definition. Those groups retain warning-and-variant
semantics. Reopening with constructor settings opts into a fixed definition;
its baseline must match the group's saved defaults. A legacy method call cannot
bypass an existing bound definition. The main example above is recommended for
new analyses.

Mimrec can select this parent through revan_analysis_id. Its own analysis_id may
be different, enabling several selection/imaging branches per reconstruction.
See :doc:`workspaces` for the distinction between analysis_id, task and execution_id.
