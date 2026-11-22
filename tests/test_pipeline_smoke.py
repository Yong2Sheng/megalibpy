"""Exercise the delivered full-chain smoke CLI through real child processes."""

import json
from pathlib import Path
import subprocess
import sys


def test_delivered_full_chain_smoke(tmp_path):
    source = tmp_path/'burst.source'
    source.write_text('Run Burst\nBurst.FileName original\nBurst.Time 1\n')
    config = tmp_path/'native.cfg'
    config.write_bytes(b'opaque native config with non-XML fields')
    tools = tmp_path/'tools'
    tools.mkdir()
    program = f'#!{sys.executable}\n'+'''
from pathlib import Path
import sys
args = sys.argv[1:]
if Path(sys.argv[0]).name == 'cosima':
    text = Path(args[-1]).read_text()
    prefix = next(l.split()[1] for l in text.splitlines() if '.FileName ' in l)
    Path(prefix+'.inc1.id1.sim.gz').write_bytes(b'sim')
else:
    Path(args[args.index('-o')+1]).write_bytes(b'native output')
'''
    for name in ('cosima','revan','mimrec'):
        path = tools/name
        path.write_text(program)
        path.chmod(0o755)
    setup = tmp_path/'setup.sh'
    setup.write_text(f'export PATH="{tools}:$PATH"\n')
    root = tmp_path/'experiment'
    command = [sys.executable, str(Path('examples/end_to_end_smoke.py').resolve()),
               '--workspace',str(root),'--source',str(source),'--revan-config',str(config),
               '--mimrec-config',str(config),'--geometry','literal.geo.setup','--setup-script',str(setup)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    record = json.loads((root/'manifest.json').read_text())
    records = list(record['executions'].values())
    assert [r['operation'] for r in records] == ['cosima','revan','extract_events','spectrum','image']
    assert all(r['status'] == 'succeeded' for r in records)
    assert {p.name for p in root.iterdir()} == {'manifest.json','cosima','revan','mimrec'}
    assert list(root.rglob('manifest.json')) == [root/'manifest.json']
    assert not (root/'cosima/attempt-001').exists()
    assert all(r['analysis_id'] == 'baseline' for r in records[1:])
    assert records[1]['data_group'] == 'revan/baseline'
    assert records[3]['data_group'] == records[4]['data_group'] == records[2]['data_group']
    assert records[3]['upstream'][0]['execution_id'] == records[2]['execution_id']
    assert records[4]['upstream'][0]['execution_id'] == records[2]['execution_id']
    assert all('manifest_snapshot' not in u for r in records for u in r['upstream'])
    assert (root/'mimrec/baseline/spectrum/spectrum.root').is_file()
    assert (root/'mimrec/baseline/image-selected/image.root').is_file()
    assert records[2]['configuration']['content'] == config.read_text()
    assert all(r['configuration']['content'] == config.read_text() for r in records[2:])
    assert not list(root.rglob('*.cfg'))
    assert not list(root.rglob('*.sh'))
    assert not list(root.rglob('*.txt'))
    assert all(r['logs']['stdout'] is None and r['logs']['stderr'] is None for r in records)
    repeated = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert repeated.returncode != 0
    assert 'fresh path' in repeated.stderr
    assert json.loads((root/'manifest.json').read_text()) == record
