API reference
=============

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

Cosima execution
----------------

.. autoclass:: Cosima
   :members:

.. autoclass:: MEGAlibRuntime
   :members:

.. autoclass:: ExecutionResult
   :members:

.. autoexception:: ExecutionError
