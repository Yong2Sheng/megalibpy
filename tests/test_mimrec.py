"""Native-command contract tests; stand-ins do not validate scientific results."""

import json
import os
from pathlib import Path
import sys

import pytest

from megalibpy import ExecutionError, MEGAlibRuntime, Mimrec, Revan, SimulationWorkspace
from megalibpy.execution import ExecutionInput


@pytest.fixture
def analysis(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cfg = tmp_path / "config dir" / "analysis.cfg"
    cfg.parent.mkdir()
    cfg.write_bytes(b'<SpectrumBefore)>true</SpectrumBefore)>\r\nraw A&B; ~/native_file\r\n')
    tra = tmp_path / "received.tra.gz"
    tra.write_bytes(b"opaque native event data")
    tool = tmp_path / "native tool"
    tool.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys, time
args = sys.argv[1:]
get = lambda flag: args[args.index(flag) + 1]
assert '-n' in args
assert sum(flag in args for flag in ['-x','-i','-s','-a']) == 1
print(json.dumps({'argv': args, 'cwd': str(pathlib.Path.cwd()),
 'home': os.environ['HOME'], 'setup_home': os.environ.get('SETUP_HOME')}), flush=True)
(pathlib.Path(os.environ['HOME']) / '.mimrec.cfg').write_text('native settings')
content = pathlib.Path(get('-c')).read_bytes()
if content == b'exit': sys.exit(9)
if content == b'sleep': time.sleep(20)
if content != b'missing': pathlib.Path(get('-o')).write_bytes(b'native product')
''')
    tool.chmod(0o755)
    return tra, cfg, tool


def read(result):
    return result.record


@pytest.mark.parametrize('operation,flag,group,filename', [
    ('extract_events','-x','tra','events.tra.gz'), ('image','-i','image','image.root'),
    ('spectrum','-s','spectrum','spectrum.root'), ('arm','-a','arm','arm.root'),
])
def test_operations_preserve_configuration_and_prepare_native_flags(analysis, tmp_path, operation, flag, group, filename):
    tra, cfg, tool = analysis
    original = cfg.read_bytes()
    result = getattr(Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool), operation)(
        tra_path=tra, output_dir=tmp_path / 'experiment', config_file=cfg,
        geometry='$(MEGALIB)/missing_model.geo.setup', EventSelections_TimeMode=1,
        Any_Native_Value='raw_value = a=b', Some_Bool=True, Other_Bool=False)
    record = read(result)
    command = record['command']
    assert command[-2:] == ['-n', flag]
    assert command[command.index('-f') + 1] == str(tra)
    assert command[command.index('-g') + 1] == '$(MEGALIB)/missing_model.geo.setup'
    changes = [command[i+1] for i, arg in enumerate(command) if arg == '-C']
    assert changes == ['EventSelections.TimeMode=1', 'Any.Native.Value=raw_value = a=b',
                       'Some.Bool=true', 'Other.Bool=false']
    assert result.outputs[group][0].name == filename
    assert result.output_dir == tmp_path / 'experiment/mimrec/attempt-001'
    assert record['operation'] == operation
    assert record['cwd'] == str(cfg.parent)
    assert record['configuration']['original_sha256'] == record['configuration']['executed_sha256']
    assert (result.output_dir / 'inputs/executed.mimrec.cfg').read_bytes() == original
    assert cfg.read_bytes() == original
    assert record['input_file']['hash_policy'] == 'size_and_mtime_only'
    assert record['upstream'] == []
    assert 'dependencies' not in record
    assert (Path(os.environ['HOME']) / '.mimrec.cfg').is_file()


def test_external_origin_reopen_and_extraction_fanout(analysis, tmp_path):
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    selected = runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    workspace = SimulationWorkspace(selected.workspace_dir)
    assert workspace.external_tra_path == tra
    assert workspace.external_sim_path is None
    index = json.loads(workspace.index_path.read_text())
    assert index['origin'] == {'kind': 'external_tra', 'path': str(tra)}
    image = runner.image(selected, config_file=cfg, output_name='image [v1].png')
    spectrum = runner.spectrum(selected.as_input('tra'), config_file=cfg)
    for result in (image, spectrum):
        assert read(result)['upstream'][0]['execution_id'] == selected.execution_id
        assert read(result)['input_file']['path'] == str(selected.outputs['tra'][0])
        assert 'manifest_snapshot' not in read(result)['upstream'][0]
        assert '-g' not in read(result)['command']
    reopened = runner.arm(working_space=workspace.root, config_file=cfg)
    assert read(reopened)['input_file']['path'] == str(tra)
    assert workspace.select('mimrec', task='image').execution_id == image.execution_id
    other = tmp_path/'background.tra'
    other.write_bytes(b'other input')
    runner.extract_events(tra_path=other, output_dir=workspace.root, config_file=cfg, task='background')
    assert workspace.external_tra_path == tra
    with pytest.raises(ValueError, match='origin'):
        workspace.execute('cosima', 'simulation', lambda p: None)
    with pytest.raises(ValueError, match='different external'):
        workspace.attach_sim(tmp_path/'different.sim')


def test_revan_handoff_and_branch_selection_keep_primary_origin(analysis, tmp_path):
    tra, cfg, tool = analysis
    sim = tmp_path/'events.sim'
    sim.write_bytes(b'sim')
    # Same stand-in supports -a; no event/configuration parser is involved.
    runner = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    a = runner.reconstruct(sim_path=sim, output_dir=tmp_path/'experiment', config_file=cfg, task='a')
    workspace = SimulationWorkspace(a.workspace_dir)
    mimrec = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    first = mimrec.extract_events(working_space=workspace.root, config_file=cfg)
    assert read(first)['upstream'][0]['execution_id'] == a.execution_id
    runner.reconstruct(working_space=workspace, config_file=cfg, task='b')
    with pytest.raises(ValueError, match='found 2'):
        mimrec.image(working_space=workspace, config_file=cfg)
    selected = workspace.select('revan', task='a')
    image = mimrec.image(selected, config_file=cfg)
    assert read(image)['upstream'][0]['execution_id'] == a.execution_id
    mimrec.extract_events(tra_path=tra, output_dir=workspace.root, config_file=cfg, task='external')
    assert workspace.external_sim_path == sim
    assert workspace.external_tra_path is None
    again = mimrec.extract_events(selected, config_file=cfg)
    assert again.output_dir.name == 'attempt-004'
    assert first.outputs['tra'][0].exists()
    with pytest.raises(ValueError, match='found 2'):
        workspace.select('mimrec', task='extract_events')


def test_setup_and_optional_home_isolation(analysis, tmp_path):
    tra, cfg, tool = analysis
    original = cfg.read_bytes()
    home = os.environ['HOME']
    setup = tmp_path/'setup.sh'
    setup.write_text('export SETUP_HOME="$HOME"\n')
    result = Mimrec(MEGAlibRuntime.from_setup_script(setup, archive_inputs=True), executable=tool).extract_events(
        tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg,
        output_name='events.tra', isolate_settings=True)
    output = json.loads(result.stdout_path.read_text())
    assert output['setup_home'] == home
    assert output['home'] == str(result.output_dir/read(result)['configuration']['settings_home'])
    assert os.environ['HOME'] == home
    assert cfg.read_bytes() == original
    assert not (Path(home)/'.mimrec.cfg').exists()
    assert result.outputs['tra'][0].name == 'events.tra'


@pytest.mark.parametrize('mode', ['empty', 'deleted', 'exit', 'missing', 'sleep'])
def test_failure_records_remain_indexed(analysis, tmp_path, mode):
    tra, cfg, tool = analysis
    if mode == 'deleted': cfg.unlink()
    else: cfg.write_bytes(b'' if mode == 'empty' else mode.encode())
    workspace = SimulationWorkspace(tmp_path/'experiment')
    with pytest.raises(ExecutionError) as error:
        Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).image(tra_path=tra, output_dir=workspace.root, config_file=cfg,
                                      timeout=0.15 if mode == 'sleep' else None)
    record = next(iter(json.loads(error.value.manifest_path.read_text())["executions"].values()))
    assert record['status'] == 'failed'
    assert next(iter(json.loads(workspace.index_path.read_text())['executions'].values()))['status'] == 'failed'
    if mode == 'exit': assert error.value.returncode == 9
    if mode == 'missing': assert error.value.returncode == 0


@pytest.mark.parametrize('arguments', [{}, {'tra_path':'file.tra'},
    {'working_space':'root','tra_path':'file.tra','output_dir':'root'},
    {'tra_path':'file.tra','output_dir':'root','output_name':'../outside.root'},
    {'tra_path':'file.tra','output_dir':'root','timeout':0}])
def test_argument_conflicts_rejected_before_allocation(analysis, arguments):
    _, cfg, tool = analysis
    with pytest.raises(ValueError):
        Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).image(config_file=cfg, **arguments)


def test_explicit_product_subset_and_wrong_group(analysis, tmp_path):
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    upstream = runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    record = read(upstream)
    second = upstream.outputs['tra'][0].parent/'second.tra'
    second.write_bytes(b'another native shard')
    record['outputs']['tra'].append(str(second.relative_to(upstream.output_dir)))
    workspace_record = json.loads(upstream.manifest_path.read_text())
    workspace_record['executions'][upstream.execution_id] = record
    upstream.manifest_path.write_text(json.dumps(workspace_record))
    reference = ExecutionInput(upstream.manifest_path, 'tra', upstream.execution_id,
                               workspace_dir=upstream.workspace_dir)
    with pytest.raises(ValueError, match='select one file'):
        runner.image(reference, config_file=cfg)
    selected = runner.image(upstream.as_input('tra', paths=[second]), config_file=cfg)
    assert read(selected)['input_file']['path'] == str(second)
    with pytest.raises(ValueError, match="'tra' output group"):
        runner.image(selected.as_input('image'), config_file=cfg)


def test_full_cosima_revan_mimrec_chain_with_standins(analysis, tmp_path):
    from megalibpy import Cosima

    _, cfg, tool = analysis
    source = tmp_path/'grb.source'
    source.write_text('Run Burst\nBurst.FileName old\nBurst.Time 1\n')
    cosima = tmp_path/'cosima-standin'
    cosima.write_text(f'#!{sys.executable}\n' + '''
from pathlib import Path
import sys
text = Path(sys.argv[-1]).read_text()
prefix = next(l.split()[1] for l in text.splitlines() if '.FileName ' in l)
Path(prefix + '.inc1.id1.sim.gz').write_bytes(b'native simulation')
''')
    cosima.chmod(0o755)
    workspace = SimulationWorkspace(tmp_path/'experiment')
    simulated = Cosima(MEGAlibRuntime.direct(archive_inputs=True), executable=cosima).simulate(source, workspace=workspace, seed=12345)
    reconstructed = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(simulated, config_file=cfg, task='baseline')
    mimrec = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    selected = mimrec.extract_events(reconstructed, config_file=cfg)
    image = mimrec.image(selected, config_file=cfg)
    assert read(image)['upstream'][0]['execution_id'] == selected.execution_id
    assert read(selected)['upstream'][0]['execution_id'] == reconstructed.execution_id
    assert read(reconstructed)['upstream'][0]['execution_id'] == simulated.execution_id
    assert workspace.select('cosima').execution_id == simulated.execution_id
    assert workspace.external_tra_path is None
    assert json.loads(workspace.index_path.read_text())['origin']['kind'] == 'cosima'


def test_plot_filename_requires_suffix_without_format_whitelist(analysis, tmp_path):
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    with pytest.raises(ValueError, match='explicit native output suffix'):
        runner.image(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg, output_name='image')
    with pytest.raises(ValueError, match='must end in'):
        runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg, output_name='image.root')
    result = runner.image(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg, output_name='image.custom')
    assert result.outputs['image'][0].name == 'image.custom'


def test_data_group_defaults_variants_and_single_manifest(analysis, tmp_path):
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    selected = runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg,
                                     geometry='literal-model.setup', task='event-selected',
                                     EventSelections_TimeMode=1)
    baseline = (selected.output_dir/'inputs/executed.mimrec.cfg').read_bytes()
    image = runner.image(selected, task='image-selected', output_name='image.png')
    spectrum = runner.spectrum(selected, task='spectrum')
    assert selected.output_dir == image.output_dir == spectrum.output_dir
    for result in (image, spectrum):
        record = read(result)
        assert record['configuration']['executed_sha256'] == read(selected)['configuration']['executed_sha256']
        assert record['geometry'] == 'literal-model.setup'
        assert record['configuration_overrides'] == [{'parameter':'EventSelections.TimeMode','value':'1'}]
        assert record['upstream'][0]['execution_id'] == selected.execution_id
        assert 'manifest_snapshot' not in record['upstream'][0]
    assert image.outputs['image'][0] == selected.output_dir/'image-selected/image.png'
    assert list(selected.workspace_dir.rglob('manifest.json')) == [selected.manifest_path]
    assert len(list((selected.output_dir/'inputs').glob('*.cfg'))) == 1
    assert len(list((selected.output_dir/'logs').glob('*.stdout.log'))) == 3
    repeated = runner.image(selected, task='image-selected', output_name='image.png')
    assert repeated.outputs['image'][0].name == 'image-002.png'
    assert image.outputs['image'][0].exists()
    cfg.write_bytes(b'different projection settings; no XML parsing')
    with pytest.warns(UserWarning, match='settings differ'):
        variant = runner.image(selected, config_file=cfg, geometry='literal-model.setup',
                               EventSelections_TimeMode=1, task='projection-b')
    assert (selected.output_dir/'inputs/executed.mimrec.cfg').read_bytes() == baseline
    variant_path = selected.output_dir/read(variant)['configuration']['executed_snapshot']
    assert variant_path.read_bytes() == cfg.read_bytes()
    assert variant_path.name != 'executed.mimrec.cfg'
    inherited = runner.spectrum(selected, task='inherited-after-variant')
    assert read(inherited)['configuration']['executed_sha256'] == read(selected)['configuration']['executed_sha256']
    # Reopen explicitly: the selected extraction, rather than an unrelated Revan,
    # supplies the data and the group's original defaults.
    reopened = runner.arm(working_space=selected.workspace_dir, attempt='attempt-001')
    assert read(reopened)['upstream'][0]['execution_id'] == selected.execution_id
    assert reopened.output_dir == selected.output_dir
    other = tmp_path/'other.tra'
    other.write_bytes(b'unrelated events')
    with pytest.raises(ValueError, match='different TRA input'):
        runner.image(tra_path=other, output_dir=selected.workspace_dir, attempt='attempt-001')


def test_record_hash_is_stable_across_workspace_growth(analysis, tmp_path):
    from megalibpy.execution.provenance import resolve_upstream
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    selected = runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    _, before = resolve_upstream(selected.as_input('tra'))
    runner.image(selected)
    _, after = resolve_upstream(selected.as_input('tra'))
    assert before['manifest_sha256'] == after['manifest_sha256']
    assert before['execution_id'] == after['execution_id']


def test_output_collision_is_rejected_without_overwrite(analysis, tmp_path):
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    selected = runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    image = runner.image(selected, task='plots', output_name='same.root')
    original = image.outputs['image'][0].read_bytes()
    with pytest.raises(ExecutionError, match='reserved'):
        runner.spectrum(selected, task='plots', output_name='same.root')
    assert image.outputs['image'][0].read_bytes() == original


def test_configuration_changes_warn_without_requiring_configuration_parser(analysis, tmp_path):
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    selected = runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    with pytest.warns(UserWarning, match='settings differ'):
        changed = runner.image(selected, Any_Value='projection_only')
    assert read(changed)['configuration_overrides'] == [{'parameter':'Any.Value','value':'projection_only'}]
    assert read(selected)['configuration_overrides'] == []


def test_cross_workspace_record_snapshot_and_new_origin(analysis, tmp_path):
    from megalibpy.execution.provenance import resolve_upstream
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    selected = runner.extract_events(tra_path=tra, output_dir=tmp_path/'first', config_file=cfg)
    image = runner.image(selected, output_dir=tmp_path/'second', config_file=cfg)
    record = read(image)
    snapshot = image.output_dir/record['upstream'][0]['manifest_snapshot']
    archived = json.loads(snapshot.read_text())
    assert archived['execution_id'] == selected.execution_id
    assert 'executions' not in archived  # archive one record, not the expanding workspace
    assert json.loads(image.manifest_path.read_text())['origin']['kind'] == 'execution_reference'
    before = resolve_upstream(selected.as_input('tra'))[1]['manifest_sha256']
    runner.spectrum(selected)
    assert resolve_upstream(selected.as_input('tra'))[1]['manifest_sha256'] == before
    assert json.loads(snapshot.read_text()) == archived


def test_failed_operation_has_exact_id_and_keeps_group_defaults(analysis, tmp_path):
    tra, cfg, tool = analysis
    runner = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    selected = runner.extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    cfg.write_bytes(b'exit')
    with pytest.warns(UserWarning):
        with pytest.raises(ExecutionError) as error:
            runner.image(selected, config_file=cfg)
    failure = json.loads(error.value.manifest_path.read_text())['executions'][error.value.execution_id]
    assert failure['status'] == 'failed'
    assert failure['data_group'] == read(selected)['data_group']
    assert error.value.execution_id != selected.execution_id
    image = runner.image(selected)
    assert read(image)['configuration']['executed_sha256'] == read(selected)['configuration']['executed_sha256']


def test_external_tra_cannot_be_processed_as_revan_sim_input(analysis, tmp_path):
    tra, cfg, tool = analysis
    selected = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    with pytest.raises(ValueError, match='found 0'):
        Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(working_space=selected.workspace_dir, config_file=cfg)


def test_central_execution_directory_cannot_escape_workspace(analysis, tmp_path):
    from megalibpy.execution.provenance import resolve_upstream
    tra, cfg, tool = analysis
    selected = Mimrec(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    data = json.loads(selected.manifest_path.read_text())
    data['executions'][selected.execution_id]['execution_dir'] = '..'
    selected.manifest_path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='within the workspace'):
        resolve_upstream(selected.as_input('tra'))


def test_analysis_id_binds_group_without_repeating_identifier(analysis, tmp_path):
    tra, cfg, tool = analysis
    runner = Mimrec(executable=tool, analysis_id='baseline')
    root = tmp_path/'experiment'
    assert not root.exists()
    selected = runner.extract_events(tra_path=tra, output_dir=root, config_file=cfg, task='event-selected')
    spectrum = runner.spectrum(selected, output_name='spectrum.png')
    image = runner.image(working_space=root, task='image-selected', output_name='image.png')
    assert selected.output_dir == spectrum.output_dir == image.output_dir == root/'mimrec/baseline'
    assert selected.outputs['tra'][0] == root/'mimrec/baseline/event-selected/events.tra.gz'
    assert read(image)['upstream'][0]['execution_id'] == selected.execution_id
    assert read(spectrum)['upstream'][0]['execution_id'] == selected.execution_id
    assert read(image)['configuration']['executed_sha256'] == read(selected)['configuration']['executed_sha256']
    assert len({selected.execution_id,spectrum.execution_id,image.execution_id}) == 3
    # Existing automatic groups continue working alongside user-named groups.
    automatic = Mimrec(executable=tool).extract_events(tra_path=tra, output_dir=root, config_file=cfg)
    assert automatic.output_dir.name == 'attempt-001'


def test_two_named_analysis_groups_and_cross_workspace_scope(analysis, tmp_path):
    tra, cfg, tool = analysis
    root = tmp_path/'experiment'
    a = Mimrec(executable=tool, analysis_id='selection-a')
    b = Mimrec(executable=tool, analysis_id='selection-b')
    selected_a = a.extract_events(tra_path=tra, output_dir=root, config_file=cfg)
    cfg_b = cfg.with_name('alternative.cfg')
    cfg_b.write_bytes(b'another native configuration')
    selected_b = b.extract_events(tra_path=tra, output_dir=root, config_file=cfg_b)
    assert selected_a.output_dir != selected_b.output_dir
    assert read(selected_a)['configuration']['executed_sha256'] != read(selected_b)['configuration']['executed_sha256']
    assert a.image(selected_a).output_dir == selected_a.output_dir
    assert b.spectrum(selected_b).output_dir == selected_b.output_dir
    with pytest.raises(ValueError, match='different TRA input'):
        a.image(selected_b)
    other = a.extract_events(tra_path=tra, output_dir=tmp_path/'another-experiment', config_file=cfg_b)
    assert other.output_dir == tmp_path/'another-experiment/mimrec/selection-a'


@pytest.mark.parametrize('identifier', ['', '../outside', '/absolute', 'a/b', 'a b', 3])
def test_invalid_analysis_id_is_rejected(identifier):
    with pytest.raises(ValueError, match='analysis_id'):
        Mimrec(analysis_id=identifier)


def test_bound_analysis_id_reopens_old_numbered_group_and_rejects_conflict(analysis, tmp_path):
    tra, cfg, tool = analysis
    selected = Mimrec(executable=tool).extract_events(tra_path=tra, output_dir=tmp_path/'experiment', config_file=cfg)
    reopened = Mimrec(executable=tool, analysis_id='attempt-001')
    image = reopened.image(working_space=selected.workspace_dir)
    assert image.output_dir == selected.output_dir
    with pytest.raises(ValueError, match='conflicts'):
        reopened.image(selected, attempt='attempt-002')


def test_revan_and_mimrec_analysis_branches_keep_exact_chain(analysis, tmp_path):
    _, cfg, tool = analysis
    sim = tmp_path/'received.sim'
    sim.write_bytes(b'one simulation origin')
    root = tmp_path/'experiment'
    a = Revan(executable=tool, analysis_id='branch-a').reconstruct(
        sim_path=sim, output_dir=root, config_file=cfg)
    b = Revan(executable=tool, analysis_id='branch-b').reconstruct(
        working_space=root, config_file=cfg, TotalEnergy_Min=100)
    ma = Mimrec(executable=tool, revan_analysis_id='branch-a')
    mb = Mimrec(executable=tool, revan_analysis_id='branch-b')
    selected_a = ma.extract_events(working_space=root, config_file=cfg)
    selected_b = mb.extract_events(working_space=root, config_file=cfg)
    image_a = ma.image(working_space=root)
    image_b = mb.image(working_space=root)
    for selected, reconstructed, image, identifier in (
            (selected_a,a,image_a,'branch-a'), (selected_b,b,image_b,'branch-b')):
        assert read(selected)['upstream'][0]['execution_id'] == reconstructed.execution_id
        assert read(image)['upstream'][0]['execution_id'] == selected.execution_id
        assert read(selected)['analysis_id'] == identifier
        assert read(reconstructed)['analysis_id'] == identifier
        assert SimulationWorkspace(root).select('revan', analysis_id=identifier).execution_id == reconstructed.execution_id
        assert SimulationWorkspace(root).select('mimrec', analysis_id=identifier, operation='image').execution_id == image.execution_id
    assert read(a)['configuration_overrides'] == []
    assert read(b)['configuration_overrides'] == [{'parameter':'TotalEnergy.Min','value':'100'}]
    assert json.loads((root/'manifest.json').read_text())['origin']['path'] == str(sim)


def test_different_mimrec_names_can_share_one_explicit_revan_parent(analysis, tmp_path):
    _, cfg, tool = analysis
    sim = tmp_path/'events.sim'
    sim.write_bytes(b'one origin')
    root = tmp_path/'experiment'
    reconstructed = Revan(executable=tool, analysis_id='reconstruction').reconstruct(
        sim_path=sim, output_dir=root, config_file=cfg)
    for name in ('selection-a','selection-b'):
        runner = Mimrec(executable=tool, analysis_id=name)
        selected = runner.extract_events(reconstructed, config_file=cfg)
        image = runner.image(working_space=root)
        assert read(selected)['upstream'][0]['execution_id'] == reconstructed.execution_id
        assert read(image)['upstream'][0]['execution_id'] == selected.execution_id
    # Reopening an image-only group preserves its explicitly registered parent,
    # even though there is no same-name Revan group and no extraction output.
    direct = Mimrec(executable=tool, analysis_id='projection-only')
    image = direct.image(reconstructed, config_file=cfg)
    spectrum = direct.spectrum(working_space=root)
    assert read(image)['upstream'][0]['execution_id'] == reconstructed.execution_id
    assert read(spectrum)['upstream'][0]['execution_id'] == reconstructed.execution_id
    with pytest.raises(ValueError, match='revan_analysis_id is required'):
        Mimrec(executable=tool, analysis_id='missing').image(working_space=root, config_file=cfg)


def test_multiple_successful_extractions_require_explicit_execution(analysis, tmp_path):
    tra, cfg, tool = analysis
    root = tmp_path/'experiment'
    runner = Mimrec(executable=tool, analysis_id='baseline')
    first = runner.extract_events(tra_path=tra, output_dir=root, config_file=cfg)
    second = runner.extract_events(tra_path=tra, output_dir=root)
    with pytest.raises(ValueError, match='found 2'):
        runner.image(working_space=root)
    image = runner.image(second)
    assert read(image)['upstream'][0]['execution_id'] == second.execution_id
    assert read(image)['upstream'][0]['execution_id'] != first.execution_id


def test_explicit_revan_parent_and_independent_mimrec_analysis_names(analysis, tmp_path):
    _, cfg, tool = analysis
    sim = tmp_path/'events.sim'
    sim.write_bytes(b'sim')
    root = tmp_path/'experiment'
    a = Revan(executable=tool, analysis_id='reconstruction-a').reconstruct(
        sim_path=sim, output_dir=root, config_file=cfg)
    b = Revan(executable=tool, analysis_id='reconstruction-b').reconstruct(
        working_space=root, config_file=cfg)
    for own in (None, 'selection-loose', 'selection-strict'):
        runner = Mimrec(executable=tool, revan_analysis_id='reconstruction-a', analysis_id=own)
        name = own or 'reconstruction-a'
        assert runner.analysis_id == name
        selected = runner.extract_events(working_space=root, config_file=cfg)
        image = runner.image(working_space=root)
        assert selected.output_dir == root/'mimrec'/name
        assert read(selected)['revan_analysis_id'] == 'reconstruction-a'
        assert read(selected)['analysis_id'] == name
        assert read(selected)['upstream'][0]['execution_id'] == a.execution_id
        assert read(image)['upstream'][0]['execution_id'] == selected.execution_id
        assert read(image)['revan_analysis_id'] == 'reconstruction-a'
        with pytest.raises(ValueError, match='Revan analysis mismatch'):
            runner.extract_events(b)
    with pytest.raises(ValueError, match='Revan analysis mismatch'):
        Mimrec(executable=tool, revan_analysis_id='reconstruction-b', analysis_id='selection-loose').image(working_space=root)


@pytest.mark.parametrize('identifier', ['', '../escape', 'a/b', 3])
def test_invalid_revan_parent_identifier_is_rejected(identifier):
    with pytest.raises(ValueError, match='revan_analysis_id'):
        Mimrec(revan_analysis_id=identifier)


def test_bound_workspace_full_chain_and_independent_selections(analysis, tmp_path):
    _, cfg, tool = analysis
    sim = tmp_path/'events.sim'
    sim.write_bytes(b'sim')
    root = tmp_path/'experiment'
    revan = Revan(working_space=root, executable=tool, analysis_id='reconstruction-a')
    assert revan.working_space == root
    assert not root.exists()
    reconstructed = revan.reconstruct(sim_path=sim, config_file=cfg)
    for identifier in ('selection-a', 'selection-b'):
        mimrec = Mimrec(working_space=SimulationWorkspace(root), executable=tool,
                        revan_analysis_id='reconstruction-a', analysis_id=identifier)
        selected = mimrec.extract_events(config_file=cfg)
        cfg_bytes = cfg.read_bytes()
        cfg.unlink()
        image = mimrec.image()
        spectrum = mimrec.spectrum(selected)
        cfg.write_bytes(cfg_bytes)
        assert read(selected)['upstream'][0]['execution_id'] == reconstructed.execution_id
        assert read(image)['upstream'][0]['execution_id'] == selected.execution_id
        assert read(spectrum)['upstream'][0]['execution_id'] == selected.execution_id
        assert image.output_dir == root/'mimrec'/identifier
    assert revan.reconstruct().output_dir == root/'revan/reconstruction-a'
    for nested in (root/'mimrec', root/'mimrec/selection-a', root/'mimrec/selection-a/spectrum'):
        with pytest.raises(ValueError, match='workspace root'):
            Mimrec(working_space=nested)
    with pytest.raises(ValueError, match='bound working_space'):
        mimrec.image(working_space=tmp_path/'different')
    with pytest.raises(ValueError, match='bound working_space'):
        revan.reconstruct(output_dir=tmp_path/'different')
    assert not (tmp_path/'different').exists()


def test_bound_workspace_external_tra_entry_and_conflicting_result(analysis, tmp_path):
    tra, cfg, tool = analysis
    root = tmp_path/'external-root'
    runner = Mimrec(working_space=root, executable=tool, analysis_id='external')
    selected = runner.extract_events(tra_path=tra, config_file=cfg)
    assert runner.image().record['upstream'][0]['execution_id'] == selected.execution_id
    elsewhere = Mimrec(executable=tool).extract_events(
        tra_path=tra, output_dir=tmp_path/'elsewhere', config_file=cfg)
    with pytest.raises(ValueError, match='bound working_space'):
        runner.image(elsewhere)
    with pytest.raises(ValueError, match='exactly one'):
        runner.image(root, tra_path=tra)
