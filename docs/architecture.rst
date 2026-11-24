Architecture and data flow
==========================

``megalibpy`` connects source-file configuration, external MEGAlib commands and
numerical analysis through explicit data products. One experiment has one
primary origin; a simulated experiment contains one Cosima execution.
Reconstruction and analysis can branch without overwriting earlier results. This guide describes implemented behavior in the current
development documentation. Planned extensions are listed separately below.

These diagrams explain the implemented design. They are not execution graphs
automatically generated from a workspace manifest.

.. contents:: On this page
   :local:
   :depth: 2

Module responsibilities
-----------------------

The source-file classes describe configuration. The tool adapters translate
Python calls into native command plans. The shared executor handles processes,
logs, failures and output checks; the runtime selects how each child environment
is initialized. A workspace supplies experiment identity and records, rather
than acting as a pipeline scheduler.

.. mermaid:: diagrams/modules.mmd
   :caption: Module responsibilities and managed command execution.

.. list-table:: Public building blocks
   :header-rows: 1
   :widths: 25 45 30

   * - Module
     - Responsibility
     - Main interfaces
   * - ``megalib_source/``
     - Read and edit one run/source in a Cosima source file.
     - ``MEGAlibSource``, ``RunConfig``, ``Source``
   * - ``cosima/``, ``revan/``, ``mimrec/``
     - Prepare tool-specific flags, inputs and expected outputs.
     - ``Cosima``, ``Revan``, ``Mimrec``
   * - ``revan/analysis.py``, ``mimrec/analysis.py``
     - Bind main configuration; Mimrec also binds primary data and components.
     - Constructor-bound analysis definitions
   * - ``execution/``
     - Runtime startup, managed execution, workspace records and lineage.
     - ``MEGAlibRuntime``, ``SimulationWorkspace``, ``ExecutionResult``
   * - ``mimrec/results.py``, ``mimrec/_root_worker.py``
     - Read selected ROOT histograms in a separate compatible Python process.
     - ``extract_spectrum``, ``extract_image``
   * - ``mimrec/workflows.py``
     - Compose extraction, imaging and spectrum calls for prepared components.
     - ``analyze_components``

``RunConfig`` does not execute Cosima. Revan and Mimrec keep native cfg bytes
opaque: no XML parsing, tag repair or resource-path rewriting is performed.
Native setting names, file interpretation and scientific cuts belong to MEGAlib.
See :doc:`revan`, :doc:`mimrec` and :doc:`api/index` for the exact interfaces.

From simulation to a localization result
----------------------------------------

The ordinary localization path is simulation, reconstruction, extraction, then
image/spectrum analysis. Prepared components are declared when constructing
Mimrec; one ``extract_events()`` call combines and selects them together with
the primary TRA. No preliminary combination command or intermediate combined
TRA is required. External SIM/EVTA or TRA data can enter at the appropriate stage.

.. mermaid:: diagrams/data-flow.mmd
   :caption: Native event products and in-memory scientific results.

Every arrow between managed results identifies an exact upstream execution and
selected product. A later operation uses the selected data; it does not
inherit the previous command's temporary configuration overrides. The current
command's own baseline and overrides still apply.

For example, use ``mimrec.spectrum(input_data=selected)`` to use a particular
extraction. Without an explicit input, the bound group queries its root manifest:
unique successful extraction, otherwise unique successful optional combination,
otherwise its registered primary input. Declared components must first have a
successful extraction/materialization. Multiple candidates raise an ambiguity
error; neither a fixed task folder nor the latest file chooses the input.

The :doc:`localization notebook <tutorials/Localization_workflow>` demonstrates
one trial. Its random background window, direct TRA event count and CSV summary
are research-script steps. They do not introduce a general study scheduler.

One origin, multiple analysis branches
--------------------------------------

Each independent Cosima trial uses its own workspace. Within it, different
Revan definitions can share the simulation, and different Mimrec definitions
can share a reconstruction. Image reconstruction and spectrum extraction can reuse the same selected result.

.. mermaid:: diagrams/branches.mmd
   :caption: Independent analysis definitions sharing explicit upstream data.

.. list-table:: Three different identifiers
   :header-rows: 1
   :widths: 23 42 35

   * - Identifier
     - Meaning
     - Selection behavior
   * - ``analysis_id``
     - Workspace-local data/configuration group within a stage.
     - Reopening restores and validates its definition.
   * - ``task``
     - Caller-chosen operation label; for Mimrec, an output directory label.
     - It is not an execution ID or a fixed extraction-folder convention.
   * - ``execution_id``
     - UUID of one command invocation, including failures and reruns.
     - Results/references preserve the exact command and upstream products.

Mimrec's ``revan_analysis_id`` identifies the upstream reconstruction;
its own ``analysis_id`` can differ. An explicit ``input_data`` result can identify
the parent instead. If both are supplied, they must agree with recorded lineage.
Changed primary data, components or constructor baseline settings require a
different analysis definition, subject to the failed-group recovery rule below.

Workspace and provenance
------------------------

All stages share one root manifest. Analysis directories group data and baseline
settings, while each native invocation keeps its own status, inputs, outputs and
logs. Directories are created as needed; temporary inputs are omitted here.

.. code-block:: text

   experiment/
   ├── manifest.json
   ├── cosima/
   │   ├── logs/
   │   └── products/
   ├── revan/
   │   ├── reconstruction-a/
   │   │   ├── logs/
   │   │   └── products/
   │   └── reconstruction-b/
   └── mimrec/
       └── selection-a/
           ├── logs/
           ├── energy-cut/
           ├── image/
           └── spectrum/

