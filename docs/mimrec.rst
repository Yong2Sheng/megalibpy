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
   reconstructed = experiment.select("revan", task="baseline")
   mimrec = Mimrec(runtime)
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
``mimrec/attempt-NNN`` group. Later image/spectrum/ARM calls may omit config_file
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
batch operation. A shared, immutable configuration snapshot preserves the original bytes:
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

Mimrec writes ``mimrec/attempt-NNN`` data/configuration groups, with shared
``inputs/`` and ``logs/``. Operation/task labels name output directories inside
the group, e.g. ``event-selected/events.tra.gz``, ``image-selected/image.png``
and ``spectrum/spectrum.root``. See :doc:`workspaces` for the complete tree.

Only the root manifest stores command records. Use result.record to read an
individual execution by ID. Same-workspace upstreams use ID links; external
selected execution records are snapshotted. Multiple consumers preserve the
same extraction ID. Repeated operations keep old products and use numbered names.

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
