from .base_params import BaseParams
from .run import Run
from .source import Source
from tabulate import tabulate

class MEGAlibSource():

    def __init__(self, file_path):

        """
        Initialize the instance by a MEGAlib source file."

        Parameters
        ----------
        file_path : str or pathlib.Path; the path to the source file.

        Returns
        -------
        MEGAlibSource
            The instance.
        """

        self._base = BaseParams.read_from_file(file_path)
        self._run  = Run.read_from_file(file_path)


    def list_base_params(self, return_table = False, should_print = True):
        return self._base.list_parameters(return_table = return_table, should_print = should_print)

    def list_run_params(self, source_detail = True, return_table = False, should_print = True):
        return self._run.list_parameters(source_detail = source_detail, return_table = return_table, should_print = should_print)

    def list_source_params(self, return_table = False, should_print = True):
        return self._run.source.list_parameters(return_table = return_table, should_print = should_print)

    def list_all_params(self, return_table = False, should_print = True):

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
    def run(self):
        return self._run

    @property
    def source(self):
        return self._run.source

    def set_coordinate(self, coord):

        """
        Set the coordinate for the source.

        Parameters
        ----------
        coord : astropy.coordinates. SkyCoord; the new coordinate.
        """

        self.source.set_coordinate(coord = coord)

    def save_source_file(self, file_path, should_print = False):

        """
        Save the MEGAlibSource object to a text file.

        Parameters
        ----------
        file_path : str or pathlib.Path; the file to be saved.
        """

        table_data = self.list_all_params(return_table = True, should_print = should_print)

        table = tabulate(table_data, tablefmt="plain", colalign=("left", "left"))

        with open(file_path, "w") as f:
            f.write(table)