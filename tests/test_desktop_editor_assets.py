import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('desktop_build_payload', Path(__file__).parents[1] / 'desktop/build_payload.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_deep_route_packaging_refuses_relative_editor_assets(tmp_path):
    (tmp_path / 'index.html').write_text('<script type="module" src="./assets/editor.js"></script>', encoding='utf-8')
    with pytest.raises(ValueError, match='root asset URLs'):
        module.validate_editor_assets(tmp_path)


def test_editor_root_assets_must_exist_in_payload(tmp_path):
    (tmp_path / 'index.html').write_text('<script src="/assets/editor.js"></script><link rel="stylesheet" href="/assets/editor.css">', encoding='utf-8')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/editor.js').write_text('export {};', encoding='utf-8')
    with pytest.raises(FileNotFoundError):
        module.validate_editor_assets(tmp_path)
    (tmp_path / 'assets/editor.css').write_text('body{}', encoding='utf-8')
    module.validate_editor_assets(tmp_path)
