Mimrec event selection and analysis
===================================

``Mimrec`` wraps four independent native operations in reusable data/configuration groups. It uses the same runtime,
configuration passthrough and experiment records as :doc:`revan`. A native
MEGAlib installation must provide ``mimrec``; Python does not import PyROOT.

.. list-table:: Native operations
   :header-rows: 1

   * - Python method
     - Native flag
     - Default output
     - Result group
   * - ``extract_events``
     - ``-x``
     - ``events.tra.gz``
     - ``tra``
   * - ``image``
     - ``-i``
     - ``image.root``
     - ``image``
   * - ``spectrum``
     - ``-s``
     - ``spectrum.root``
     - ``spectrum``
   * - ``arm``
     - ``-a``
     - ``arm.root``
     - ``arm``

Continue a selected reconstruction
----------------------------------

.. code-block:: python

   from megalibpy import MEGAlibRuntime, Mimrec, SimulationWorkspace

   runtime = MEGAlibRuntime.from_setup_script("megalib-setup.sh")
   experiment = SimulationWorkspace("grb-localization-001")
   reconstructed = experiment.select("revan", analysis_id="reconstruction-a")
   mimrec = Mimrec(
       runtime, revan_analysis_id="reconstruction-a", analysis_id="selection-a")
   selected = mimrec.extract_events(
       working_space=reconstructed,
       config_file="configurations/analysis.mimrec.cfg",
       geometry="geometry/detector.geo.setup",
       task="event-selection",
   )
   image = mimrec.image(
       working_space=selected,
       config_file="configurations/analysis.mimrec.cfg",
       geometry="geometry/detector.geo.setup",
       task="image-selected",
   )
   print(image.outputs["image"])
   print(image.manifest_path)

Use ``Mimrec()`` for an already initialized native environment. Setup-script
mode initializes MEGAlib in a child Bash without changing the notebook's Python
environment. Both methods above execute synchronously and work in notebooks.

A workspace directory selects its unique successful Revan attempt. If several
Revan branches or successful retries exist, use ``select("revan", task=...)``
or a specific ``ExecutionResult``/``ExecutionInput``. Multiple successes within
a task also require an explicit result/reference. No latest-file rule is used.
A Mimrec extraction must be passed explicitly as a result, or selected with
``experiment.select("mimrec", task="event-selection")``. Directory entry never
silently switches from Revan to the most recent Mimrec output.

Passing a selected Mimrec TRA result continues inside its data/configuration
``mimrec/<analysis_id>`` group. Later image/spectrum/ARM calls may omit config_file
and inherit the saved configuration, geometry override, keyword overrides and
original resource cwd. Each native call still has a distinct execution ID and logs.
Explicit settings changes emit UserWarning and retain an immutable variant,
without replacing group defaults. No configuration fields are interpreted.

Each call applies its own native selections. Imaging extracted data can apply
additional selections if its settings differ. ARM uses native source/test-position
and fit settings. Python does not derive the source position or fit arrays.

External TRA files
------------------

.. code-block:: python

   selected = mimrec.extract_events(
       tra_path="received/events.tra.gz",
       output_dir="received-experiment",
       config_file="configurations/analysis.mimrec.cfg",
       task="event-selection",
   )

Supply exactly one of ``working_space`` and ``tra_path``. External TRA requires
``output_dir``, always an experiment root, not an attempt directory. The new
root records an ``external_tra`` origin without synthetic Cosima/Revan runs.
Reopening that TRA-origin root without Revan tasks uses its original external
file. To continue from extracted events, pass the extraction result explicitly.

An external TRA may also be processed inside an existing experiment by setting
``output_dir`` to that root. Its original origin is preserved; this step records
its own input path, size and modification time. No event contents are scanned,
copied or hashed. To retain known upstream execution IDs, pass results/references
through ``working_space`` instead of reducing them to raw filenames.
Native include/continuation references remain MEGAlib's responsibility.

Configuration and flags
-----------------------

A typical command is:

.. code-block:: text

   mimrec -c EXECUTED_CONFIGURATION -f INPUT -o OUTPUT [-g GEOMETRY] [-C name=value ...] -n -x

The final operation flag is ``-x``, ``-i``, ``-s`` or ``-a``. ``-n`` selects
batch operation. The manifest records the original configuration bytes losslessly:
Python does not parse XML, rewrite paths, repair tags, discover dependencies or
inspect geometry/resources. The original configuration directory is the child
working directory. Native logs explain settings/selection errors.

``geometry=None`` omits ``-g``. Otherwise its literal value is forwarded to native
MEGAlib to override the configuration. Arbitrary configuration keywords become
separate ``-C`` arguments; only keyword underscores change into dots:

.. code-block:: python

   selected = mimrec.extract_events(
       working_space=reconstructed,
       config_file="configurations/analysis.mimrec.cfg",
       task="time-window",
       EventSelections_TimeMode=1,
       EventSelections_Time_Min=100,
       EventSelections_Time_Max=101,
   )

