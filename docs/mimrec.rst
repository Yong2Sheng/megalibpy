Mimrec data definitions and analysis
====================================

Define one analysis by its experiment root, exact primary input, prepared
external components, main native configuration and baseline overrides. Native
operations consume this definition and produce separately recorded results.
MEGAlibRuntime controls process startup only; it does not own data or cfg settings.

Bind data and the main configuration once
-----------------------------------------

.. code-block:: python

   from megalibpy import MEGAlibRuntime, Mimrec, SimulationWorkspace

   runtime = MEGAlibRuntime.from_setup_script("megalib-setup.sh")
   experiment = SimulationWorkspace("grb-localization-001")
   mimrec = Mimrec(
       runtime,
       working_space=experiment,
       revan_analysis_id="reconstruction-a",
       analysis_id="selection-a",
       config_file="configurations/analysis.mimrec.cfg",
       geometry="geometry/detector.geo.setup",
   )
   selected = mimrec.extract_events(
       task="energy-cut", TotalEnergy_Min=100)
   spectrum = mimrec.spectrum()
   image = mimrec.image(task="image-selected")

Construction reads metadata and main cfg bytes but creates no directories and
starts no native process. working_space is the experiment root directory
containing manifest.json and sibling cosima/revan/mimrec directories; never pass
an analysis or product subdirectory. analysis_id names this Mimrec group and
may differ from the Revan parent. If omitted, it defaults to revan_analysis_id.
External primary data requires an explicit analysis_id.

The primary input is resolved to a concrete execution and TRA product. If the
Revan group has several successful executions, construct with an exact
``input_data=reconstructed`` result/reference instead of relying on its name.
A later Revan execution does not change the primary input already bound to an
object. References preserve upstream identities; raw TRA paths use size/mtime
metadata without event scanning or copying.

.. code-block:: python

   mimrec = Mimrec(
       runtime, working_space="received-experiment", analysis_id="external-a",
       input_data="received/events.tra.gz",
       config_file="configurations/analysis.mimrec.cfg",
   )
   selected = mimrec.extract_events()

A new external-root records its real external_tra origin. Additional external
steps and components preserve any existing Cosima/SIM/TRA primary origin.

How subsequent operations find extracted data
---------------------------------------------

**task="event-selected" is not a fixed phrase or a lookup convention.** task is
only an output directory label. The preceding example deliberately uses
``task="energy-cut"``; spectrum() still finds the extracted data correctly.

For image/spectrum/arm, when input_data is omitted the bound analysis queries
the root manifest:

#. Restrict records to this Mimrec analysis group.
#. Find successful records with ``operation="extract_events"``. Use the result
   only if there is exactly one.
#. If no successful extraction exists, use the group's unique successful
   ``operation="add_external_components"`` result, if present.
#. Otherwise use the registered primary input. If external components were
   declared but no successful extraction/materialization exists, call
   ``extract_events()`` first; components are never silently ignored.

The selected execution UUID and its recorded TRA path become the next command's
upstream. The reader does not search for an event-selected folder, inspect
filenames/mtime or choose the latest result. Failed executions are excluded.

**Multiple successful extractions are ambiguous**, even when their task labels
are different. Multiple combinations are likewise ambiguous when there is no
unique extraction. Select an exact result/reference:

.. code-block:: python

   primary = experiment.select("revan", analysis_id="reconstruction-a")
   first = mimrec.extract_events(input_data=primary, task="cut-a", TotalEnergy_Min=100)
   second = mimrec.extract_events(input_data=primary, task="cut-b", TotalEnergy_Min=200)
   # mimrec.spectrum() now raises: multiple successful extract_events records.
   spectrum_a = mimrec.spectrum(input_data=first)
   image_b = mimrec.image(input_data=second)

   # Reopening the notebook: query metadata explicitly, then pass the result.
   selected_a = experiment.select(
       "mimrec", analysis_id="selection-a",
       operation="extract_events", task="cut-a")
   spectrum_a = mimrec.spectrum(input_data=selected_a)

