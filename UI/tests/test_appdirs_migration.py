import importlib.util
from pathlib import Path


def _real_appdirs():
    """The real module (conftest stubs src.models.appdirs so other tests never touch real folders)."""
    path = Path(__file__).resolve().parents[1] / "src" / "models" / "appdirs.py"
    spec = importlib.util.spec_from_file_location("real_appdirs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_character_files_move_into_characters(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data = tmp_path / "DnDTools" / "data"
    data.mkdir(parents=True)
    for name in ("28201358.json", "worth_model.json", "market_model.json"):
        (data / name).write_text("{}")
    _real_appdirs().migrate_data_files()
    assert (data / "characters" / "28201358.json").exists()          # a character file (its id)
    assert (data / "worth_model.json").exists() and (data / "market_model.json").exists()
    assert not (data / "characters" / "worth_model.json").exists()    # models stay with the market data