The time values above are illustrative, in the event file's native time system;
choose an interval that covers your actual data. Values retain underscores,
spaces, equals signs and native environment expressions. Booleans become
``true``/``false``; other values use ``str``. Native MEGAlib validates settings.
Default HOME is unchanged. ``isolate_settings=True`` explicitly gives only the
native tool a private HOME after setup; HOME-relative configuration paths then
follow that HOME, without being rewritten.

Outputs and execution records
-----------------------------

Mimrec writes ``mimrec/<analysis_id>`` data/configuration groups, with shared
``inputs/`` and ``logs/``. Operation/task labels name output directories inside
the group, e.g. ``event-selected/events.tra.gz``, ``image-selected/image.png``
and ``spectrum/spectrum.root``. See :doc:`workspaces` for the complete tree.

Only the root manifest stores command records. Use result.record to read an
individual execution by ID. Same-workspace upstreams use ID links; external
selected execution records are snapshotted. Multiple consumers preserve the
same extraction ID. Repeated operations keep old products. Requested filenames are retained unless
the exact output path exists or is reserved in the manifest; only conflicts gain
-002, -003, etc. before the extension. Log numbering counts executions separately.

Reopen a saved group with ``working_space=experiment, attempt="attempt-001"``.
A unique successful extraction is selected; multiple successes require an explicit
result/reference. No implicit latest-result rule is used. A group without
extraction uses its recorded entry input. Unrelated TRA data needs a new group.

``output_name`` chooses a filename in the operation directory. Extraction accepts
``.tra`` or ``.tra.gz``; native compression follows the suffix. Plot outputs default
to ``.root`` and remain native objects/canvases; native-supported suffixes such
as ``.png`` can be requested. No PyROOT or Python ROOT-array conversion is added.

Failures retain separate execution records and logs in the same group.
ExecutionError exposes the root manifest and failed execution_id. Zero native
exit status and a nonempty requested output establish execution success only;
native image/ARM failures may exit zero without creating a file.

Scope and next steps
--------------------

These are independent operations. Component merging, ``add_external_components``,
reusable workflows and repeated localization studies are planned separately.
No automatic background selection, time alignment or flux/exposure scaling is
performed. ROOT object discovery and scientific result extraction are also
separate future work. See :doc:`api/index` for full signatures.

A command-line example is provided in ``examples/mimrec_analysis.py``:

.. code-block:: bash

   python examples/mimrec_analysis.py extract_events \
     --working-space grb-localization-001 \
     --config configurations/analysis.mimrec.cfg \
     --task event-selection --revan-task baseline \
     --setup-script megalib-setup.sh

Compact recording
-----------------

See :doc:`workspaces` for the default manifest-based source/config retention,
temporary native inputs and launch helpers, optional archival mode and keyword-based
summary capture. Empty logs are removed and their result paths are None. A physical
configuration snapshot is retained only when runtime.archive_inputs is true.

Parent and own analysis identifiers
-----------------------------------

Mimrec(runtime, revan_analysis_id="reconstruction-a", analysis_id="selection-b")
uses the named Revan reconstruction as its parent and keeps its own data/config
group under mimrec/selection-b. When analysis_id is omitted, it defaults to the
provided Revan name. Construct once, then pass the workspace to extract_events,
image, spectrum or arm without repeating either identifier.

An existing unique successful extraction in the own group is selected first.
Otherwise its recorded entry is used; a new group selects the supplied Revan
parent. Actual execution UUIDs remain recorded in upstream, not just names.
Contradicting the saved parent produces an error; multiple successful candidates
require an explicit result/reference. The task parameter names an operation's
output folder, not the analysis. Constructors do not run MEGAlib or create files.

Use analysis_id="attempt-001" and the corresponding Revan parent name to reopen
existing numbered groups without moving their products. Unbound result-based
calls remain supported. See :doc:`workspaces` for complete rules.

ROOT data and rendered plots
----------------------------

For numerical spectrum or localization analysis, retain ``spectrum.root`` and
``image.root`` (the method defaults). The full-chain smoke example defaults to
these ROOT products. Passing ``output_name="spectrum.png"`` or
``output_name="image.png"`` asks native Mimrec to save a rendered image instead;
it does not also save a ROOT file. PNG pixels do not preserve the histogram bins
and metadata required for numerical analysis.

To recover ROOT products after a PNG-only run, reuse the exact successful
extraction result and the saved configuration; Cosima and Revan need not run
again. These are new Mimrec executions, not a conversion of the PNG:

.. code-block:: python

   spectrum_root = mimrec.spectrum(
       working_space=selected, output_name="spectrum.root")
   image_root = mimrec.image(
       working_space=selected, task="image-selected", output_name="image.root")

The files remain in the same Mimrec analysis group and the manifest records each
new execution. Existing PNG products remain available.
