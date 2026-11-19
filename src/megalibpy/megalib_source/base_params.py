from tabulate import tabulate
from ..convenient_functions import extract_value

class BaseParams():
    """Global simulation parameters shared by the entire Cosima run."""

    def __init__(self, param_dict = None, geometry = None, version = None, physics_list_em = None, store_sim_info = None, pre_trigger_mode = None):

        """Create global parameters from a mapping or individual values.

        Parameters
        ----------
        param_dict : dict, optional
            A dictionary keyed by Cosima directives. If given, it supplies
            all the parameter values.
        geometry : str
            Geometry setup path used by ``Geometry``.
        version : str
            Source file format version used by ``Version``.
        physics_list_em : str
            Electromagnetic physics list used by ``PhysicsListEM``.
        store_sim_info : str
            Simulation information storage mode used by ``StoreSimulationInfo``.
        pre_trigger_mode : str
            Event pre-trigger mode used by ``PreTriggerMode``.
        """

        if param_dict is None:

            self.base_params = {"Geometry": geometry,
                                  "Version": version,
                                  "PhysicsListEM": physics_list_em,
                                  "StoreSimulationInfo": store_sim_info,
                                  "PreTriggerMode": pre_trigger_mode}
        else:
            self.base_params = param_dict
        
    @classmethod
    def read_from_file(cls, file_path):
        
        """Read the supported global directives from a Cosima source file.
        
        Parameters
        ----------
        file_path : str or pathlib.Path
            Path to the input ``.source`` file.
        
        Returns
        -------
        BaseParams
            An instance of BaseParams initialized with the source file.
        """
        
        with open(file_path, "r") as f:
            all_lines = f.readlines()
        lines = []
        for line in all_lines:
            if "#" not in line:
                lines += [line]
        
        # the master key list to be detected, so far. More can be added as needed
        key_list = ["Geometry",
                    "Version",
                    "PhysicsListEM",
                    "StoreSimulationInfo",
                    "PreTriggerMode"]
        
        param_dict = {}
        
        for key in key_list:
            
            param_dict[key] = extract_value(lines, identifier = key)
        
        return cls(param_dict = param_dict)
    
    @property
    def geometry(self):
        """The geometry setup path as specified in the source file."""
        return self.base_params["Geometry"]

    @property
    def version(self):
        """The value of the ``Version`` directive."""
        return self.base_params["Version"]

    @property
    def physics_list_em(self):
        """The name of the electromagnetic physics list."""
        return self.base_params["PhysicsListEM"]

    @property
    def store_simulation_info(self):
        """The mode used to store simulation information."""
        return self.base_params["StoreSimulationInfo"]

    @property
    def pre_trigger_mode(self):
        """The event pre-trigger mode."""
        return self.base_params["PreTriggerMode"]

    def list_parameters(self, return_table = False, should_print = True):
        """Display the global directives and their values.

        Set ``return_table=True`` to return a list of ``[key, value]`` rows
        and ``should_print=False`` to skip printing the table.
        """

        table_data = [[key, value] for key, value in self.base_params.items()]
        if should_print is True:
            print(tabulate(table_data, headers=["Key", "Value"], tablefmt="grid"))

        if return_table is True:
            return table_data
