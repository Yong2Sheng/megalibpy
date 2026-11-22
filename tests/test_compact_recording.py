"""Quota-oriented recording: native inputs exist only while the child needs them."""

import hashlib
import json
from pathlib import Path
import sys

import pytest

from megalibpy import Cosima, ExecutionError, MEGAlibRuntime, Mimrec, Revan, SimulationWorkspace
from megalibpy.execution.provenance import decode_content


@pytest.fixture
def native(tmp_path, monkeypatch):
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    tools = tmp_path/'tools'
    tools.mkdir()
    code = f'#!{sys.executable}\n'+'''
from pathlib import Path
import os,sys
args = sys.argv[1:]
name = Path(sys.argv[0]).name
mode = os.environ.get('FAKE_MODE','success')
if name == 'cosima':
    text = Path(args[-1]).read_text()
    prefix = next(l.split()[1] for l in text.splitlines() if '.FileName ' in l)
    os.write(1,b'event data\\n'*200000)
    if mode == 'failure':
        os.write(2,b'fatal native error\\n')
        sys.exit(7)
    if mode != 'no-summary':
        os.write(1,b'\\nSummary for run Burst\\nTotal number of generated particles: 454830\\nGraphics systems deleted.\\n')
    Path(prefix+'.inc1.id1.sim.gz').write_bytes(b'sim')
else:
    cfg = Path(args[args.index('-c')+1])
    assert cfg.read_bytes()
    Path(args[args.index('-o')+1]).write_bytes(b'product')
    os.write(1,b'verbose analysis\\n'*10000+b'FINAL ANALYSIS\\n')
'''
    for name in ('cosima','revan','mimrec'):
        tool = tools/name
        tool.write_text(code)
        tool.chmod(0o755)
    setup = tmp_path/'init.sh'
    setup.write_text(f'export PATH="{tools}:$PATH"\n')
    ori = tmp_path/'three-months.ori'
    with ori.open('wb') as out:
        out.truncate(1024**3)  # sparse: no gigabyte read/write in this test
    source = tmp_path/'burst.source'
    source.write_text(f'Run Burst\nBurst.FileName old\nBurst.Time 1\nBurst.OrientationSky Galactic File NoLoop {ori}\n')
    cfg = tmp_path/'analysis.cfg'
    cfg.write_bytes(b'opaque native bytes & legacy <SpectrumBefore)>\r\n')
    return source, cfg, setup, ori


def test_compact_full_chain_without_resource_copies_and_summary(native, tmp_path, monkeypatch):
    source, cfg, setup, ori = native
    original_read = Path.read_bytes
    def guarded(path):
        if path == ori:
            raise AssertionError('large orientation file was read by Python')
        return original_read(path)
    monkeypatch.setattr(Path, 'read_bytes', guarded)
    runtime = MEGAlibRuntime.from_setup_script(setup)
    workspace = SimulationWorkspace(tmp_path/'experiment')
    simulated = Cosima(runtime).simulate(source, workspace=workspace, seed=12345, log_mode='summary')
    record = simulated.record
    assert simulated.stdout_path.read_bytes().startswith(b'Summary for run Burst')
    assert b'event data' not in simulated.stdout_path.read_bytes()
    assert simulated.stderr_path is None
    assert record['logs']['stderr'] is None
    assert record['logs']['capture']['stdout']['bytes_seen'] > 1000000
    assert record['logs']['capture']['stdout']['summary_found']
    assert record['logs']['capture']['stdout']['bytes_retained'] < 4096
    assert record['dependencies'][0]['path'] == str(ori)
    assert record['dependencies'][0]['sha256'] is None
    assert 'snapshot' not in record['dependencies'][0]
    executed = decode_content(record['source']['executed'])
    assert str(workspace.root/'cosima/products/events').encode() in executed
    assert decode_content(record['source']['original']) == source.read_bytes()
    reconstructed = Revan(runtime).reconstruct(simulated, config_file=cfg, log_mode="full")
    mimrec = Mimrec(runtime)
    selected = mimrec.extract_events(reconstructed, config_file=cfg, log_mode="full")
    expected = hashlib.sha256(cfg.read_bytes()).hexdigest()
    cfg.unlink()  # inherited config comes from manifest, not the original file
    image = mimrec.image(selected, output_name='image.png', log_mode='full')
    spectrum = mimrec.spectrum(selected, output_name='spectrum.png', log_mode='full')
    for result in (reconstructed, selected, image, spectrum):
        assert result.record['configuration']['executed_sha256'] == expected
        assert result.record['configuration_overrides'] == []  # Python log options are not native -C settings
        assert result.record['configuration']['executed_snapshot'] is None
        assert decode_content(result.record['configuration']).startswith(b'opaque native bytes')
        assert result.stderr_path is None
        assert result.stdout_path.read_bytes().endswith(b'FINAL ANALYSIS\n')
        assert result.record['runtime']['executable']['path'].endswith(result.record['tool'])
    assert not list(workspace.root.rglob('*.cfg'))
    assert not list(workspace.root.rglob('*.source'))
    assert not list(workspace.root.rglob('*.ori'))
    assert not list(workspace.root.rglob('*.sh'))
    assert not list(workspace.root.rglob('*.txt'))
    assert not list(workspace.root.rglob('*.stderr.log'))
    assert all(p.stat().st_size for p in workspace.root.rglob('*.log'))
    for record in json.loads(workspace.index_path.read_text())['executions'].values():
        assert record['runtime']['setup_script']['original_path'] == str(setup)
        assert record['runtime']['setup_script']['sha256']
        assert 'content' not in record['runtime']['setup_script']
        assert not Path(record['launch_command'][3]).exists()
    assert workspace.select('mimrec', operation='image').stderr_path is None


@pytest.mark.parametrize('mode', ['failure','no-summary'])
def test_summary_missing_is_explicit_and_does_not_substitute_a_tail(native, tmp_path, monkeypatch, mode):
    source, cfg, setup, _ = native
    monkeypatch.setenv('FAKE_MODE', mode)
    runtime = MEGAlibRuntime.from_setup_script(setup)
    workspace = SimulationWorkspace(tmp_path/'experiment')
    if mode == 'failure':
        with pytest.raises(ExecutionError) as error:
            Cosima(runtime).simulate(source, workspace=workspace, log_mode='summary')
        record = json.loads(workspace.index_path.read_text())['executions'][error.value.execution_id]
        assert record['returncode'] == 7
        stderr = workspace.root/record['execution_dir']/record['logs']['stderr']
        assert b'fatal native error' in stderr.read_bytes()
    else:
        record = Cosima(runtime).simulate(source, workspace=workspace, log_mode='summary').record
    capture = record['logs']['capture']['stdout']
    assert capture['summary_missing']
    assert capture['bytes_retained'] == 0
    assert record['logs']['stdout'] is None
    assert not list(workspace.root.rglob('*.source'))
    assert not list(workspace.root.rglob('*.sh'))


def test_opaque_non_utf8_configuration_is_lossless(native, tmp_path):
    _, cfg, setup, _ = native
    content = b'legacy bytes \xff\x80 & <NativeTag)>'
    cfg.write_bytes(content)
    tra = tmp_path/'external.tra'
    tra.write_bytes(b'events')
    runner = Mimrec(MEGAlibRuntime.from_setup_script(setup))
    selected = runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    cfg.unlink()
    result = runner.image(selected)
    assert result.record['configuration']['encoding'] == 'base64'
    assert decode_content(result.record['configuration']) == content
