"""Who this app is and where it lives. Every link, update check and release URL derives from these,
so renaming the product or moving the repository is a change here only. Standard library only: the
standalone updater (update.spec) imports this without Flask."""

NAME = "DnDTools"
GITHUB_REPO = "Davidmycodeguy/DnDTools"

REPO_URL = f"https://github.com/{GITHUB_REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_RELEASE_URL = f"{RELEASES_URL}/latest"
UPDATE_MANIFEST_URL = f"{LATEST_RELEASE_URL}/download/update-manifest.json"
ISSUES_URL = f"{REPO_URL}/issues"
DOCS_URL = f"{REPO_URL}/tree/main/docs"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
LATEST_RELEASE_API = f"{RELEASES_API}/latest"


def for_pages():
    """What templates and page scripts need (window.PRODUCT)."""
    return {"name": NAME, "repoUrl": REPO_URL, "releasesUrl": LATEST_RELEASE_URL, "issuesUrl": ISSUES_URL,
            "docsUrl": DOCS_URL}