With declared external_components, extract_events() without input_data always
starts from the primary plus all declared components, using one IN/END list and
one native -x. Repeated calls make independent selections of this same dataset;
they do not re-add components to an earlier extraction. To further filter an
existing result, pass input_data=selected explicitly; only that TRA is read.
Without external components, repeated implicit extraction retains the existing
manifest selection order and can further filter a prior extraction. For
independent cuts in that case, explicitly pass the same primary to each call.
A later looser cut cannot recover events already removed from its selected input.

If cut-a itself was executed several times, select/save the exact execution
reference rather than guessing. task and operation are distinct manifest fields:
operation comes from the Python method; task is chosen by the caller.

.. warning::

   Mimrec.spectrum no longer accepts a working_space argument or positional
   input. Bind the experiment root in Mimrec(..., working_space=...), and use
   spectrum(input_data=selected) only when selecting an exact TRA result.
   The removed keyword raises TypeError; it is never forwarded as a native -C.

A bound command's explicit input_data must be the declared primary input or a
TRA result in this analysis's own data chain; it cannot silently replace the
dataset with an unrelated result. Other operations retain their legacy
working_space entry for compatibility; new code should use the constructor
binding and input_data consistently.

Baseline configuration versus command overrides
------------------------------------------------

The constructor's config_file, geometry and ``**configuration`` establish the
baseline. Native cfg bytes remain opaque: Python does not parse XML, repair
tags, rewrite resource paths, discover geometry resources or edit settings.
The original configuration directory remains native cwd for relative resources.
The original main cfg can be removed after construction/recording; its bytes
are retained in the analysis definition and execution manifests.

Each method's keyword overrides apply **only to that execution**:

.. code-block:: python

   mimrec = Mimrec(
       runtime, working_space=experiment, analysis_id="selection-b",
       revan_analysis_id="reconstruction-a",
       config_file="analysis.mimrec.cfg", TotalEnergy_Min=50)
   selected = mimrec.extract_events(TotalEnergy_Min=100)
   spectrum = mimrec.spectrum()

The extraction receives -C TotalEnergy.Min=100. Spectrum returns to the baseline
-C TotalEnergy.Min=50 and consumes the already-filtered TRA. It inherits the
derived data, not the previous command's overrides. Later native selections
still apply to that data. Method overrides never become group defaults, even
when they appear in the first command executed in a new group.

The manifest separately records analysis baseline overrides, execution_overrides
and the effective configuration_overrides passed to native MEGAlib. Only key
underscores become dots; booleans become true/false; other values use str, with
spaces, underscores, equals signs and environment expressions left intact.
No time, flux, intensity or exposure scaling is performed.

Reopening the same analysis_id restores and checks the recorded definition.
Different primary data, external components, main cfg bytes/resource cwd,
baseline geometry or baseline overrides require a new analysis_id. Main cfg
and geometry can be omitted on method calls; explicit conflicting replacements
are rejected. No semantic configuration-equivalence parser is introduced.

Prepared external components and native combination
----------------------------------------------------

Declare external_components when defining the analysis, then call
extract_events() directly. Components can be background, another GRB or any
prepared TRA; no physical classification is inferred. One native command reads
the complete declared dataset and applies the extraction settings. There is no
required add_external_components() call or intermediate combined TRA.

.. code-block:: python

   # Prepare a background interval separately. These overrides belong only to
   # this extraction, not to the later combination or spectrum.
   background_analysis = Mimrec(
       runtime, working_space="background-window-001", analysis_id="window-a",
       input_data="background.tra.gz", config_file="background.mimrec.cfg")
   background = background_analysis.extract_events(
       EventSelections_TimeMode=1,
       EventSelections_Time_Min=100,
       EventSelections_Time_Max=101)

   mixed_analysis = Mimrec(
       runtime, working_space=experiment,
       analysis_id="with-background", input_data=reconstructed,
       config_file="analysis.mimrec.cfg",
       external_components=[background])
   selected = mixed_analysis.extract_events(task="energy-cut", TotalEnergy_Min=100)
   spectrum = mixed_analysis.spectrum(input_data=selected)

