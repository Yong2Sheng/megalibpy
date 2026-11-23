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
   │   ├── reconstruction-a/              # one input/configuration group
   │   │   ├── logs/
   │   │   └── products/events.tra.gz
   │   └── reconstruction-b/...           # alternative reconstruction
   └── mimrec/
       └── selection-a/              # shared data and default configuration
           ├── logs/                 # separate numbered logs per command
           ├── event-selected/events.tra.gz
           ├── image-selected/image.root
           ├── spectrum/spectrum.root
           └── arm/arm.root

Directories are created when needed. There are no empty stage directories or
per-command manifests. Named analysis groups identify data/configuration context,
not one invocation of a native program. Unbound adapters retain automatic
attempt-NNN grouping for compatibility. Each invocation retains its own
``execution_id``, command, status, logs, exact inputs and output paths.

Bind an experiment root to a tool object
----------------------------------------

``working_space`` means the experiment root, for example
``grb-localization-001/`` above. It never means ``mimrec/``,
``mimrec/selection-a/`` or ``mimrec/selection-a/spectrum/``.
``result.workspace_dir`` gives this root; ``result.output_dir`` is a stage or
analysis directory and is not the workspace root.

Both ``Revan`` and ``Mimrec`` accept ``working_space`` in their constructors.
Their main config_file, geometry and baseline native overrides also belong in
these named analysis constructors. Per-command native overrides affect only the
execution; they do not redefine the saved baseline. See :doc:`revan` and
:doc:`mimrec` for fixed-definition and legacy compatibility rules.
Subsequent operations can omit it. Per-call results or explicit references can
still select an exact execution within the bound workspace. A different root
or destination raises ``ValueError``; create another tool object for another
workspace. Without a constructor binding, per-call inputs work as before.
For external ``sim_path``/``tra_path`` entry, the bound root supplies the
otherwise required ``output_dir``. ``MEGAlibRuntime`` only configures native
process startup; it has no workspace or analysis binding.

One Cosima per experiment
-------------------------

.. code-block:: python

   from megalibpy import Cosima, Revan, Mimrec, SimulationWorkspace

   experiment = SimulationWorkspace("grb-localization-001")
   simulated = Cosima(runtime).simulate(
       "burst.source", workspace=experiment, seed=12345)
   revan = Revan(
       runtime, working_space=experiment, analysis_id="reconstruction-a",
       config_file="baseline.revan.cfg", geometry="detector.geo.setup")
   reconstructed = revan.reconstruct()

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

   mimrec = Mimrec(
       runtime, working_space=experiment,
       revan_analysis_id="reconstruction-a", analysis_id="selection-a",
       config_file="analysis.mimrec.cfg")
   selected = mimrec.extract_events(task="energy-cut", TotalEnergy_Min=100)
   image = mimrec.image(task="image-selected", output_name="image.root")
   spectrum = mimrec.spectrum(output_name="spectrum.root")

Construction binds the primary input and main native configuration without
creating files or executing a command. The first execution creates the group
and stores its complete definition: exact main input, prepared external
components, cfg bytes/resource cwd, geometry and baseline overrides.

Method overrides are recorded per execution and do not become group defaults.
For example, TotalEnergy_Min=100 above applies only to extraction. image and
spectrum use the baseline settings while consuming the already filtered TRA.
A different main configuration or dataset requires a new analysis_id; an
individual method override does not. Native cfg bytes remain opaque.

Opening the same analysis_id restores and validates the saved definition, even
when the original cfg was removed. Schema-2 legacy groups without a definition
retain their former variant-warning behavior until opened with constructor
configuration, which binds their existing defaults. No user files are migrated.

Reopen a named analysis without repeating identifiers:

.. code-block:: python

   mimrec = Mimrec(
       runtime, working_space=experiment,
       revan_analysis_id="reconstruction-a", analysis_id="selection-a")
   image = mimrec.image(
       task="image-selected", output_name="image.root")

Input selection first uses the own Mimrec group's unique successful extraction.
If none exists, it uses the group's unique successful component combination,
otherwise its exact registered primary input. With declared components, call
extract_events() directly to select the complete dataset in one native -x.
Repeated default component extractions start from the declaration; an explicit
previous result re-filters only that TRA and does not add components again. For a new group, the constructor resolves
the explicit upstream revan_analysis_id to an exact execution. Multiple candidates raise
ambiguity errors; directory contents and mtimes never choose an upstream.

``revan_analysis_id`` names the upstream reconstruction; ``analysis_id`` names
the Mimrec group. Omitting the latter defaults it to the former:

.. code-block:: python

   same_name = Mimrec(runtime, revan_analysis_id="reconstruction-a")
   # own directory: mimrec/reconstruction-a
   loose = Mimrec(runtime, revan_analysis_id="reconstruction-a", analysis_id="loose")
   strict = Mimrec(runtime, revan_analysis_id="reconstruction-a", analysis_id="strict")

Both differently named analyses can start from the same Revan result. A supplied
parent name must match actual provenance, including when a result is passed
explicitly or an existing extraction is reused. A named new Mimrec group entered
through a workspace requires the Revan parent name; an explicit result can serve
as the exact parent instead. External TRA input needs no invented Revan ID.

Names are local to a workspace and stage, use letters/digits/underscores/hyphens,
and start with a letter or digit. Constructors create no files and launch no
commands. A runner can be reused with the same names in independent workspaces.
Existing numbered groups can be reopened by using their basename as analysis_id;
files are not renamed or moved.

``task`` is distinct: for Mimrec it names an operation's output directory such as
``event-selected`` or ``image-selected``. It does not select the analysis group or identify extracted data. Root manifest
operation/status/execution/path records select data, even with arbitrary task
names. Multiple successful extractions require input_data=an_exact_result;
spectrum no longer accepts working_space. See :doc:`mimrec` for the full selection
order, component workflow and migration examples.
For Revan it remains a queryable operation label. An execution_id identifies one
actual native command; each rerun gets another UUID and independent log number.
Output names depend on the requested path, not operation count: spectrum.png
and spectrum.root can both keep their names. Only an existing or manifest-reserved
path receives a suffix such as spectrum-002.root, then spectrum-003.root.
The same filename in another output directory does not conflict. Recorded
reservations remain protected even when the corresponding file has been removed.
Reusing a named analysis never overwrites earlier products. Config variants
produce a warning and preserve the saved baseline.

Without bound names, Revan calls still allocate numbered groups, and Mimrec
results carry group context as before. The method-level attempt selector is a
legacy explicit selector; a value conflicting with a bound analysis_id is rejected.

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
   reconstructed = experiment.select("revan", analysis_id="reconstruction-a")
   selected = experiment.select(
       "mimrec", analysis_id="selection-a", operation="extract_events")

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
The full-chain smoke example is ``examples/end_to_end_smoke.py``. Prepared-component
composition is available through analyze_components; random-window workflows,
study scheduling and graph visualization remain separate future work.

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
