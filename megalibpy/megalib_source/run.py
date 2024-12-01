from .source import Source
from ..convenient_functions import extract_value
from tabulate import tabulate

class Run():

    def __init__(self, param_dict = None, run_name = None, file_name = None, orientation_sky = None, time = None, source = None):

        """
        Initialize the run. It only supports a single source so far.

        run_name : str
        file_name : str
        orientation_sky : str
        time : float
        source : Source object
        """

        if param_dict is None:
        
            self._run = {"Run": run_name, 
                        f"{run_name}.FileName": file_name, 
                        f"{run_name}.OrientationSky": orientation_sky, 
                        f"{run_name}.Time": time, 
                        f"{run_name}.Source": source}
        else:
            self._run = param_dict

    @classmethod
    def read_from_file(cls, file_path):
        
        """
        Read a run that contains only one source from file. Mutiple runs and sources can be supported, but it can be implemented when needed.
        
        Parameters
        ----------
        file_path : str or pathlib.Path; the source file path
        
        Returns
        -------
        Run
            An instance of Run initialized with the source file.
        """
        
        # reading the run and its source can be trickly.
        # open the file and remove comments
        with open(file_path, "r") as f:
            all_lines = f.readlines()
        lines = []
        for line in all_lines:
            if "#" not in line:
                lines += [line]

        # read run first
        run_keywords = ["Run", "FileName", "OrientationSky", "Time"] # these keywords for run can be expanded as needed
        run_dict = {}
        # The run name has to be extracted first in order to retrieve other parameters of the source
        run_dict["Run"] = extract_value(lines, identifier = "Run")
        run_name = run_dict["Run"]
        for run_keyword in run_keywords:
            if run_keyword != "Run": # exclude the run name since its already read
                run_dict[f"{run_name}.{run_keyword}"] = extract_value(lines, identifier = f"{run_name}.{run_keyword}")
            
        # read source
        source_keywords = ["Source", "ParticleType", "Beam", "Orientation", "Spectrum", "Flux"] # these keywords for run can be expanded as needed
        source_dict = {}
        # The source name has to be extracted first in order to retrieve other parameters of the source
        source_dict[f"{run_name}.Source"] = extract_value(lines, identifier = ".Source")
        source_name = source_dict[f"{run_name}.Source"]
        for source_keyword in source_keywords:
            if source_keyword != "Source": # exclude the source name since its already read
                source_dict[f"{source_name}.{source_keyword}"] = extract_value(lines, identifier = f"{source_name}.{source_keyword}")
            
        run_dict[f"{run_name}.Source"] = Source(run_name = run_name, param_dict = source_dict)
        
        return cls(param_dict = run_dict)
        
    #@property
    #def nsource(self):
        #return len(self._run["Source"])

    @property
    def run_name(self):
        return self._run["Run"]

    @property
    def file_name(self):
        return self._run[f"{self.run_name}.FileName"]

    @property
    def orientation_sky(self):
        return self._run[f"{self.run_name}.OrientationSky"]

    @property
    def time(self):
        return self._run[f"{self.run_name}.Time"]

    @property
    def source(self):
        return self._run[f"{self.run_name}.Source"]
    
    def list_parameters(self, source_detail = False, return_table = False, should_print = True):
        # Prepare data for tabulate
        #table_data = [[key, value] if not isinstance(value, Source) else [key, value.source_name] for key, value in self._run.items()]
        table_data = [[key, value] for key, value in self._run.items()]
        
        if source_detail is True:
            table_data.pop()  # remove the last one (the Source object) since we will add source details
            table_data.extend([[key, value] for key, value in self.source.source_dict.items()])
        
        # Print using tabulate
        if should_print is True:
            print(tabulate(table_data, headers=["Key", "Value"], tablefmt="grid"))

        if return_table is True:
            return table_data

        
    @property
    def run_dict(self):
        return self._run