The numeric time range is illustrative; supply one valid for your data's native
time system. The wrapper does not infer valid background intervals.
extract_events writes an IN/END list with absolute primary/component paths and
runs native mimrec -x once, following the official
`MFileEvents include reader <https://github.com/zoglauer/megalib/blob/11b797167eecb88ae84b63a852edf5a466d964ae/src/global/misc/src/MFileEvents.cxx#L676>`_.
Main input and components are not copied or parsed.
Result/reference components retain every real upstream UUID, including selected
records from another workspace; raw external paths are recorded with stat-only
metadata. The primary workspace origin remains intact. The list's content is
stored in the manifest, and its native file is temporary unless archive_inputs
is explicitly enabled.

**The single extraction applies its cfg selections to all declared inputs.**
Choose main settings and extraction overrides appropriate for all components.
Background preparation overrides are not carried forward automatically. No
clock alignment, exposure normalization or event-intensity scaling is added.
Do not assume that background and source event clocks have been aligned.

Repeated default extract_events() calls start from the full declared input set,
even if earlier extractions exist. An explicit input_data=selected instead
re-filters that result alone; no component is appended a second time. The
extraction record itself contains every parent, component_inputs and include_list.
Later image/spectrum calls receive its exact result, or query the unique
successful extraction under the normal manifest selection rules.

add_external_components() remains available as an optional explicit native
materialization operation. It is not part of the recommended flow. If deliberately
using it before a second extraction, pass input_data=combined explicitly to
consume that materialized TRA. Both commands apply their own native selections.

A small ordinary-function workflow is available for already prepared components:

.. code-block:: python

   from megalibpy.mimrec.workflows import analyze_components

   results = analyze_components(
       mixed_analysis,
       extraction_overrides={"TotalEnergy_Min": 100},
   )
   selected = results["selected"]
   image_root = results["image"]
   spectrum_root = results["spectrum"]

It performs one extraction over the declared dataset, then images and calculates
a spectrum. Each analysis receives the exact extraction result, so repeated
workflow calls do not rely on implicit latest selections. Separate override
dictionaries are available for the three operations. There is no
combination_overrides argument or separate combined result. Earlier successful results remain if a later step fails.
Random background-window selection, multi-trial studies and scheduling remain
future work; each independent Cosima trial must use a separate workspace.

Outputs, failures and compatibility
-----------------------------------

Native operations are extract_events (-x), image (-i), spectrum (-s), arm (-a)
and add_external_components (-x on an include list). TRA operations return the
tra product group; plots return image/spectrum/arm. Defaults remain native
ROOT products for numerical analysis. A requested PNG does not also save ROOT.

Outputs live under mimrec/<analysis_id>/<task>, with shared inputs/logs and one
root manifest. Every command has its own UUID, upstream references and status.
Requested filenames are preserved unless occupied/reserved; conflicts gain
-002, -003, etc. without overwriting historical products. Empty logs are removed.
ExecutionError retains manifest_path and execution_id for failures. Native exit
zero plus a nonempty expected product is execution validation only.

Old schema-2 groups remain readable. Opening one with config_file in the
constructor explicitly binds its existing main data/defaults; different baseline
settings require a new ID. New bound definitions cannot be bypassed by consuming
their results through a legacy tool object. Schema-1/old directory layouts remain
read-only; no files are moved or migrated.

Unbound legacy operations still support their prior per-command configuration
and variant-warning behavior, except spectrum's removed working_space argument.
Migrate spectrum(result, ...) to spectrum(input_data=result, ...), and move root
selection into the constructor. The full-chain example uses the new bound API.
See :doc:`workspaces` and :doc:`api/index` for details.

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
       input_data=selected, output_name="spectrum.root")
   image_root = mimrec.image(
       input_data=selected, task="image-selected", output_name="image.root")

The files remain in the same Mimrec analysis group and the manifest records each
new execution. Existing PNG products remain available.

