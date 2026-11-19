import pytest
from astropy.coordinates import SkyCoord

from megalibpy import BaseParams, MEGAlibSource, test_data


@pytest.fixture
def template():
    return test_data / "GRB_ml_template.source"


def test_read_base_parameters(template):
    base = BaseParams.read_from_file(template)

    assert base.version == "1"
    assert base.physics_list_em == "LivermorePol"
    assert base.store_simulation_info == "init-only"
    assert base.pre_trigger_mode == "EveryEventWithHits"
    assert base.geometry.endswith("COSISMEX.geo.setup")


def test_read_galactic_coordinates(template):
    coord = MEGAlibSource(template).source.coordinate

    assert coord.l.deg == pytest.approx(44.6)
    assert coord.b.deg == pytest.approx(-21.6)


def test_edit_save_and_reread_source_file(template, tmp_path):
    config = MEGAlibSource(template)
    config.set_coordinate(SkyCoord(l=241.5, b=2.4, unit="deg", frame="galactic"))
    config.set_flux(8.5)
    output = tmp_path / "modified.source"
    config.save_source_file(output)

    reread = MEGAlibSource(output)
    assert reread.run_config.run_name == config.run_config.run_name
    assert reread.run_config.orientation_sky == config.run_config.orientation_sky
    assert reread.source.spectrum == config.source.spectrum
    assert reread.source.coordinate.l.deg == pytest.approx(241.5)
    assert reread.source.coordinate.b.deg == pytest.approx(2.4)
    assert float(reread.source.flux) == pytest.approx(8.5)


def test_run_config_legacy_aliases(template):
    from megalibpy import Run, RunConfig
    from megalibpy.megalib_source import Run as PackageRun
    from megalibpy.megalib_source import RunConfig as PackageRunConfig
    from megalibpy.megalib_source.run import Run as LegacyRun

    config = MEGAlibSource(template)
    assert Run is PackageRun is LegacyRun is PackageRunConfig is RunConfig
    assert config.run is config.run_config
    assert isinstance(config.run_config, RunConfig)
    assert Run.read_from_file(template).run_name == config.run_config.run_name
    assert Run(run_name="Example").run_name == "Example"
