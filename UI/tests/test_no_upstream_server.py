"""The app sends nothing to the original author's server and downloads nothing from it: assets are
local copies and updates come from our own releases."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ("rrmtools", "Beelzebub2/DnDTools")
SHIPPED = [
    ROOT / "UI" / "app.py", ROOT / "UI" / "main.py", ROOT / "UI" / "update.py",
    *(ROOT / "UI" / "src").rglob("*.py"), *(ROOT / "UI" / "utils").rglob("*.py"),
    *(ROOT / "UI" / "static" / "js").rglob("*.js"), *(ROOT / "UI" / "templates").rglob("*.html"),
    *(ROOT / ".github" / "workflows").glob("*.yml"), *(ROOT / "scripts").glob("*.py"),
    ROOT / "UI" / "assets" / ".asset_manifest.json",
]


def test_nothing_talks_to_the_original_authors_server():
    offenders = sorted(
        f"{path.relative_to(ROOT)}: {needle}"
        for path in SHIPPED if path.is_file()
        for needle in UPSTREAM if needle in path.read_text(encoding="utf-8", errors="ignore")
    )
    assert offenders == []
