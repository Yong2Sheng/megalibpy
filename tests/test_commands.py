"""Unmanaged command execution uses the shared runtime without workspace state."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from megalibpy import MEGAlibRuntime, run_command


@pytest.fixture
def native_tool(tmp_path):
    directory=tmp_path/'native tools';directory.mkdir()
    executable=directory/'mimrec'
    executable.write_text(f'#!{sys.executable}\n'+'''
import json,os,pathlib,sys,time
args=sys.argv[1:]
if 'sleep' in args:time.sleep(30)
print(json.dumps({'args':args,'cwd':str(pathlib.Path.cwd()),
 'child':os.environ.get('MEGALIBPY_COMMAND_CHILD'),
 'pythonpath':os.environ.get('PYTHONPATH')}),flush=True)
sys.stderr.buffer.write(b'native stderr \\xff\\n')
sys.exit(7 if 'fail' in args else 0)
''')
    executable.chmod(0o755)
    setup=tmp_path/'setup native.sh'
    setup.write_text('export PATH='+shlex.quote(str(directory))+':"$PATH"\n'
                     'export MEGALIBPY_COMMAND_CHILD=initialized\n')
    return executable,setup


@pytest.mark.parametrize('mode',['direct','direct-relative','setup'])
def test_command_runtime_preserves_argv_and_parent_without_workspace(native_tool,tmp_path,monkeypatch,mode):
    executable,setup=native_tool
    monkeypatch.setenv('PYTHONPATH','parent-only-value')
    monkeypatch.delenv('MEGALIBPY_COMMAND_CHILD',raising=False)
    child_cwd=tmp_path/'output dir';child_cwd.mkdir()
    runtime=(MEGAlibRuntime.from_setup_script(setup) if mode=='setup' else MEGAlibRuntime.direct())
    executable_arg='mimrec' if mode=='setup' else executable
    if mode=='direct-relative':executable_arg=Path('..')/'native tools'/'mimrec'
    before_env=dict(os.environ);before_cwd=Path.cwd()
    arguments=[executable_arg,'-C','Literal.Value=$(touch should-not-exist); a=b',Path('an input.tra')]
    result=run_command(arguments,runtime=runtime,cwd=child_cwd,capture_output=True)
    out=json.loads(result.stdout)
    assert out['args']==['-C','Literal.Value=$(touch should-not-exist); a=b','an input.tra']
    assert out['cwd']==str(child_cwd)
    assert out['child']==('initialized' if mode=='setup' else None)
    assert out['pythonpath']==(None if mode=='setup' else 'parent-only-value')
    assert result.args==[str(a) for a in arguments]
    assert result.returncode==0 and '\ufffd' in result.stderr
    assert dict(os.environ)==before_env and Path.cwd()==before_cwd
    assert list(child_cwd.iterdir())==[]


def test_command_default_inherits_streams_and_nonzero_status_is_explicit(native_tool,capfd):
    executable,_=native_tool
    result=run_command([executable])
    assert result.stdout is None and result.stderr is None
    streams=capfd.readouterr();assert 'native stderr' in streams.err
    assert json.loads(streams.out)['args']==[]
    result=run_command([executable,'fail'],capture_output=True,check=False)
    assert result.returncode==7
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_command([executable,'fail'],capture_output=True)
    assert failure.value.cmd==[str(executable),'fail']
    assert json.loads(failure.value.stdout)['args']==['fail']


def test_setup_failure_timeout_and_helpers_are_cleaned(native_tool,tmp_path,monkeypatch):
    _,setup=native_tool
    locations=[]
    original=MEGAlibRuntime.launch
    def record_launch(self,command,record,**kwargs):
        locations.append(record.parent)
        return original(self,command,record,**kwargs)
    monkeypatch.setattr(MEGAlibRuntime,'launch',record_launch)
    runtime=MEGAlibRuntime.from_setup_script(setup)
    run_command(['mimrec'],runtime=runtime,capture_output=True)
    with pytest.raises(subprocess.TimeoutExpired) as failure:
        run_command(['mimrec','sleep'],runtime=runtime,timeout=0.2,capture_output=True)
    assert failure.value.cmd==['mimrec','sleep']
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_command(['not-an-installed-megalib-tool'],runtime=runtime,capture_output=True)
    assert failure.value.returncode==127
    broken=tmp_path/'broken setup.sh';broken.write_text('return 9\n')
    with pytest.raises(subprocess.CalledProcessError) as failure:
        run_command(['mimrec'],runtime=MEGAlibRuntime.from_setup_script(broken),capture_output=True)
    assert failure.value.returncode==9
    assert all(not p.exists() for p in locations)


@pytest.mark.parametrize('command,error',[("mimrec -x",TypeError),([],ValueError),([''],ValueError),(['mimrec',1],TypeError)])
def test_command_rejects_shell_strings_and_invalid_argv(command,error):
    with pytest.raises(error):run_command(command)
