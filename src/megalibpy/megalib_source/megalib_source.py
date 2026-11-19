from .base_params import BaseParams
from .run_config import RunConfig
from tabulate import tabulate

class MEGAlibSource():
    """Read and edit a Cosima source file with one run and one source."""

    def __init__(self, file_path):

        """Load the global, run, and source parameters from a file.

        Parameters
        ----------
        file_path : str or pathlib.Path
            Path to the input Cosima ``.source`` file.
        """

        self._base = BaseParams.read_from_file(file_path)
        self._run  = RunConfig.read_from_file(file_path)


    def list_base_params(self, return_table = False, should_print = True):
        """Display the global simulation parameters.

        Set ``return_table=True`` to return a list of ``[key, value]`` rows
        and ``should_print=False`` to skip printing the table.
        """
        return self._base.list_parameters(return_table = return_table, should_print = should_print)

    def list_run_params(self, source_detail = True, return_table = False, should_print = True):
        """Display the run parameters and, by default, the source parameters.

        Set ``source_detail=False`` to show the source as a single
        :class:`Source` object in the run table. Set ``return_table=True``
        to return a list of ``[key, value]`` rows and ``should_print=False``
        to skip printing the table.
        """
        return self._run.list_parameters(source_detail = source_detail, return_table = return_table, should_print = should_print)

    def list_source_params(self, return_table = False, should_print = True):
        """Display the parameters for the run's source.

        Set ``return_table=True`` to return a list of ``[key, value]`` rows
        and ``should_print=False`` to skip printing the table.
        """
        return self._run.source.list_parameters(return_table = return_table, should_print = should_print)

    def list_all_params(self, return_table = False, should_print = True):
        """Display the global, run, and source parameters in one table.

        Set ``return_table=True`` to return a list of ``[key, value]`` rows
        and ``should_print=False`` to skip printing the table.
        """

        # first get the base parameter table
        table_data = self.list_base_params(return_table = True, should_print = False)
        #print(table_data)

        # second add the run parameters (including the source details)
        table_data.extend(self.list_run_params(source_detail = True, return_table = True, should_print = False))
        #print(table_data)

        if should_print is True:
            print(tabulate(table_data, headers=["Key", "Value"], tablefmt="grid"))

        if return_table is True:
            return table_data

    @property
    def run_config(self):
        """The parsed :class:`RunConfig`; accessing it does not execute Cosima."""
        return self._run

    @property
    def run(self):
        """Compatibility alias for :attr:`run_config`."""
        return self.run_config

    @property
    def source(self):
        """The parsed :class:`Source` associated with the run."""
        return self._run.source

    def set_coordinate(self, coord):

        """
        Set the Galactic coordinate of the source.

        Parameters
        ----------
        coord : astropy.coordinates.SkyCoord
            The new coordinate in the Galactic frame.
        """

        self.source.set_coordinate(coord = coord)

    def set_flux(self, flux):

        """
        Set the photon flux of the source.

        Parameters
        ----------
        flux : float
            Photon flux in photons per square centimeter per second.
        """

        self.source.set_flux(flux=flux)

    def save_source_file(self, file_path, should_print = False):

        """Write the stored parameters to a Cosima source file.

        Parameters
        ----------
        file_path : str or pathlib.Path
            Output path. An existing file at this path is overwritten.
        should_print : bool, optional
            Print the parameter table when true. Defaults to false.
        """

        table_data = self.list_all_params(return_table = True, should_print = should_print)

        table = tabulate(table_data, tablefmt="plain", colalign=("left", "left"))

        with open(file_path, "w") as f:
            f.write(table)
