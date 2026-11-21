Experiment workspaces
=====================

A ``SimulationWorkspace`` represents one independent simulation experiment.
Cosima, Revan and Mimrec are sibling directories. One root ``manifest.json``
contains the origin, data groups and independent command execution records.

.. code-block:: text

   grb-localization-001/
   ├── manifest.json
   ├── cosima/                       # exactly one simulation, no attempt level
   │   ├── logs/
   │   └── products/
   ├── revan/
   │   ├── attempt-001/              # one input/configuration group
   │   │   │   ├── logs/
   │   │   └── products/events.tra.gz
   │   └── attempt-002/...           # alternative reconstruction
   └── mimrec/
       └── attempt-001/              # shared data and default configuration
           ├── logs/                 # separate numbered logs per command
           ├── event-selected/events.tra.gz
           ├── image-selected/image.png
           ├── spectrum/spectrum.png
           └── arm/arm.root

Directories are created when needed. There are no empty stage directories or
per-command manifests. ``attempt-NNN`` now identifies a data/configuration group,
not one invocation of a native program. Each invocation retains its own
``execution_id``, command, status, logs, exact inputs and output paths.

One Cosima per experiment
-------------------------

.. code-block:: python

   from megalibpy import Cosima, Revan, Mimrec, SimulationWorkspace

   experiment = SimulationWorkspace("grb-localization-001")
   simulated = Cosima(runtime).simulate(
       "burst.source", workspace=experiment, seed=12345)
   reconstructed = Revan(runtime).reconstruct(
       simulated, config_file="baseline.revan.cfg", task="baseline")

``Cosima.simulate(output_dir=...)`` also treats its destination as an experiment
root. It creates ``cosima/inputs``, ``cosima/logs`` and ``cosima/products``.
A second Cosima call is rejected, including after failure. Different inputs,
settings, seeds or retries require another workspace. Several native output
shards are still products of the same unique simulation origin.

An external sim/evta file can start at Revan with ``sim_path`` and ``output_dir``.
An external TRA can start at Mimrec with ``tra_path`` and ``output_dir``. The root
records its real external origin; no synthetic earlier execution is created,
and Cosima cannot subsequently be added. Additional external TRA steps preserve
an existing primary origin.

Mimrec data groups and configuration reuse
------------------------------------------

.. code-block:: python

   mimrec = Mimrec(runtime)
   selected = mimrec.extract_events(
       reconstructed, config_file="analysis.mimrec.cfg", task="event-selected")
   image = mimrec.image(selected, task="image-selected", output_name="image.png")
   spectrum = mimrec.spectrum(selected, output_name="spectrum.png")

The first call creates ``mimrec/attempt-001`` and records its default native
configuration, explicit geometry selection, overrides and original resource cwd.
Passing the extraction result continues in that same group. Omitting
``config_file`` reuses the manifest-recorded configuration and these defaults; the original
configuration file is not required to remain available. Native relative resources
still use the original configuration directory.

Explicit settings that differ from the group's defaults produce a Python
``UserWarning`` and are recorded for that execution. Different configuration
bytes are retained in that execution's manifest entry; the default is never
replaced. Archival mode additionally retains content-addressed snapshot files. Python compares bytes/hashes, original cwd, literal
geometry and ordered overrides. It does not parse configuration fields or decide
whether a change affects projection or event selection.

With an explicit ``config_file``, ``geometry=None`` omits ``-g`` and keyword
settings are the explicitly supplied overrides. With an omitted configuration,
geometry/overrides inherit the group defaults; supplied keywords update those
default overrides for this call. None of these changes rewrites the native cfg.

Reopen a group explicitly:

.. code-block:: python

   image = mimrec.image(
       working_space=experiment, attempt="attempt-001",
       task="image-selected", output_name="image.png")

If that group has one successful extraction, it is the input. Multiple successful
extractions require an explicit result/reference. A group without extraction uses
its recorded entry input. A different unrelated TRA requires a new group.
Omitting ``attempt`` and passing a Revan result creates a new Mimrec group;
passing a selected Mimrec TRA result continues its existing group.

Repeated operations retain previous products, add numbered output filenames and
write separate numbered stdout/stderr logs in the shared ``logs/`` directory.
A requested path that belongs to another execution is rejected, never overwritten.
Task labels name operation output directories within a Mimrec group; they no
longer sit above its attempt directory. Revan creates a new data group per call;
its task label remains recorded and queryable.

Central manifest and lineage
----------------------------

