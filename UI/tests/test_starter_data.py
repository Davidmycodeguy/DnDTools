from src.models.starter_data import STARTER_FILES, install_starter_data


def _bundle(tmp_path, names=STARTER_FILES):
    bundle = tmp_path / "starter_data"
    bundle.mkdir()
    for name in names:
        (bundle / name).write_text(f"shipped {name}")
    return bundle


def test_a_new_install_gets_the_shipped_market_data_and_models(tmp_path):
    bundle, data = _bundle(tmp_path), tmp_path / "data"
    copied = install_starter_data(bundle, data)
    assert sorted(copied) == sorted(STARTER_FILES)
    assert all((data / name).read_text() == f"shipped {name}" for name in STARTER_FILES)


def test_the_users_own_data_is_never_overwritten(tmp_path):
    bundle, data = _bundle(tmp_path), tmp_path / "data"
    data.mkdir()
    (data / "market_history.sqlite").write_text("my crawls")
    copied = install_starter_data(bundle, data)
    assert "market_history.sqlite" not in copied
    assert (data / "market_history.sqlite").read_text() == "my crawls"


def test_no_bundle_means_nothing_to_do(tmp_path):
    assert install_starter_data(tmp_path / "missing", tmp_path / "data") == []
