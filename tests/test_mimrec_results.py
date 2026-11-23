"""Numerical contracts and optional real ROOT subprocess integration.

Set MEGALIBPY_ROOT_PYTHON to a PyROOT Python executable to run integration tests.
Synthetic files are generated in pytest temporary directories, never shipped as
personal simulation fixtures.
"""

import os
from pathlib import Path
import subprocess
import sys
from dataclasses import replace

import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u
import pytest

from megalibpy import (
    ExecutionResult, HistogramAxis, ImageData, MEGAlibRuntime, ROOTExtractionError,
    ROOTObject, SpectrumData, extract_image, extract_spectrum, list_root_objects,
)


def metadata(dimension=1):
    return ROOTObject("canvas;1/h", "h", "TH1D" if dimension == 1 else "TH2D",
                      "test", dimension, "Energy [keV]", "counts / keV", "")


def test_counts_are_integrated_only_for_density_and_matching_units():
    spectrum = SpectrumData(Path("test.root"), metadata(),
                            HistogramAxis(np.array([1., 2., 5.]), "Energy [keV]", "keV"),
                            np.array([2., 3.]), "counts / keV", "counts/keV", (4., 5.))
    assert spectrum.total_counts == 11  # variable bins, not sum(values)=5
    assert replace(spectrum, value_title="counts", value_unit="counts").total_counts == 5
    for label in ("counts/s/keV", "normalized counts", "Intensity [a.u.]", ""):
        with pytest.raises(ValueError, match="labels"):
            replace(spectrum, value_title=label).total_counts
    with pytest.raises(ValueError, match="labels"):
        replace(spectrum, axis=replace(spectrum.axis, unit="MeV")).total_counts
    with pytest.raises(ValueError, match="Nonfinite"):
        replace(spectrum, values=np.array([1., np.nan])).total_counts


def test_peak_is_native_pixel_center_with_separate_verified_mapping():
    axis = HistogramAxis(np.array([-10., -2., 4.]), "", "deg")
    image = ImageData(Path("test.root"), metadata(2), axis, axis,
                      np.array([[1., 2.], [9., np.nan]]), "Intensity [a.u.]", "a.u.", None)
    assert image.peak_indices == (1, 0)
    assert image.peak_position == (1., -6.)
    assert image.peak_galactic_position is None
    assert image.coordinate_system == image.projection == "unknown"
    mapped = replace(image, longitude_mapping={"scale": -1., "offset": 12.})
    assert mapped.peak_position == image.peak_position
    coordinate = mapped.peak_galactic_position
    assert isinstance(coordinate, SkyCoord) and coordinate.isscalar
    assert coordinate.frame.name == "galactic"
    assert coordinate.l.deg == pytest.approx(11.)  # not a blanket -x
    assert coordinate.b.deg == pytest.approx(-6.)
    assert coordinate.separation(SkyCoord(l=11*u.deg, b=-6*u.deg, frame="galactic")).deg == pytest.approx(0.)
    wrapped = replace(image, longitude_mapping={"scale": -1., "offset": 0.}).peak_galactic_position
    assert wrapped.l.deg == pytest.approx(359.)
    with pytest.raises(ValueError, match="shared"):
        replace(mapped, values=np.ones((2, 2))).peak_galactic_position
    with pytest.raises(ValueError, match="shared"):
        replace(image, values=np.ones((2, 2))).peak_position
    with pytest.raises(ValueError, match="no finite"):
        replace(image, values=np.full((2, 2), np.nan)).peak_position


def test_result_requires_a_unique_correct_product(tmp_path):
    path = tmp_path / "spectrum.root"
    path.touch()
    result = ExecutionResult(tmp_path, {"spectrum": (path, path.with_suffix('.png'))},
                             tmp_path / "manifest.json", None, None)
    # A missing ROOT installation should not mask input-selection errors.
    with pytest.raises(ValueError, match="one ROOT product"):
        extract_image(result)
    with pytest.raises(ValueError, match="one ROOT product"):
        extract_spectrum(replace(result, outputs={"spectrum": (path, tmp_path / 'second.root')}))
    with pytest.raises(ValueError, match="failed"):
        extract_spectrum(replace(result, returncode=1))
    with pytest.raises(FileNotFoundError):
        extract_spectrum(tmp_path / "missing.root")
    with pytest.raises(ValueError, match="positive"):
        extract_spectrum(path, timeout=0)


def test_child_import_failure_is_actionable_and_does_not_import_root(tmp_path):
    path = tmp_path / "input.root"
    path.touch()
    # A standalone Python shim fails before invoking the ROOT worker.
    shim = tmp_path / "missing-root-python"
    shim.write_text('#!/bin/sh\necho "PyROOT missing from selected environment" >&2\nexit 9\n')
    shim.chmod(0o755)
    before = set(sys.modules)
    with pytest.raises(ROOTExtractionError, match="PyROOT missing"):
        extract_spectrum(path, root_python=shim)
    assert ("ROOT" in sys.modules) == ("ROOT" in before)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['input.root', 'missing-root-python']


