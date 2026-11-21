API reference
=============

.. contents:: On this page
   :local:
   :depth: 2


.. currentmodule:: megalibpy

Import these classes directly from ``megalibpy``. Start with
:class:`MEGAlibSource` to load and edit a source file. Its :attr:`~MEGAlibSource.run_config`
and :attr:`~MEGAlibSource.source` properties give you access to the parsed
:class:`RunConfig` and :class:`Source` objects.

Source file
-----------

.. autoclass:: MEGAlibSource
   :members:

Global parameters
-----------------

.. autoclass:: BaseParams
   :members:

Cosima run configuration
------------------------

This object describes a ``Run`` block in a source file; it does not execute
Cosima. ``Run`` remains a compatibility alias for ``RunConfig``, and
``MEGAlibSource.run`` remains an alias for ``MEGAlibSource.run_config``.

.. autoclass:: RunConfig
   :members:

Source parameters
-----------------

.. autoclass:: Source
   :members:

Cosima simulation
-----------------

Use :meth:`Cosima.simulate` to start an external simulation. Its parameter
reference below includes defaults, units, output layout, return values, errors,
and the limits of dependency capture. See :doc:`../cosima` for complete examples
and the two runtime modes.

.. autoclass:: Cosima
   :members: simulate

Runtime selection
-----------------

Choose :meth:`MEGAlibRuntime.direct` for an already initialized environment, or
:meth:`MEGAlibRuntime.from_setup_script` to initialize MEGAlib in a Bash child.
Both modes preserve the calling Python environment.

.. autoclass:: MEGAlibRuntime
   :members: direct, from_setup_script

Revan reconstruction
--------------------

Use an explicit configuration and geometry; see :doc:`../revan` for native
settings isolation, input selection and examples.

.. autoclass:: Revan
   :members: reconstruct

Mimrec selection and analysis
-----------------------------

See :doc:`../mimrec` for event extraction, imaging, spectra and ARM.

.. autoclass:: Mimrec
   :members: extract_events, image, spectrum, arm

Experiment workspace
--------------------

See :doc:`../workspaces` for the index layout, legacy directory handling and
the distinction between task identity and execution identity.

.. autoclass:: SimulationWorkspace
   :members: select, attach_cosima, attach_sim, attach_tra, external_sim_path, external_tra_path, index_path

Results and failures
--------------------

Successful calls return ``ExecutionResult``. Failed attempts raise
``ExecutionError`` with the manifest path and the native return code when
available. A zero native return code can still produce an error if expected
output files are missing.

.. autoclass:: ExecutionResult
   :members:

.. autoexception:: ExecutionError

Executor extension interface
----------------------------

This plan model is used by tool adapters. It is not required for ordinary
Cosima calls.

.. autoclass:: megalibpy.execution.ExecutionPlan
   :members:

.. autoclass:: megalibpy.execution.ExecutionInput
   :members:
