"""Revan adapter tests with real subprocesses and a stand-in native tool."""

import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

from megalibpy import Cosima, ExecutionError, MEGAlibRuntime, Revan, SimulationWorkspace


@pytest.fixture
def reconstruction(tmp_path, monkeypatch):
    user_home = tmp_path / "native-user-home"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    config_dir = tmp_path / "configuration files"
    config_dir.mkdir()
    config = config_dir / "reconstruction.cfg"
    config.write_text('''<RevanConfigurationFile>
<!-- preserve this scientific note -->
<UnknownFutureSetting><Value>keep me</Value></UnknownFutureSetting>
<BayesianComptonFile>response.dat</BayesianComptonFile>
<TestMode>success</TestMode>
</RevanConfigurationFile>''')
    (config_dir / "response.dat").write_text("response")
    geometry = tmp_path / "geometry.setup"
    geometry.write_text("# geometry")
    source = tmp_path / "input.sim.gz"
    source.write_bytes(b"native data is not inspected by wrapper")
    tool = tmp_path / "fake-revan"
    tool.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys, time, re
args = sys.argv[1:]
get = lambda flag: args[args.index(flag) + 1]
assert '-n' in args and '-a' in args
cfg = pathlib.Path(get('-c'))
content = cfg.read_bytes()
mode_match = re.search(rb'<TestMode>([^<>]*)</TestMode>', content)
mode = mode_match[1].decode() if mode_match else 'success'
home = pathlib.Path(os.environ['HOME'])
(home / '.revan.cfg').write_text('native saved settings')
print(json.dumps({'argv': args, 'cwd': str(pathlib.Path.cwd()),
                  'home': str(home), 'setup_home': os.environ.get('SETUP_HOME')}), flush=True)
if mode == 'exit': sys.exit(7)
if mode == 'sleep': time.sleep(20)
if mode != 'missing':
    pathlib.Path(get('-o')).write_bytes(b'native reconstructed events')
