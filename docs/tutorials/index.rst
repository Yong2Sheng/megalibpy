Tutorials
=========

Read a Cosima source file, inspect the run and source parameters, and save
an updated copy. The example uses a GRB template included with the package.

.. code-block:: python

   from astropy.coordinates import SkyCoord
   from megalibpy import MEGAlibSource, test_data

   config = MEGAlibSource(test_data / "GRB_ml_template.source")
   print(config.run_config.run_name)
   print(config.source.coordinate)

   config.set_coordinate(SkyCoord(l=241.5, b=2.4, unit="deg", frame="galactic"))
   config.set_flux(8.5)  # photons per square centimeter per second
   config.save_source_file("modified.source")

To simulate the saved configuration, use a separate MEGAlib installation and
point the geometry and orientation entries to files on your system.

The notebook below shows how to inspect the individual parameter tables.
To run it locally, :download:`download the notebook <Source_file_interpretion.ipynb>`
and open it in JupyterLab from the ``megalibpy`` environment.

.. toctree::
   :maxdepth: 1

   Inspect and edit a source file <Source_file_interpretion>

Single-trial GRB localization
--------------------------------

The localization notebook demonstrates one simulation and reconstruction,
random one-second background extraction using a standalone runtime command,
component-aware event selection, spectrum/image generation, Galactic peak
coordinates and angular separation, and a one-row CSV summary. Update its
external paths, scientific configurations and background time bounds before
running. Each new simulation requires a fresh workspace. Native execution is
not performed during the documentation build.

:download:`Download the localization notebook <Localization_workflow.ipynb>`.

.. toctree::
   :maxdepth: 1

   Single-trial GRB localization <Localization_workflow>
