Mimrec event selection and analysis
===================================

``Mimrec`` wraps four independent native operations. It uses the same runtime,
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

Each call selects events according to its own configuration. Imaging an
extracted TRA still applies the imaging configuration's native selections;
choose those settings deliberately. ARM uses native source/test-position and
fit settings. This wrapper does not derive the source position or fit arrays.

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
batch operation. Original and executed configuration snapshots are byte-identical:
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

.. code-block:: text

   grb-localization-001/
   ├── manifest.json                    # workspace index (legacy roots: workspace.json)
   ├── cosima/...
   ├── revan/...
   └── mimrec/
       ├── event-selection/attempt-001/
       │   ├── inputs/                  # original/executed cfg, upstream record
       │   ├── logs/                    # stdout/stderr, setup bootstrap when used
       │   ├── products/events.tra.gz
       │   └── manifest.json
       └── image-selected/attempt-001/
           ├── inputs/
           ├── logs/
           ├── products/image.root
           └── manifest.json

Task names identify branches; repeated task calls allocate a new attempt.
Execution manifests identify the operation, actual input, configuration hashes,
ordered overrides, command, runtime and exact upstream execution/product subset.
An extraction can feed image, spectrum and ARM branches without overwriting it.

``output_name`` changes the filename inside ``products/``. Event extraction
accepts ``.tra`` or ``.tra.gz``; the suffix controls native compression. Plot
outputs default to ``.root`` and remain native ROOT objects/canvases. You may
request a native-supported plot suffix such as ``.png``; the wrapper does not
convert ROOT data into arrays or introduce a ROOT dependency into Python.

Failures raise ``ExecutionError`` and retain logs, manifests and indexed attempts.
Timeouts are in seconds. Success requires a zero exit code and the requested
nonempty output; some native image/ARM failures exit zero without creating a
file. This is execution validation, not scientific validation.

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