Schema-2 workspace manifests contain ``origin``, ``groups`` and ``executions``.
Each execution record keeps its own schema, ID, status, runtime, configuration,
operation, group, logs, outputs and upstream references. ``result.manifest_path``
points to the root manifest; use ``result.record`` to read that particular
execution, or select it through an explicit ``ExecutionInput`` with its ID.

.. code-block:: python

   print(image.record["command"])
   print(image.record["upstream"])
   reconstructed = experiment.select("revan", task="baseline")
   selected = experiment.select(
       "mimrec", attempt="attempt-001", operation="extract_events")

Selection succeeds only for one successful candidate. It never guesses by file
mtime, directory order or the latest result. Repeated successful commands may
require retaining their returned result or constructing an explicit ID reference.

Same-workspace parents are referenced by execution ID without copying manifests.
For external parents, only the selected execution record is snapshotted; products
stay in place. A selected record's checksum is stable when unrelated executions
are added to its workspace. Configuration content is recorded in the manifest by default; optional physical
configuration snapshots are reused within a data group. Event products are not scanned or hashed by Revan/Mimrec.

Manifest allocation/status changes use short exclusive locks and atomic writes.
The lock is released during native execution. Contention raises ``FileExistsError``;
an abandoned lock after hard termination requires manual inspection. Failed and
interrupted commands remain recorded and are never treated as successful results.

Legacy data
-----------

Old standalone manifests and schema-1 workspace indexes remain readable.
Their files are not moved or rewritten automatically. New executions targeting
an old workspace raise a clear read-only-layout error: supply a fresh
``output_dir`` and an explicit old result/reference instead. The new manifest
then records the existing origin/upstream by reference without rerunning Cosima.
There is no automatic in-place migration in this release.

See :doc:`mimrec` for native operations and :doc:`api/index` for signatures.
The full-chain smoke example is ``examples/end_to_end_smoke.py``. Component
workflows, study scheduling and graph visualization remain separate future work.

Recording for large batches
---------------------------

The default runtime uses ``archive_inputs=False``. Source/configuration bytes
and their hashes are retained inside the existing root manifest, rather than
creating additional source/cfg files. Native tools still require input filenames;
those are temporary for the duration of the command and removed afterwards.
Mimrec defaults are restored from the recorded bytes, preserving native content
without parsing XML. Binary/non-UTF-8 configurations use lossless base64.

Cosima's default ``hash_limit_bytes=0`` records discovered resource paths, sizes
and modification times without reading or copying nonempty orientation, geometry
or spectrum files. Long shared orientation files stay in their original location.
Explicit ``hash_limit_bytes`` requests hashing; copying also requires an archival
runtime. External resources must be preserved by the user.

``archive_inputs=True`` explicitly retains source/configuration snapshots. Setup
scripts are always sourced from their original path; compact records keep their
path and hash, archival records also retain their text in the manifest. There is
no setup.sh backup file. The executable-path handoff and launch.sh bootstrap are
created in a temporary directory and removed; actual executable path/hash are
stored in the manifest. The bootstrap sources the supplied initialization once
per native command and execs the tool. It is not another initialization routine.

Choose log retention on the execution itself:

.. code-block:: python

   runtime = MEGAlibRuntime.from_setup_script("initialize-megalib.sh")
   simulated = Cosima(runtime).simulate(
       "burst.source", workspace=experiment, log_mode="summary")

MEGAlibRuntime has no logging parameters. Cosima supports ``full`` (default) or
``summary``. Other operations currently preserve full logs; their native summary
boundaries have not been defined. These are Python capture options, never native
MEGAlib flags or configuration overrides.

Summary mode continuously drains stdout and discards data before a line starting
``Summary for run``. Starting with that line, every byte is streamed to the log
through EOF, including shutdown text. A later summary marker replaces the earlier
block. There is no size cap on a summary and no byte-tail retention option.
Only a short marker overlap is buffered to recognize a keyword split across pipe
reads; the complete summary is never accumulated in memory. The input read block
size does not limit the amount of retained content.

If no marker appears, stdout is absent and ``logs.capture.stdout.summary_missing``
is true. No arbitrary tail is substituted for a summary. Stderr is retained in
full in either mode; use full stdout when complete diagnostic output is needed.
The wrapper does not change native exit-status/output validation.

Empty logs are removed, including stderr. Their manifest path and corresponding
result property are None. Check ``result.stderr_path is not None`` before opening
it. Nonempty error diagnostics remain available. Setup/bootstrap/path handoffs do
not leave permanent files, even in archival mode. Existing historical files are
not deleted or reorganized automatically.