''')
    tool.chmod(0o755)
    return source, config, geometry, tool


def read(result):
    return result.record


def legacy_cosima(tmp_path, source, *, count=1):
    root = tmp_path / "old-cosima"
    (root / "products").mkdir(parents=True)
    (root / "logs").mkdir()
    outputs = []
    for i in range(count):
        product = root / "products" / f"events.id{i+1}.sim.gz"
        product.write_bytes(source.read_bytes())
        outputs.append(str(product.relative_to(root)))
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "tool": "cosima", "status": "succeeded",
        "outputs": {"sim": outputs}, "logs": {"stdout": "logs/stdout.log", "stderr": "logs/stderr.log"},
    }))
    return root


def test_explicit_configuration_and_home_isolation(reconstruction, tmp_path, monkeypatch):
    source, cfg, geometry, tool = reconstruction
    home = tmp_path / "parent-home"
    home.mkdir()
    sentinel = home / ".revan.cfg"
    sentinel.write_text("user settings")
    monkeypatch.setenv("HOME", str(home))
    original = cfg.read_bytes()
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
        sim_path=source, config_file=cfg, geometry=geometry, output_dir=tmp_path / "run",
        isolate_settings=True,
    )
    record = read(result)
    assert cfg.read_bytes() == original
    assert sentinel.read_text() == "user settings"
    assert os.environ["HOME"] == str(home)
    assert record["upstream"] == []
    assert record["configuration"]["original_sha256"]
    assert (result.output_dir / "inputs/executed.revan.cfg").read_bytes() == original
    executed = result.output_dir / "inputs/executed.revan.cfg"
    assert "preserve this scientific note" in executed.read_text()
    assert ET.parse(executed).findtext("UnknownFutureSetting/Value") == "keep me"
    command = record["command"]
    assert command[command.index("-c") + 1] == str(executed)
    assert command[command.index("-g") + 1] == str(geometry)
    assert command[command.index("-f") + 1] == str(source)
    assert command[command.index("-o") + 1] == str(result.outputs["tra"][0])
    assert record["cwd"] == str(cfg.parent)
    assert record["input_file"]["hash_policy"] == "size_and_mtime_only"
    assert "dependencies" not in record
    assert "dependency_capture" not in record
    assert (result.output_dir / read(result)["configuration"]["settings_home"] / ".revan.cfg").read_text() == "native saved settings"


def test_home_override_occurs_after_setup_without_rewriting_config(reconstruction, tmp_path, monkeypatch):
    source, cfg, geometry, tool = reconstruction
    home = tmp_path / "real home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cfg.write_text('<RevanConfigurationFile><AnyPath>~/calibration.dat</AnyPath></RevanConfigurationFile>')
    setup = tmp_path / "setup.sh"
    setup.write_text('export SETUP_HOME="$HOME"\n')
    result = Revan(MEGAlibRuntime.from_setup_script(setup, archive_inputs=True), executable=tool).reconstruct(
        sim_path=source, config_file=cfg, geometry=geometry, output_dir=tmp_path / "run", compressed=False, isolate_settings=True,
    )
    output = json.loads(result.stdout_path.read_text())
    assert output["setup_home"] == str(home)
    assert output["home"] == str(result.output_dir / read(result)["configuration"]["settings_home"])
    assert read(result)["runtime"]["executable"]["path"] == str(tool)
    assert ET.parse(result.output_dir / "inputs/executed.revan.cfg").findtext("AnyPath") == "~/calibration.dat"
    assert result.outputs["tra"][0].name == "events.tra"


def test_legacy_directory_read_only_with_explicit_new_destination(reconstruction, tmp_path):
    source, cfg, geometry, tool = reconstruction
    root = legacy_cosima(tmp_path, source)
    original = (root / "manifest.json").read_bytes()
    runner = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    with pytest.raises(ValueError, match="Legacy workspace is read-only"):
        runner.reconstruct(root, config_file=cfg)
    destination = tmp_path / "new-layout"
    a = runner.reconstruct(root, output_dir=destination, config_file=cfg, task="configuration-a")
    b = runner.reconstruct(root, output_dir=destination, config_file=cfg, task="configuration-b")
    assert (root / "manifest.json").read_bytes() == original
    assert not (root / "workspace.json").exists()
    assert a.output_dir == destination / "revan/attempt-001"
    assert b.output_dir == destination / "revan/attempt-002"
    assert read(a)["upstream"][0]["execution_id"] is None
    assert (a.output_dir / read(a)["upstream"][0]["manifest_snapshot"]).read_bytes() == original
    assert SimulationWorkspace(destination).select("revan", task="configuration-b").execution_id == b.execution_id
    with pytest.raises(ValueError, match="found 2"):
        SimulationWorkspace(destination).select("revan")


def test_multiple_files_need_explicit_selection_and_exact_lineage(reconstruction, tmp_path):
    source, cfg, geometry, tool = reconstruction
    root = legacy_cosima(tmp_path, source, count=2)
    result = SimulationWorkspace(root).select()
    with pytest.raises(ValueError, match="Select a file"):
        Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(result, config_file=cfg, geometry=geometry)
    selection = result.as_input("sim", paths=[result.outputs["sim"][1]])
    child = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(selection, output_dir=tmp_path/"new", config_file=cfg, geometry=geometry)
    record = read(child)
    assert record["upstream"][0]["paths"] == [str(result.outputs["sim"][1])]
    assert record["input_file"]["path"] == str(result.outputs["sim"][1])
    with pytest.raises(ValueError, match="subset"):
        Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
            result.as_input("sim", paths=[source]), config_file=cfg, geometry=geometry)


def test_external_evta_creates_experiment_and_retains_input(reconstruction, tmp_path):
    source, cfg, geometry, tool = reconstruction
    evta = source.with_name("external.evta")
    evta.write_bytes(source.read_bytes())
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(sim_path=evta, output_dir=tmp_path / "external-workspace",
                                              config_file=cfg, geometry=geometry)
    assert result.workspace_dir == tmp_path / "external-workspace"
    assert (result.workspace_dir / "manifest.json").is_file()
    assert read(result)["upstream"] == []
    assert evta.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("mode", ["empty-config", "missing-config", "exit", "missing", "sleep"])
def test_failures_keep_attempt_records(reconstruction, tmp_path, mode):
    source, cfg, geometry, tool = reconstruction
    if mode == "empty-config": cfg.write_bytes(b"")
    elif mode == "missing-config": cfg.unlink()
    else: cfg.write_text(f"<RevanConfigurationFile><TestMode>{mode}</TestMode></RevanConfigurationFile>")
    experiment = SimulationWorkspace(tmp_path / "experiment")
    with pytest.raises(ExecutionError) as error:
        Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(sim_path=source, config_file=cfg, geometry=geometry,
                                         output_dir=experiment.root, timeout=0.15 if mode == "sleep" else None)
    record = next(iter(json.loads(error.value.manifest_path.read_text())["executions"].values()))
    assert record["status"] == "failed"
    assert record["execution_id"]
    index = json.loads(experiment.index_path.read_text())
    assert next(iter(index["executions"].values()))["status"] == "failed"
    if mode == "exit": assert error.value.returncode == 7
    if mode == "missing": assert error.value.returncode == 0


def test_explicit_destination_new_workspace_and_directory_protection(reconstruction, tmp_path):
    source, cfg, geometry, tool = reconstruction
    root = legacy_cosima(tmp_path, source)
    experiment = SimulationWorkspace(tmp_path / "new-experiment")
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(root, output_dir=experiment.root, config_file=cfg, geometry=geometry)
    assert result.workspace_dir == experiment.root
    assert experiment.select().output_dir == root
    other = legacy_cosima(tmp_path / "other", source)
    with pytest.raises(ValueError, match="different Cosima"):
        Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(other, output_dir=experiment.root, config_file=cfg, geometry=geometry)
    with pytest.raises(ValueError, match="supported simulation workspace"):
        Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(sim_path=source, output_dir=result.output_dir, config_file=cfg, geometry=geometry)


def test_native_configuration_keywords_become_flags_without_changing_values(reconstruction, tmp_path):
    source, cfg, _, tool = reconstruction
    original = cfg.read_bytes()
    response = "$(MEGALIB)/missing response_file_v2.rsp"
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
        sim_path=source, config_file=cfg, output_dir=tmp_path / "run",
        TotalEnergy_Min=100, TotalEnergy_Max=1000,
        BayesianComptonFile=response, RejectAllBadEvents=True,
        Unknown_Native_Field="value_with_underscores=a=b", SearchMIPs=False,
    )
    actual = json.loads(result.stdout_path.read_text())["argv"]
    changes = [actual[i + 1] for i, flag in enumerate(actual) if flag == "-C"]
    assert changes == ["TotalEnergy.Min=100", "TotalEnergy.Max=1000",
                       f"BayesianComptonFile={response}", "RejectAllBadEvents=true",
                       "Unknown.Native.Field=value_with_underscores=a=b", "SearchMIPs=false"]
    assert "-g" not in actual
    assert cfg.read_bytes() == original
    assert (result.output_dir / "inputs/executed.revan.cfg").read_bytes() == original
    record = read(result)
    assert record["configuration_overrides"][2] == {"parameter": "BayesianComptonFile", "value": response}
    assert "dependencies" not in record


@pytest.mark.parametrize("geometry", [None, "$(MEGALIB)/not_local.geo.setup", "relative_model.geo.setup"])
def test_geometry_is_optional_and_forwarded_without_inspection(reconstruction, tmp_path, geometry):
    source, cfg, model, tool = reconstruction
    model.unlink()
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
        sim_path=source, config_file=cfg, geometry=geometry, output_dir=tmp_path / "run")
    actual = json.loads(result.stdout_path.read_text())["argv"]
    if geometry is None:
        assert "-g" not in actual
    else:
        assert actual[actual.index("-g") + 1] == geometry
    assert read(result)["geometry"] == geometry


def test_cosima_workspace_unique_origin_and_result_handoff(reconstruction, tmp_path):
    _, cfg, geometry, tool = reconstruction
    source = tmp_path / "example.source"
    source.write_text("Run Burst\nBurst.FileName old\nBurst.Time 1\n")
    cosima = tmp_path / "fake-cosima"
    cosima.write_text(f"#!{sys.executable}\n" + '''
