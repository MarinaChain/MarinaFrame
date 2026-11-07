"""Synthetic guard mutations. Run from the repo; no worker source is changed.

An allowed socket can be created under Seatbelt: bind/connect is the denied
operation. Isolated Python avoids mistaking import-path denial for that guard.
"""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import types


def main():
    root = Path(__file__).resolve().parents[1]
    source_path = root/'src/vessel_reconstruction/ship_cad.py'
    source = source_path.read_text()
    mutations = [
        ('unknown_fields', 'if not isinstance(value, dict) or set(value) != set(expected):', 'if False:', 'code'),
        ('literal_dimension', 'if not _id(reference):', 'if False:', 'literal'),
        ('missing_measurement', 'if not _measurement_ok(record, kind):', 'if False:', 'missing'),
        ('wrong_view', 'if expected_view is not None and record[\'view\'] != expected_view:', 'if False:', 'view'),
    ]
    results = []
    for name, old, new, case in mutations:
        assert source.count(old) == 1, name
        module = types.ModuleType('vessel_reconstruction.ship_cad_mutant')
        exec(compile(source.replace(old,new), str(source_path), 'exec'), module.__dict__)
        program = {'schema':'ship-cad/v1','components':[{'id':'house','op':'deckhouse',
                   'source':{'view':'plan','region':'house','method':'closed_outline'},
                   'args':{'outline':'outline','height':'height'}}]}
        caught = False
        if case == 'code':
            program['components'][0]['code'] = 'import os'
        elif case == 'literal':
            program['components'][0]['args']['height'] = 2.5
        if case in ('code','literal'):
            try:
                module.validate_program(program)
            except ValueError:
                pass
            else:
                caught = True  # The required rejection assertion would fail.
        elif case == 'view':
            program['components'][0]['source']['view'] = 'profile'
            measurements = {'outline':{'status':'measured','kind':'outline','value':[[0,0],[1,0],[0,1]],
                'view':'profile','region':'house','method':'closed_outline','source_sha256':'a'*64,'entity_ids':['a']},
                'height':{'status':'measured','kind':'interval','value':[0,1],
                'view':'profile','region':'height','method':'parallel_lines','source_sha256':'b'*64,'entity_ids':['b']}}
            caught = module.resolve_program(program,measurements)[0]['geometry'] is not None
        else:
            try:
                result = module.resolve_program(program,{})
                caught = result[0]['geometry'] is not None
            except KeyError:
                caught = True  # The graceful draft-guess assertion would fail.
        results.append({'mutation':name,'caught':caught})
    if sys.platform == 'darwin':
        from vessel_reconstruction.ship_cad_worker import sandbox_profile, runtime_paths
        with tempfile.TemporaryDirectory(prefix='ship-cad-mutations-') as scratch:
            directory = Path(scratch)
            secret = directory/'secret.txt'
            secret.write_text('synthetic sentinel')
            task = directory/'task'
            task.mkdir()
            profile = sandbox_profile(task,runtime_paths())
            for name, addition, command in [
                ('network','(allow network*)','import socket; socket.socket().bind(("127.0.0.1",0))'),
                ('external_file',f'(allow file-read* (literal {json.dumps(str(secret.resolve()))}))',
                 f'import pathlib; pathlib.Path({str(secret.resolve())!r}).read_text()'),
            ]:
                path = task/f'{name}.sb'
                path.write_text(profile+addition)
                result = subprocess.run(['/usr/bin/sandbox-exec','-f',str(path),sys.executable,'-I','-c',command],
                                        capture_output=True,text=True)
                results.append({'mutation':name,'caught':result.returncode == 0,
                                'mutant_returncode':result.returncode})
    else:
        results.append({'mutation':'OS sandbox guards','caught':False,'reason':'macOS required'})
    print(json.dumps(results,indent=2))
    return 0 if all(result['caught'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