Extract numerical ROOT results
------------------------------

``extract_spectrum`` and ``extract_image`` accept either a returned
``ExecutionResult`` or a ROOT filename. They return NumPy arrays and metadata
in memory, without creating CSV, TSV, PNG or persistent cache files. They do
not modify the input file, workspace or manifest, and do not rerun Mimrec.

PyROOT is loaded **only in a separate subprocess**. Keep the analysis environment
(for example Python 3.12) separate from the MEGAlib/ROOT environment (for example
Python 3.10). The child runs a standalone bundled reader using only the standard
library and PyROOT; it does not require megalibpy or its analysis dependencies.
Do not add the other environment's PyROOT site-packages to the analysis Python.
uproot alone cannot read the Canvas contents of the verified Mimrec samples.

For a setup script that activates MEGAlib and its ROOT-compatible Python:

.. code-block:: python

   from megalibpy import (
       MEGAlibRuntime, extract_spectrum, extract_image, list_root_objects,
   )

   runtime = MEGAlibRuntime.from_setup_script("megalib-setup.sh")
   # spectrum_root/image_root are the native ExecutionResult objects above.
   spectrum = extract_spectrum(spectrum_root, runtime=runtime)
   energy_edges = spectrum.axis.edges
   spectral_values = spectrum.values
   print(spectrum.axis.unit, spectrum.value_unit, spectrum.total_counts)

   image = extract_image(image_root, runtime=runtime)
   print(image.peak_position)           # original histogram (x, y) bin center
   position = image.peak_galactic_position  # Galactic SkyCoord, or None
   if position is not None:
       print(position.l.deg, position.b.deg)
   print(image.coordinate_system, image.projection)

By default setup mode resolves ``python`` after sourcing the script. If the
script does not activate the matching Python, supply
``root_python="/path/to/root-environment/bin/python"`` as well. Direct mode
defaults to the calling Python executable, still in a child process; use
``root_python`` to select a different ROOT-compatible interpreter. The child
requires Python >=3.10. Each call has a 120-second timeout by default; pass
``timeout=None`` to disable it. Native/setup diagnostics are isolated from the
structured response. All temporary transport files are removed after the call.

Spectrum units and counts
~~~~~~~~~~~~~~~~~~~~~~~~~

``spectrum.axis.edges`` has N+1 energy edges; ``axis.widths`` and ``axis.centers``
are derived without assuming uniform or logarithmic bins. ``values`` contains
the original N regular-bin contents. ROOT titles are retained verbatim;
bracketed units are preserved, and absent units remain unknown.

For the native ``counts / keV`` spectrum with ``Energy [keV]``, total counts is:

.. math::

   N = \sum_i h_i (E_{i+1} - E_i).

``total_counts`` applies this only to recognized exact count-density labels
(``counts/keV``, ``count/keV``, ``cts/keV``, ignoring whitespace/case), with a
``keV`` X unit. Exact count labels (``counts``, ``count``, ``cts``) are summed
without multiplying by widths. Unknown labels, rates, normalized histograms,
or inconsistent energy units raise ``ValueError`` when total_counts is requested.
They remain extractable without silently assigning a count interpretation.
This relies on the histogram's labels: mislabeled data cannot be validated by
this reader. No exposure or flux scaling is performed. Underflow/overflow
contents are returned separately in ``flow_values`` and excluded from counts.

Image coordinates and peak definition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``image.values`` has shape ``(Nx, Ny)`` and uses ``values[ix, iy]``. The X/Y edges
retain native histogram coordinates. ``peak_position`` is the arithmetic center
of the unique maximum finite pixel; it is **not a centroid**, a fitted position
or a sub-pixel estimate. NaN/Inf pixels are excluded from peak selection. Tied
maxima or an image without finite pixels raise ``ValueError`` on peak access.

For plotting the unmodified native grid, the caller can explicitly use:

.. code-block:: python

   import matplotlib.pyplot as plt
   plt.pcolormesh(image.x_axis.edges, image.y_axis.edges, image.values.T)

