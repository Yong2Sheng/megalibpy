from tabulate import tabulate
from ..convenient_functions import extract_value

class BaseParams():

    def __init__(self, param_dict = None, geometry = None, version = None, physics_list_em = None, store_sim_info = None, pre_trigger_mode = None):

        """
        The base parameters that controls the whole cosima simulation. I interpret them as the global variables for the entire cosima simulation.
        These base parameters are not complete, I will add more in the future when I need them.

        Parameters
        ----------
        geometry : str
        version : str
        physics_list_em : str
        store_sim_info : str
        pre_trigger_mode : str


        Notes
        -----
        This class does not return any value explicitly. Instead, it initializes the attributes of a `BaseParam` instance
        with the provided parameters
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
        
        """
        Alternative constructor to create an instance from a source file.
        
        Parameters
        ----------
        file_path : str or pathlib.Path
        
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
        return self.base_params["Geometry"]

    @property
    def version(self):
        return self.base_params["Version"]

    @property
    def physics_list_em(self):
        return self.base_params["PhysicsListEM"]

    @property
    def store_simulation_info(self):
        return self.base_params["StoreSimulationInfo"]

    @property
    def pre_trigger_mode(self):
        return self.base_params["PreTriggerMode"]

    def list_parameters(self, return_table = False, should_print = True):
        
        table_data = [[key, value] for key, value in self.base_params.items()]
        if should_print is True:
            print(tabulate(table_data, headers=["Key", "Value"], tablefmt="grid"))

        if return_table is True:
            return table_data