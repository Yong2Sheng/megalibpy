from tabulate import tabulate
from astropy.coordinates import SkyCoord

class Source():
    """Particle, beam, orientation, spectrum, and flux for one Cosima source."""

    def __init__(self, run_name, param_dict = None, source_name = None, particle_type = None, beam = None, orientation = None, spectrum = None, flux = None):

        """Create a source from a mapping or individual values.

        Parameters
        ----------
        run_name : str
            Name of the run that references this source.
        param_dict : dict, optional
            A dictionary keyed by Cosima directives. If given, it supplies
            all the parameter values.
        source_name : str
            Name assigned to the source in the run's ``Source`` directive.
        particle_type : int or str
            Cosima particle type code.
        beam : str
            Beam model and its arguments, as used in the ``Beam`` directive.
        orientation : str
            Orientation specification, such as ``Galactic Fixed -21.6 44.6``.
        spectrum : str
            For direct construction, supply the ``<source>.Spectrum``
            entry in ``param_dict`` to store the spectral specification.
        flux : float or str
            Photon flux in photons per square centimeter per second.
        """
        
        self._run_name = run_name
        
        if param_dict is None:

            self._source = {f"{self._run_name}.Source" : source_name, 
                           f"{source_name}.ParticleType" : particle_type,
                           f"{source_name}.Beam" : beam, 
                           f"{source_name}.Orientation" : orientation, 
                           f"{source_name}.Flux" : flux}
        else:
            self._source = param_dict
            
        self._source_name = self._source[f"{self._run_name}.Source"]

    @property
    def source_name(self):
        """The name assigned to the source in the run's ``Source`` directive."""
        return self._source[f"{self._run_name}.Source"]

    @property
    def particle_type(self):
        """The Cosima particle type code, read from file as text."""
        return self._source[f"{self._source_name}.ParticleType"]

    @property
    def beam(self):
        """The beam model and parameters as specified in the source file."""
        return self._source[f"{self._source_name}.Beam"]

    @property
    def orientation(self):
        """The raw orientation specification for this source."""
        return self._source[f"{self._source_name}.Orientation"]

    @property
    def spectrum(self):
        """The spectral model and its arguments as specified in the source file."""
        return self._source[f"{self._source_name}.Spectrum"]

    @property
    def flux(self):
        """Photon flux in photons per square centimeter per second.

        A parsed flux is a string. After :meth:`set_flux`, this property
        returns the value supplied to the setter.
        """
        return self._source[f"{self._source_name}.Flux"]
    
    @property
    def coordinate(self):
        """The source position as an ``astropy.coordinates.SkyCoord``.

        This property reads the last two orientation values as Galactic
        latitude and longitude, in that order and in degrees.
        """

        lon = float(self.orientation.split()[-1])
        lat = float(self.orientation.split()[-2])
        
        return SkyCoord(l = lon, b = lat, unit = "deg", frame = "galactic")

    def list_parameters(self, return_table = False, should_print = True):
        """Display the source directives and their values.

        Set ``return_table=True`` to return a list of ``[key, value]`` rows
        and ``should_print=False`` to skip printing the table.
        """
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
        """The underlying dictionary of source directives and their values."""
        return self._source
    
    def set_coordinate(self, coord):
        
        """Replace latitude and longitude in the existing orientation string.
        
        Parameters
        ----------
        coord : astropy.coordinates.SkyCoord
            A single position in the Galactic frame. The latitude and
            longitude are written in degrees.
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

    def set_flux(self, flux):

        """
        Set the flux of the source.

        Parameters
        ----------
        flux : float
            Photon flux in photons per square centimeter per second.
        """

        self._source[f"{self._source_name}.Flux"] = flux
