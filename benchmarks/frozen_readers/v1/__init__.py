"""Load the byte-identical v1 sources with their original imports bound locally."""
import builtins
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def _load(name, dependencies):
    module_name = f'{__name__}.{name}'
    path = Path(__file__).with_name(f'{name}.py')
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    original_import = builtins.__import__

    def frozen_import(import_name, globals=None, locals=None, fromlist=(), level=0):
        if import_name == 'vessel_reconstruction' and fromlist == ('body_plan_crossings',):
            return SimpleNamespace(body_plan_crossings=dependencies['body_plan_crossings'])
        if import_name == 'vessel_reconstruction.body_plan_reader':
            return dependencies['body_plan_reader']
        return original_import(import_name, globals, locals, fromlist, level)

    module.__dict__['__builtins__'] = dict(vars(builtins), __import__=frozen_import)
    sys.modules[module_name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


body_plan_crossings = _load('body_plan_crossings', {})
body_plan_reader = _load('body_plan_reader', {'body_plan_crossings': body_plan_crossings})
body_plan_identity = _load('body_plan_identity', {'body_plan_reader': body_plan_reader})
