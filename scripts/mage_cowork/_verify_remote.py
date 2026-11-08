import sys
sys.path.insert(0, r'd:\models\models\agent\mage-vl-cowork')
import importlib.util
import os

model_dir = r'd:\models\models\agent\mage-vl-cowork'
ok = True
for fname in ['configuration_llava_onevision2.py', 'modeling_llava_onevision2.py']:
    fpath = os.path.join(model_dir, fname)
    if not os.path.exists(fpath):
        print(f'{fname}: MISSING')
        ok = False
        continue
    spec = importlib.util.spec_from_file_location(fname.replace('.py', ''), fpath)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        exports = [c for c in dir(mod) if not c.startswith('_')]
        print(f'{fname}: OK — exports: {exports[:6]}')
    except Exception as e:
        print(f'{fname}: FAILED — {type(e).__name__}: {e}')
        ok = False

# Also verify config.json looks parseable
try:
    import json
    with open(os.path.join(model_dir, 'config.json')) as f:
        cfg = json.load(f)
    print(f'config.json: OK — model_type={cfg.get("model_type")}, auto_map={cfg.get("auto_map")}')
except Exception as e:
    print(f'config.json: FAILED — {e}')
    ok = False

print(f'\nOverall: {"PASS" if ok else "FAIL"}')