from pathlib import Path
import sys
text = Path(sys.argv[-1]).read_text()
prefix = next(l.split()[1] for l in text.splitlines() if '.FileName ' in l)
Path(prefix + '.inc1.id1.sim.gz').write_bytes(b'simulation')
''')
    cosima.chmod(0o755)
    experiment = SimulationWorkspace(tmp_path / "experiment")
    result = Cosima(MEGAlibRuntime.direct(archive_inputs=True), executable=cosima).simulate(source, workspace=experiment, seed=1)
    assert result.workspace_dir == experiment.root
    assert result.output_dir == experiment.root / "cosima"
    with pytest.raises(ValueError, match="already contains"):
        Cosima(MEGAlibRuntime.direct(archive_inputs=True), executable=cosima).simulate(source, workspace=experiment, seed=1)
    tra = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(result, config_file=cfg, geometry=geometry)
    assert tra.workspace_dir == result.workspace_dir
    assert read(tra)["upstream"][0]["execution_id"] == result.execution_id
    assert experiment.select().execution_id == result.execution_id
    assert len(json.loads(experiment.index_path.read_text())["executions"]) == 2
    selected = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
        result.as_input("sim", paths=result.outputs["sim"]),
        config_file=cfg, geometry=geometry, task="selected-input")
    assert selected.workspace_dir == experiment.root
    assert selected.output_dir == experiment.root / "revan/attempt-002"


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
def test_native_legacy_names_and_literal_values_preserved(reconstruction, tmp_path, eol):
    source, cfg, geometry, tool = reconstruction
    content = eol.join([
        b'<?xml version="1.0"?>',
        b'<!-- preserve <FakeRoot> and raw A&B -->',
        b'<RevanConfigurationFile>',
        b'  <SpectrumBefore)>true</SpectrumBefore)>',
        b'  <UnknownSetting>raw A&B and literal &amp;</UnknownSetting>',
        b'  <EmptyValue />',
        b'</RevanConfigurationFile>', b'',
    ])
    cfg.write_bytes(content)
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
        sim_path=source, config_file=cfg, geometry=geometry, output_dir=tmp_path / "run")
    assert (result.output_dir / "inputs/executed.revan.cfg").read_bytes() == content
    assert (result.output_dir / "inputs/executed.revan.cfg").read_bytes() == content
    record = read(result)["configuration"]
    assert record["original_sha256"] == record["executed_sha256"]
    assert record["format"] == "native_passthrough"


def test_native_home_paths_remain_literal_and_are_not_discovered(reconstruction, tmp_path, monkeypatch):
    source, cfg, geometry, tool = reconstruction
    home = tmp_path / "home&literal"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / "response&data.rsp").write_text("response")
    content = (b'<RevanConfigurationFile>\r\n'
               b'<!-- <BayesianComptonFile>~/ignored.rsp</BayesianComptonFile> -->\r\n'
               b'<SpectrumBefore)>true</SpectrumBefore)>\r\n'
               b'<BayesianComptonFile> <!-- keep --> ~/response&data.rsp </BayesianComptonFile>\r\n'
               b'<UnknownSetting>literal &amp;</UnknownSetting>\r\n'
               b'</RevanConfigurationFile>\r\n')
    cfg.write_bytes(content)
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
        sim_path=source, config_file=cfg, geometry=geometry, output_dir=tmp_path / "run")
    executed = (result.output_dir / "inputs/executed.revan.cfg").read_bytes()
    assert executed == content
    assert b'~/ignored.rsp' in executed
    record = read(result)
    assert "dependencies" not in record


def test_configuration_syntax_delegated_to_native(reconstruction, tmp_path):
    source, cfg, geometry, tool = reconstruction
    content = b"native configuration payload is opaque to Python"
    cfg.write_bytes(content)
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
        sim_path=source, config_file=cfg, geometry=geometry, output_dir=tmp_path / "run")
    assert (result.output_dir / "inputs/executed.revan.cfg").read_bytes() == content
    # The stand-in accepts the payload; this is not a claim that Revan accepts it.
    assert read(result)["configuration"]["format"] == "native_passthrough"


def test_isolation_can_be_disabled_without_modifying_config(reconstruction, tmp_path, monkeypatch):
    source, cfg, geometry, tool = reconstruction
    home = tmp_path / "original-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    original = cfg.read_bytes()
    result = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(
        sim_path=source, config_file=cfg, geometry=geometry, output_dir=tmp_path / "run",
        isolate_settings=False)
    assert cfg.read_bytes() == original
    assert json.loads(result.stdout_path.read_text())["home"] == str(home)
    assert (home / ".revan.cfg").read_text() == "native saved settings"
    assert read(result)["tool_environment"] == {}
    assert read(result)["configuration"]["settings_home"] is None


@pytest.mark.parametrize("arguments", [{}, {"working_space": "existing", "sim_path": "events.sim"},
                                      {"sim_path": "events.sim"}])
def test_entry_points_are_explicit_and_exclusive(reconstruction, tmp_path, arguments):
    _, cfg, _, tool = reconstruction
    with pytest.raises(ValueError):
        Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool).reconstruct(config_file=cfg, **arguments)
    assert not (tmp_path / "events-workspace").exists()


def test_external_sim_root_can_be_reopened_and_keeps_origin(reconstruction, tmp_path):
    source, cfg, _, tool = reconstruction
    original = source.read_bytes()
    runner = Revan(MEGAlibRuntime.direct(archive_inputs=True), executable=tool)
    root = tmp_path / "received-grb"
    first = runner.reconstruct(sim_path=source, output_dir=root, config_file=cfg, task="baseline")
    assert first.workspace_dir == root
    assert first.output_dir == root / "revan/attempt-001"
    index = json.loads((root / "manifest.json").read_text())
    assert index["kind"] == "simulation_workspace"
    assert index["origin"] == {"kind": "external_sim", "path": str(source)}
    assert all(r["tool"] != "cosima" for r in index["executions"].values())
    assert read(first)["upstream"] == []
    second = runner.reconstruct(working_space=root, config_file=cfg, task="alternate", TotalEnergy_Min=100)
    assert second.output_dir == root / "revan/attempt-002"
    assert read(second)["input_file"]["path"] == str(source)
    assert source.read_bytes() == original
    assert SimulationWorkspace(root).select("revan", task="baseline").execution_id == first.execution_id
    other = tmp_path / "other.sim"
    other.write_bytes(b"another simulation")
    with pytest.raises(ValueError, match="different external"):
        runner.reconstruct(sim_path=other, output_dir=root, config_file=cfg)
    with pytest.raises(ValueError, match="sim_path"):
        runner.reconstruct(working_space=source, config_file=cfg)
    with pytest.raises(ValueError, match="origin"):
        SimulationWorkspace(root).execute("cosima", "simulation", lambda p: None)


def test_revan_analysis_binding_branching_defaults_and_non_overwrite(reconstruction, tmp_path):
    source, cfg, geometry, tool = reconstruction
    root = tmp_path/'experiment'
    runner = Revan(executable=tool, analysis_id='baseline')
    assert not root.exists()
    first = runner.reconstruct(sim_path=source, output_dir=root, config_file=cfg, geometry=geometry)
    original = first.outputs['tra'][0].read_bytes()
    cfg.unlink()
    second = runner.reconstruct(working_space=root)
    assert first.output_dir == second.output_dir == root/'revan/baseline'
    assert first.outputs['tra'][0].name == 'events.tra.gz'
    assert second.outputs['tra'][0].name == 'events-002.tra.gz'
    assert first.outputs['tra'][0].read_bytes() == original
    assert read(second)['configuration']['executed_sha256'] == read(first)['configuration']['executed_sha256']
    assert read(second)['geometry'] == str(geometry)
    assert read(second)['analysis_id'] == 'baseline'
    with pytest.raises(ValueError, match='found 2'):
        SimulationWorkspace(root).select('revan', analysis_id='baseline')
    cfg_b = tmp_path/'b.cfg'
    cfg_b.write_bytes(b'native alternative configuration')
    alternative = Revan(executable=tool, analysis_id='alternative').reconstruct(
        working_space=root, config_file=cfg_b)
    assert alternative.output_dir == root/'revan/alternative'
    assert SimulationWorkspace(root).select('revan', analysis_id='alternative').execution_id == alternative.execution_id
    assert len(json.loads((root/'manifest.json').read_text())['groups']) == 2
    automatic = Revan(executable=tool).reconstruct(working_space=root, config_file=cfg_b)
    assert automatic.output_dir.name == 'attempt-001'


def test_revan_analysis_change_warns_and_different_input_is_rejected(reconstruction, tmp_path):
    source, cfg, _, tool = reconstruction
    root = tmp_path/'experiment'
    runner = Revan(executable=tool, analysis_id='baseline')
    first = runner.reconstruct(sim_path=source, output_dir=root, config_file=cfg)
    with pytest.warns(UserWarning, match='settings differ'):
        changed = runner.reconstruct(working_space=root, TotalEnergy_Min=100)
    assert read(changed)['configuration_overrides'] == [{'parameter':'TotalEnergy.Min','value':'100'}]
    again = runner.reconstruct(working_space=root)
    assert read(again)['configuration_overrides'] == []
    assert read(first)['configuration_overrides'] == []
    other = tmp_path/'other.sim'
    other.write_bytes(b'other input')
    with pytest.raises(ValueError, match='different sim/evta'):
        runner.reconstruct(sim_path=other, output_dir=root, config_file=cfg)


@pytest.mark.parametrize('identifier', ['', '../escape', 'a/b', 'space name', 2])
def test_invalid_revan_analysis_id_is_rejected(identifier):
    with pytest.raises(ValueError, match='analysis_id'):
        Revan(analysis_id=identifier)


def test_constructor_configuration_freezes_bytes_and_baseline_not_first_execution(reconstruction, tmp_path):
    source, config, geometry, tool = reconstruction
    root = tmp_path / 'bound-experiment'
    original = config.read_bytes()
    value = [1, 2]
    runner = Revan(working_space=root, analysis_id='a', config_file=config,
                   geometry=geometry, Native_Vector=value, executable=tool)
    assert not root.exists()
    value.append(3)
    config.unlink()
    first = runner.reconstruct(sim_path=source, TotalEnergy_Min=100)
    baseline = [{'parameter': 'Native.Vector', 'value': '[1, 2]'}]
    assert first.record['analysis_baseline_overrides'] == baseline
    assert first.record['execution_overrides'] == [{'parameter': 'TotalEnergy.Min', 'value': '100'}]
    assert first.record['configuration_overrides'] == baseline + first.record['execution_overrides']
    assert first.record['configuration']['content'] == original.decode()
    reopened = Revan(working_space=root, analysis_id='a', executable=tool)
    second = reopened.reconstruct()
    assert second.record['configuration_overrides'] == baseline
    assert second.record['execution_overrides'] == []
    assert second.record['geometry'] == str(geometry)
    assert first.outputs['tra'][0] != second.outputs['tra'][0]
    assert first.outputs['tra'][0].exists()


def test_constructor_configuration_requires_identity_and_rejects_changed_baselines(reconstruction, tmp_path):
    source, config, geometry, tool = reconstruction
    root = tmp_path / 'bound-experiment'
    with pytest.raises(ValueError, match='working_space and analysis_id'):
        Revan(config_file=config)
    runner = Revan(working_space=root, analysis_id='a', config_file=config,
                   geometry=geometry, executable=tool, Native_Setting=True)
    result = runner.reconstruct(sim_path=source)
    for kwargs in ({'geometry': 'different'}, {'Native_Setting': False}):
        with pytest.raises(ValueError, match='new analysis_id'):
            Revan(working_space=root, analysis_id='a', executable=tool, **kwargs)
    changed = config.with_name('changed.cfg')
    changed.write_bytes(b'opaque changed cfg')
    for kwargs in ({'config_file': changed}, {'geometry': 'different'}):
        with pytest.raises(ValueError, match='new analysis_id'):
            runner.reconstruct(**kwargs)
    fork = Revan(working_space=root, analysis_id='b', config_file=changed, executable=tool)
    assert fork.reconstruct().record['data_group'] != result.record['data_group']
    assert len(SimulationWorkspace(root)._read()["executions"]) == 2


def test_bound_revan_rejects_identifier_mutation_and_changed_input(reconstruction, tmp_path):
    source, config, _, tool = reconstruction
    root = tmp_path / 'bound-experiment'
    runner = Revan(working_space=root, analysis_id='a', config_file=config, executable=tool)
    runner.reconstruct(sim_path=source)
    other = source.with_name('other.sim'); other.write_bytes(b'other')
    with pytest.raises(ValueError, match='different sim/evta input'):
        runner.reconstruct(sim_path=other)
    runner.analysis_id = 'b'
    with pytest.raises(ValueError, match='Construct a new Revan'):
        runner.reconstruct()


def test_legacy_calls_cannot_bypass_bound_revan_and_can_adopt_matching_defaults(reconstruction, tmp_path):
    source, config, geometry, tool = reconstruction
    root = tmp_path / 'bound-experiment'
    legacy = Revan(analysis_id='a', executable=tool)
    legacy.reconstruct(sim_path=source, output_dir=root, config_file=config, geometry=geometry)
    bound = Revan(working_space=root, analysis_id='a', config_file=config, geometry=geometry, executable=tool)
    bound.reconstruct()
    changed = config.with_name('changed.cfg'); changed.write_bytes(b'different')
    with pytest.raises(ValueError, match='new analysis_id'):
        legacy.reconstruct(working_space=root, config_file=changed)
    temporary = legacy.reconstruct(working_space=root, Native_Setting=3)
    assert temporary.record['execution_overrides'] == [{'parameter': 'Native.Setting', 'value': '3'}]
    assert bound.reconstruct().record['configuration_overrides'] == []


def test_failed_first_bound_execution_keeps_opaque_baseline(reconstruction, tmp_path):
    source, config, _, tool = reconstruction
    config.write_bytes(b'\xff\x00 opaque native config <TestMode>exit</TestMode>')
    root = tmp_path / 'failed-experiment'
    runner = Revan(working_space=root, analysis_id='a', config_file=config, executable=tool)
    with pytest.raises(ExecutionError):
        runner.reconstruct(sim_path=source, Temporary_Setting=True)
    config.unlink()
    reopened = Revan(working_space=root, analysis_id='a', executable=tool)
    assert reopened._configuration.content == b'\xff\x00 opaque native config <TestMode>exit</TestMode>'
    assert reopened._configuration.overrides == {}
    assert SimulationWorkspace(root)._read()['groups']['revan/a']['definition']['overrides'] == []


def test_deleted_failed_analysis_accepts_corrected_baseline_and_keeps_history(reconstruction,tmp_path):
    import shutil
    source,config,geometry,tool=reconstruction
    root=tmp_path/'experiment'
    config.write_bytes(b'<TestMode>exit</TestMode>')
    failed_runner=Revan(working_space=root,analysis_id='same',config_file=config,
                        geometry='wrong-geometry',executable=tool,Old_Setting=True)
    with pytest.raises(ExecutionError) as failure:
        failed_runner.reconstruct(sim_path=source)
    old_id=failure.value.execution_id
    old=SimulationWorkspace(root)._read()['executions'][old_id]
    # Existing folders still protect their definition, even after a failure.
    config.write_bytes(b'corrected opaque native config')
    with pytest.raises(ValueError,match='new analysis_id'):
        Revan(working_space=root,analysis_id='same',config_file=config,geometry=geometry,executable=tool)
    shutil.rmtree(root/'revan/same')
    before=(root/'manifest.json').read_bytes()
    corrected=Revan(working_space=root,analysis_id='same',config_file=config,
                    geometry=geometry,executable=tool)
    assert (root/'manifest.json').read_bytes()==before
    assert not (root/'revan/same').exists()
    result=corrected.reconstruct()
    data=SimulationWorkspace(root)._read()
    assert data['executions'][old_id]==old
    assert result.execution_id!=old_id
    assert result.record['number']==2
    assert result.record['geometry']==str(geometry)
    assert result.record['configuration_overrides']==[]
    assert data['groups']['revan/same']['defaults']['geometry']==str(geometry)
    assert data['groups']['revan/same']['recovery_history'][0]['previous_execution_ids']==[old_id]
    reopened=Revan(working_space=root,analysis_id='same',executable=tool)
    assert reopened.reconstruct().record['geometry']==str(geometry)


def test_deleted_successful_analysis_still_protects_settings_but_can_rerun(reconstruction,tmp_path):
    import shutil
    source,config,geometry,tool=reconstruction
    root=tmp_path/'experiment'
    original=Revan(working_space=root,analysis_id='same',config_file=config,geometry=geometry,executable=tool)
    first=original.reconstruct(sim_path=source)
    shutil.rmtree(root/'revan/same')
    with pytest.raises(ValueError,match='new analysis_id'):
        Revan(working_space=root,analysis_id='same',geometry='changed',executable=tool)
    result=Revan(working_space=root,analysis_id='same',executable=tool).reconstruct()
    assert result.execution_id!=first.execution_id
    assert result.record['number']==2
    assert 'recovery_history' not in SimulationWorkspace(root)._read()['groups']['revan/same']


def test_deleted_failed_group_recovery_is_rechecked_before_execution(reconstruction,tmp_path):
    import shutil
    source,config,_,tool=reconstruction
    root=tmp_path/'experiment'
    config.write_bytes(b'<TestMode>exit</TestMode>')
    runner=Revan(working_space=root,analysis_id='same',config_file=config,executable=tool)
    with pytest.raises(ExecutionError):runner.reconstruct(sim_path=source)
    shutil.rmtree(root/'revan/same')
    corrected=Revan(working_space=root,analysis_id='same',config_file=config,geometry='corrected',executable=tool)
    # Another actor recreating the directory cancels the implicit reset.
    (root/'revan/same').mkdir(parents=True)
    with pytest.raises(ValueError,match='new analysis_id'):
        corrected.reconstruct()


def test_deleted_preparation_failure_keeps_baseline_in_recovery_history(reconstruction,tmp_path,monkeypatch):
    import importlib
    import shutil
    module=importlib.import_module('megalibpy.revan.runner')
    source,config,_,tool=reconstruction
    root=tmp_path/'experiment'
    runner=Revan(working_space=root,analysis_id='same',config_file=config,executable=tool)
    original=module._prepare
    def broken_prepare(*args,**kwargs):
        raise RuntimeError('preparation failed before an execution plan existed')
    monkeypatch.setattr(module,'_prepare',broken_prepare)
    with pytest.raises(ExecutionError) as failure:runner.reconstruct(sim_path=source)
    data=SimulationWorkspace(root)._read()
    definition=data['groups']['revan/same']['definition']
    assert 'configuration' not in data['executions'][failure.value.execution_id]
    shutil.rmtree(root/'revan/same')
    config.write_bytes(b'corrected baseline')
    monkeypatch.setattr(module,'_prepare',original)
    result=Revan(working_space=root,analysis_id='same',config_file=config,executable=tool).reconstruct()
    history=SimulationWorkspace(root)._read()['groups']['revan/same']['recovery_history']
    assert history[0]['previous_definition']==definition
    assert history[0]['previous_execution_ids']==[failure.value.execution_id]
    assert result.record['status']=='succeeded'
