Installation
============

Install Miniforge, Miniconda, or Anaconda to get Conda. From a terminal,
clone the repository and create the project environment.

.. code-block:: bash

   git clone https://github.com/Yong2Sheng/megalibpy.git
   cd megalibpy
   conda env create -f environment.yml
   conda activate megalibpy
   python -m pip install -e . --no-deps --no-build-isolation

Conda installs Python 3.12 and the dependencies in ``environment.yml``.
Pip installs the package in editable mode, so changes to the source code
take effect without reinstalling.

Run a smoke test to verify the installation.

.. code-block:: bash

   python -m pytest -m smoke

When the environment definition changes, update it from the repository root.

.. code-block:: bash

   conda env update -n megalibpy -f environment.yml --prune

You can read the notebook in :doc:`tutorials/index` in a browser. To run it
interactively, install JupyterLab in the activated environment.

.. code-block:: bash

   conda install -c conda-forge jupyterlab
   jupyter lab