The verified rectangular Galactic Mimrec image stores reversed pixel contents
and a separate ``TGaxis`` for longitude. The reader inspects this axis's actual
endpoints and label range to recover an affine mapping, rather than copying
the old sign-change rule. ``peak_galactic_position`` applies that mapping and
wraps longitude to [0, 360). It returns a scalar Astropy SkyCoord with the
Galactic frame, supporting nonzero longitude offsets. Use position.l.deg and
position.b.deg for numeric degrees, or position.separation(true_position) to
calculate a spherical angular error. The histogram bins remain unchanged.
This replaces the previous tuple return; migrate longitude, latitude = position
to longitude, latitude = position.l.deg, position.b.deg.

A Galactic Latitude [deg] Y axis and a unique, explicit, linear Galactic
Longitude [deg] TGaxis spanning the histogram are required for that mapping.
Unrecognized, nonlinear and Hammer projections stay ``unknown`` and return
None for ``peak_galactic_position``. A SkyCoord is constructed only after the
Galactic mapping is verified; no unknown frame, equatorial transformation or
inverse Hammer projection is inferred.
This behavior follows the official
`MImageGalactic implementation <https://github.com/zoglauer/megalib/blob/11b797167eecb88ae84b63a852edf5a466d964ae/src/mimrec/src/MImageGalactic.cxx>`_.
The native spectrum density normalization is implemented in
`MInterfaceMimrec <https://github.com/zoglauer/megalib/blob/11b797167eecb88ae84b63a852edf5a466d964ae/src/mimrec/src/MInterfaceMimrec.cxx>`_.

Selecting ROOT objects explicitly
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The reader recursively visits TDirectory keys, Canvas and nested Pad primitives,
identifies TH1/TH2 by ROOT inheritance and dimension, and excludes profiles and
TH3. It does not depend on key order or fixed primitive indices. Every stored key
cycle remains a candidate; multiple matching histograms require explicit choice:

.. code-block:: python

   objects = list_root_objects("spectrum.root", runtime=runtime)
   for obj in objects:
       print(obj.object_path, obj.class_name, obj.x_title, obj.y_title)

   spectrum = extract_spectrum(
       "spectrum.root", runtime=runtime,
       object_path="c1;1/EnergySpectrum",  # use the path actually listed above
   )

Selectors include directory key cycles and the Canvas/Pad hierarchy. Names are
URL-escaped; repeated primitive names have explicit occurrence suffixes. A
result containing multiple ROOT products also requires an explicit file path.
Neither file modification times nor a latest-cycle heuristic select data.

Verified scope
~~~~~~~~~~~~~~

The 2026-11-22 implementation was checked locally with a Python 3.12 caller and
a separate Python 3.10/ROOT reader against user-supplied native Mimrec Canvas
spectrum and rectangular Galactic image files. This validates bin extraction
for those samples; it does not establish every MEGAlib version/projection or
scientific localization accuracy. Portable tests cover numerical contracts;
real ROOT integration tests generate synthetic files when
``MEGALIBPY_ROOT_PYTHON`` identifies a ROOT-compatible executable. The normal
CI environment does not install ROOT and skips those optional integration tests.

The user subsequently verified both extraction APIs on Palmetto: spectrum
``total_counts`` agrees with the event-extraction log, and the image
``peak_galactic_position`` lies close to the injected source coordinates.
This validates the tested spectrum and rectangular Galactic image workflow;
it does not establish a localization uncertainty or coverage of other projections.


Recovery after deleting a failed analysis
-----------------------------------------

If a Mimrec group has only failed executions and its entire directory has been
removed, reconstructing it with the same analysis_id may use corrected main
settings. The constructor retains recorded primary/component references when
omitted, while an explicit main cfg establishes fresh configuration defaults.
The next execution recreates the layout and records the corrected definition;
all previous failed execution records remain intact. Existing, successful or
in-progress groups cannot use this reset. See :doc:`workspaces` for the full
recovery contract, including deleted-output limitations and Cosima's separate
single-execution rule.
