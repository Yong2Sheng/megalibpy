from importlib.metadata import version

import pytest

import megalibpy


@pytest.mark.smoke
def test_installed_version():
    assert megalibpy.__version__ == version("megalibpy")
    assert megalibpy.Revan().executable == "revan"
    assert megalibpy.SimulationWorkspace is not None


@pytest.mark.smoke
def test_read_packaged_template():
    config = megalibpy.MEGAlibSource(megalibpy.test_data / "GRB_ml_template.source")

    assert isinstance(config.run, megalibpy.Run)
    assert isinstance(config.source, megalibpy.Source)
    assert config.run.run_name == "GRBSim"
    assert float(config.source.flux) == pytest.approx(20.6)