``working_space`` means this experiment root. ``result.workspace_dir`` returns
the root, whereas ``result.output_dir`` identifies an analysis/stage directory.
The root manifest contains ``origin``, ``groups`` and ``executions``; use
``result.record`` to read a particular execution by ID. Same-workspace parents
use ID links; cross-workspace inputs snapshot only the selected record, leaving
event products in place. Output reservations prevent historical names from being
overwritten, even when a previously recorded product was removed.

Constructors read and validate definitions without creating files or starting
native tools. Short manifest updates are locked and written atomically; native
execution does not hold the lock. See :doc:`workspaces` for reopening, explicit
selection, legacy read-only layouts and recovery conditions.

Runtime and environment separation
----------------------------------

The analysis Python environment and MEGAlib installation can use different
Python versions. Direct mode starts a tool in the current environment.
Setup-script mode sources the supplied script and executes the tool in the
same Bash child. The caller's environment and working directory stay unchanged.

.. mermaid:: diagrams/runtime.mmd
   :caption: Runtime initialization belongs to the child process.

``MEGAlibRuntime`` owns process initialization, not data, analysis IDs,
configuration or log-capture options. Revan/Mimrec main configuration and
baseline overrides belong in their constructors; method overrides affect only
one command. Native settings retain HOME by default, with explicit isolation
available per execution.

``run_command`` reuses runtime startup for small standalone preparation tasks.
It returns ``subprocess.CompletedProcess`` and bypasses managed workspace,
manifest, output-discovery and lineage handling. See :doc:`commands`.

Execution lifecycle and failures
--------------------------------

Managed commands keep independent records through preparation, native execution
and output validation. A successful execution requires zero native exit status
and nonempty expected products; this checks operation, not scientific correctness.

.. mermaid:: diagrams/execution.mmd
   :caption: Independent command records preserve success, failure and interruption.

``ExecutionError`` exposes the manifest path and execution ID for failures after
record creation. Early argument/allocation errors can occur before such a record
exists. Keyboard interruption records ``interrupted`` and propagates the interrupt;
hard termination may leave an unfinished record, which is never a successful input.

Deleting a directory does not erase its manifest history. If a Revan/Mimrec
group contains only failed executions and its entire directory has been removed,
the same analysis ID can accept corrected constructor settings. The next execution
rechecks eligibility under the lock, records recovery history and retains old
failures. Existing, successful or in-progress groups cannot reset their definition
this way. Cosima always requires a new workspace for a rerun, including failure.

Compact inputs and log retention
--------------------------------

By default source/cfg bytes and hashes live in the root manifest. Native input
and launch files are temporary. External orientation, geometry and spectrum
resources remain shared; Cosima's default zero hash limit records stat metadata
without reading or copying nonempty resources. Explicit archival can retain
configuration files; setup scripts are always sourced from their original path.

.. mermaid:: diagrams/retention.mmd
   :caption: Compact configuration records and streaming Cosima summary logs.

Select ``log_mode`` on the execution method. Cosima supports full or summary
stdout capture; summary retains every byte from the last line starting
``Summary for run`` through EOF, with no size cap. Missing markers are recorded
explicitly, and stderr is retained in full. Empty logs are removed and their
result paths become ``None``. Other tools currently use full capture.

ROOT histograms and sky coordinates
-----------------------------------

ROOT files remain native products until explicitly read. ``extract_spectrum``
and ``extract_image`` return detached arrays and metadata in memory. PyROOT runs
only in a separate compatible interpreter, never in the analysis Python process.

.. mermaid:: diagrams/root-reading.mmd
   :caption: Isolated ROOT reading preserves numerical data and environment boundaries.

The reader recursively discovers supported histograms by ROOT type and
Directory/Canvas/Pad hierarchy. Multiple candidates require explicit object
selection. Spectrum bin edges and units are retained. ``total_counts`` integrates
only recognized counts/keV densities with keV widths, or directly sums explicit
counts; unknown conventions raise an error rather than silently assigning counts.

``peak_position`` is the maximum-intensity pixel center, not a centroid or fit.
``peak_galactic_position`` returns Galactic ``SkyCoord`` only for a verified
rectangular Galactic axis mapping. Unknown/Hammer projections remain unmapped;
longitude is determined from the actual axis mapping, not a hardcoded sign rule.
See :doc:`mimrec` for numerical contracts, supported mappings and verification scope.

Implemented behavior and future extensions
------------------------------------------

.. list-table:: Scope of the current implementation
   :header-rows: 1
   :widths: 25 75

   * - Status
     - Capability
   * - Implemented
     - Managed Cosima/Revan/Mimrec commands, named analysis definitions, exact
       result references, component-aware extraction and root-manifest lineage.
   * - Implemented
     - Standalone native commands, prepared-component function composition,
       isolated ROOT extraction and a configurable single-trial tutorial.
   * - Script responsibility
     - Research-specific background sampling, CSV study summaries and deciding
       the scientific validity of inputs, selections and results.
   * - Future extensions
     - Study scheduling, a general workflow framework, execution-graph export
       and interactive lineage browsing are not provided by the current package.
   * - Limited mapping support
     - General projection inversion, fitted localization positions and
       localization-uncertainty estimation are not supplied by the image reader.

Native availability and scientific validation depend on the user's installation
and data. Refer to the operation guides and :doc:`api/index` for complete
parameters and exceptions; the diagrams explain responsibilities and data flow,
not exhaustive validation of every native configuration or projection.