@pytest.fixture(scope="module")
def root_fixture(tmp_path_factory):
    python = os.environ.get("MEGALIBPY_ROOT_PYTHON")
    if not python:
        pytest.skip("Set MEGALIBPY_ROOT_PYTHON for real ROOT integration")
    directory = tmp_path_factory.mktemp("native-root")
    path = directory / "histograms.root"
    program = r'''
import ROOT, sys
from array import array
ROOT.gROOT.SetBatch(True)
f=ROOT.TFile(sys.argv[1], 'RECREATE')
sub=f.mkdir('nested'); sub.cd()
c=ROOT.TCanvas('canvas','Canvas')
p=ROOT.TPad('pad','Pad',0,0,1,1); p.Draw(); p.cd()
h=ROOT.TH1D('energy/one','Energy;Energy [keV];counts / keV',2,array('d',[1,2,5]))
h.SetDirectory(0); h.SetBinContent(1,2); h.SetBinContent(2,3)
h.SetBinContent(0,7); h.SetBinContent(3,8); h.Draw()
c.Write()
f.cd()
other=ROOT.TH1D('counts','Other;Energy [keV];counts',2,0,10)
other.SetBinContent(1,4); other.SetBinContent(2,5); other.Write()
other.SetBinContent(1,6); other.Write()  # two cycles, must not select latest
profile=ROOT.TProfile('profile','Profile',2,0,10); profile.Write()
th3=ROOT.TH3D('cube','Cube',2,0,1,2,0,1,2,0,1); th3.Write()
ci=ROOT.TCanvas('image','Image')
hi=ROOT.TH2D('image-hist','Image;;Galactic Latitude [deg];Intensity [a.u.]',2,-10,10,2,-5,5)
hi.SetDirectory(0); hi.SetBinContent(1,2,10); hi.Draw('colz')
axis=ROOT.TGaxis(10,-5,-10,-5,100,120,510,'+')
axis.SetTitle('Galactic Longitude [deg]'); axis.Draw(); ci.Write()
unknown=ROOT.TH2D('unknown','Unknown;;Latitude [deg];Intensity',2,-10,10,2,-5,5)
unknown.SetBinContent(1,2,1); unknown.Write()
dup=ROOT.TCanvas('duplicates','Duplicates')
a=ROOT.TH1D('same','A',2,0,1); a.SetDirectory(0); a.Draw()
b=ROOT.TH1D('same','B',2,0,1); b.SetDirectory(0); b.Draw('same'); dup.Write()
f.Close()
'''
    subprocess.run([python, "-c", program, str(path)], check=True, capture_output=True, text=True)
    return python, path


def test_real_root_hierarchy_cycles_and_types(root_fixture):
    python, path = root_fixture
    objects = list_root_objects(path, root_python=python)
    selectors = {obj.object_path for obj in objects}
    assert "nested;1/canvas;1/pad/energy%2Fone" in selectors
    assert {"counts;1", "counts;2"} <= selectors
    assert {"duplicates;1/same[1]", "duplicates;1/same[2]"} <= selectors
    assert all(obj.class_name not in {"TProfile", "TH3D"} for obj in objects)
    with pytest.raises(ROOTExtractionError, match="select object_path"):
        extract_spectrum(path, root_python=python)
    with pytest.raises(ROOTExtractionError, match="select object_path"):
        extract_image(path, root_python=python)
    with pytest.raises(ROOTExtractionError, match="select object_path"):
        extract_spectrum(path, root_python=python, object_path="missing")


def test_real_spectrum_and_execution_result(root_fixture):
    python, path = root_fixture
    result = ExecutionResult(path.parent, {"spectrum": (path,)}, path.parent/'manifest.json', None, None)
    spectrum = extract_spectrum(result, root_python=python,
                                object_path="nested;1/canvas;1/pad/energy%2Fone")
    np.testing.assert_array_equal(spectrum.axis.edges, [1., 2., 5.])
    assert spectrum.axis.unit == "keV" and spectrum.value_unit == "counts/keV"
    assert spectrum.total_counts == 11 and spectrum.flow_values == (7., 8.)
    assert extract_spectrum(path, root_python=python, object_path="counts;1").total_counts == 9
    assert extract_spectrum(path, root_python=python, object_path="counts;2").total_counts == 11
    assert "ROOT" not in sys.modules


def test_real_image_mapping_and_unknown_projection(root_fixture):
    python, path = root_fixture
    image = extract_image(path, root_python=python, object_path="image;1/image-hist")
    assert image.values.shape == (2, 2)
    assert image.peak_position == (-5., 2.5)
    coordinate = image.peak_galactic_position
    assert isinstance(coordinate, SkyCoord)
    assert coordinate.frame.name == "galactic"
    assert coordinate.l.deg == pytest.approx(115.)
    assert coordinate.b.deg == pytest.approx(2.5)
    assert image.coordinate_system == "galactic" and image.projection == "rectangular"
    unknown = extract_image(path, root_python=python, object_path="unknown;1")
    assert unknown.peak_position == (-5., 2.5)
    assert unknown.peak_galactic_position is None


def test_real_setup_mode_and_no_persistent_outputs(root_fixture, tmp_path):
    python, path = root_fixture
    setup = tmp_path / "setup with spaces.sh"
    # Quotes in paths remain shell literals in this generated test script.
    import shlex
    setup.write_text('export PATH=' + shlex.quote(str(Path(python).parent)) + ':"$PATH"\necho setup-output\n')
    original = path.read_bytes()
    contents = set(path.parent.iterdir())
    spectrum = extract_spectrum(path, runtime=MEGAlibRuntime.from_setup_script(setup),
                                object_path="nested;1/canvas;1/pad/energy%2Fone")
    assert spectrum.total_counts == 11
    assert path.read_bytes() == original
    assert set(path.parent.iterdir()) == contents


def test_reader_timeout(tmp_path):
    path = tmp_path / "input.root"
    path.touch()
    shim = tmp_path / "sleep-python"
    shim.write_text('#!/bin/sh\nexec sleep 10\n')
    shim.chmod(0o755)
    with pytest.raises(ROOTExtractionError, match="timed out"):
        extract_spectrum(path, root_python=shim, timeout=0.05)
