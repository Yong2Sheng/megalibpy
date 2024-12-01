from tabulate import tabulate
from astropy.coordinates import SkyCoord

class Source():

    def __init__(self, run_name, param_dict = None, source_name = None, particle_type = None, beam = None, orientation = None, spectrum = None, flux = None):

        """
        Initialize a source. 
        Note that many parameters are only input as a string like `orientation = "Galactic Fixed -21.6 44.6"`. The current code doesn't further interpret it.

        Parameters
        ----------
        run_name : str; the name of the run of the source
        source_name : str; the source name
        particle_type : int
        beam : str
        orientation : str
        spectrum : str
        flux : float
        """
        
        self._run_name = run_name
        
        if param_dict is None:

            self._source = {f"{self._run_name}.Source" : source_name, 
                           f"{source_name}.ParticleType" : particle_type,
                           f"{source_name}.Beam" : beam, 
                           f"{source_name}.orientation" : orientation, 
                           f"{source_name}.Flux" : flux}
        else:
            self._source = param_dict
            
        self._source_name = self._source[f"{self._run_name}.Source"]

    @property
    def source_name(self):
        return self._source[f"{self._run_name}.Source"]

    @property
    def particle_type(self):
        return self._source[f"{self._source_name}.ParticleType"]

    @property
    def beam(self):
        return self._source[f"{self._source_name}.Beam"]

    @property
    def orientation(self):
        return self._source[f"{self._source_name}.Orientation"]

    @property
    def spectrum(self):
        return self._source[f"{self._source_name}.Spectrum"]

    @property
    def flux(self):
        return self._source[f"{self._source_name}.Flux"]
    
    @property
    def coordinate(self):
        
        lon = float(self.orientation.split()[-1])
        lat = float(self.orientation.split()[-2])
        
        return SkyCoord(l = lon, b = lat, unit = "deg", frame = "galactic")

    def list_parameters(self, return_table = False, should_print = True):
        # Prepare data for tabulate
        table_data = [[key, value] for key, value in self._source.items()]
        #table_data = [[key, value] for key, value in self._run.items()]
        
        # Print using tabulate
        if should_print is True:
            print(tabulate(table_data, headers=["Key", "Value"], tablefmt="grid"))

        if return_table is True:
            return table_data
        
    @property
    def source_dict(self):
        return self._source
    
    def set_coordinate(self, coord):
        
        """
        Set the galactic coordinate of the source.
        
        Parameters
        ----------
        coord : astropy.coordinates.SkyCoord
        
        Returns
        -------
        None
        """
        
        if not isinstance(self.orientation, str):
            raise ValueError("The orientation of the source is not set")
            
        else:
            if not isinstance(coord, SkyCoord):
                raise TypeError(f"{coord} must be an astropy.coordinates.SkyCoord object")
            else:
                values = self.orientation.split()
                values[-1] = coord.l.deg.astype(str)
                values[-2] = coord.b.deg.astype(str)
                self._source[f"{self._source_name}.Orientation"] = " ".join(values)
            
        