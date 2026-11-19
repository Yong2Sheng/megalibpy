Tutorials
=========

Read a Cosima source file, inspect the run and source parameters, and save
an updated copy. The example uses a GRB template included with the package.

.. code-block:: python

   from astropy.coordinates import SkyCoord
   from megalibpy import MEGAlibSource, test_data

   config = MEGAlibSource(test_data / "GRB_ml_template.source")
   print(config.run.run_name)
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
