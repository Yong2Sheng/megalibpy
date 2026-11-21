Experiment workspaces
=====================

``SimulationWorkspace`` groups execution records for one experiment. It is
separate from the executor's single-attempt directory: a successful or failed
attempt still has its own inputs, logs, products and manifest.

A new Cosima experiment and its reconstruction share one root:

.. code-block:: python

   from megalibpy import Cosima, MEGAlibRuntime, Revan, SimulationWorkspace

   runtime = MEGAlibRuntime.direct()  # already initialized MEGAlib environment
   experiment = SimulationWorkspace("experiments/grb-001")
   simulation = Cosima(runtime).simulate(
       "burst.source", workspace=experiment, seed=12345,
   )
   reconstruction = Revan(runtime).reconstruct(
       working_space=simulation,
       config_file="baseline.revan.cfg",
       geometry="detector.geo.setup",
       task="baseline",
   )

Directory layout
----------------

.. code-block:: text

   grb-001/
   ├── manifest.json                   # experiment index
   ├── cosima/
   │   └── simulation/
   │       └── attempt-001/
   │           ├── inputs/
   │           ├── logs/
   │           ├── products/
   │           └── manifest.json       # authoritative execution record
   └── revan/
       ├── baseline/
       │   └── attempt-001/
       │       ├── inputs/
       │       ├── logs/
       │       ├── products/
       │       └── manifest.json
       └── alternate/
           └── attempt-001/...

An existing Cosima execution directory is also an experiment root: its original
``manifest.json`` remains unchanged, and ``workspace.json`` serves as the
experiment index. New stage/task/attempt folders are added below that same root.
No migration or repeat simulation is required.

The index has its own ``kind="simulation_workspace"`` and schema version 1;
this is distinct from execution-manifest schema 1/2. It stores a workspace UUID,
stable task IDs, attempt numbers, manifest locations, execution IDs and status.
The execution manifests remain the source of detailed configuration and lineage.
An existing external Cosima origin can be registered by reference without
copying it; its location may be relative to the experiment root, including
``..`` when outside it. Moving an experiment does not package external data.

External simulation entry point
-------------------------------

``Revan.reconstruct(sim_path=..., output_dir=..., config_file=...)`` creates or
continues an experiment whose origin is an external event file. ``output_dir``
is the experiment root; attempt records use the same ``revan/task/attempt-NNN``
layout as experiments begun with Cosima. The index stores
``external_input={"kind": "external_sim", "path": ...}``; no Cosima record is
invented. The file is referenced in place, not copied or read for content checks.

The experiment can subsequently be reopened with ``working_space=root`` to
reuse that external input for another reconstruction task. All returned results
carry this root as ``workspace_dir``. Different origins cannot be silently mixed
in one workspace. Passing an event file through ``working_space`` is rejected;
use the explicit ``sim_path`` entry point with ``output_dir``.

Selection and identity
----------------------

A workspace allows one Cosima origin. Another successful or pending Cosima
execution is rejected; failed/interrupted attempts can be retried. The default
low-level ``Cosima.simulate(output_dir=...)`` API remains available for
independent executions outside this experiment rule.

Stage/task labels use letters, digits, underscores and hyphens. Repeated Revan
calls under the same task label allocate a new attempt, preserving all older
records; separate labels organize configuration comparisons. A task ID differs
from the execution UUID for an individual attempt. Configuration equality is
not enforced: give different scientific setups different labels.

``experiment.select("cosima")`` or ``experiment.select("revan", task="baseline")``
returns a persisted successful result only when the selection is unambiguous.
Two successful attempts within a task also require an explicit result/manifest
reference. No global latest-result selection or modification-time heuristic is
used. Pass the returned ``ExecutionResult`` or an explicit ``ExecutionInput``
when choosing a particular execution.

Managed results carry ``workspace_dir``; ``as_input(group, paths=[...])`` retains
that experiment hint while pinning an explicit upstream product selection.
References to legacy executions without UUIDs remain supported.

Failure and concurrency behavior
--------------------------------

Allocation is indexed before the native process starts; completion updates the
index without discarding failed attempts. Explicit output directories are never
reused. Short index mutations use an exclusive ``.workspace.lock``; contention
raises ``FileExistsError`` and can be retried by the caller. Executions do not
hold that lock for their entire duration.

A forcibly terminated Python process can leave an allocated attempt or stale
lock. Inspect the execution manifest and confirm that no writer is active before
manual recovery. Automatic stale-lock recovery, job scheduling, index repair and
graphical workflow browsing are not provided. The index does not replace
execution manifests or claim that scientific results have been validated.

Mimrec branches and external TRA
--------------------------------

Mimrec uses the same ``mimrec/<task>/attempt-NNN`` layout. Pass a selected
Revan result into ``Mimrec.extract_events``; pass its selected TRA result into
``image``, ``spectrum`` or ``arm`` to preserve exact upstream IDs. Each operation
has its own default task label. A workspace directory selects Revan, never an
implicit latest Mimrec result.

``tra_path`` plus ``output_dir`` can start an experiment at Mimrec. An empty
root registers ``external_input={kind: external_tra, path: ...}``. Existing
origins are preserved when processing additional external TRA inputs; those
inputs are recorded in their individual execution manifests.
``external_sim_path`` and ``external_tra_path`` expose only their matching
origin kind. No synthetic upstream execution is introduced.

See :doc:`mimrec` for selection, output formats and complete examples. Workflow
composition and graph visualization remain future work.
