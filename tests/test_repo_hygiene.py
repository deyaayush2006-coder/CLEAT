"""Repository hygiene checks.

These protect the hackathon rules (open-source licence, no committed secrets) and the
Streamlit-only frontend decision. Never weaken or delete them.
"""

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "venv", ".git"}
FORBIDDEN_REQUIREMENTS = ("react", "shadcn", "gsap", "framer", "tailwind", "three")
HTML_ALLOWED_FILES = {Path("cleat/ui/theme.py"), Path("cleat/ui/components.py")}
UNSAFE_HTML = re.compile(r"unsafe_allow_html\s*=\s*True")
NOVELTY_EFFECTS = re.compile(r"\bst\.(balloons|snow)\(")
SECRET_PATTERNS = {
    # Bounded to one line and a realistic length so empty .env.example entries never match.
    "PayPal client secret": re.compile(r"PAYPAL_CLIENT_SECRET[ \t]*=[ \t]*['\"]?[A-Za-z0-9_\-]{20,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "PayPal access token": re.compile(r"A21AA[0-9A-Za-z_\-]{20,}"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def _walk_files() -> list[Path]:
    """Return every file under the repo root, skipping virtualenvs and git internals."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        files.extend(Path(dirpath, name) for name in filenames)
    return files


def _committable_files() -> list[Path]:
    """Return the files git would commit: tracked plus untracked files that are not ignored.

    Untracked files are included so a pasted key is caught before its first commit.
    Outside a git checkout (for example a downloaded zip) the tree is walked instead.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return [p for p in _walk_files() if p.name not in {".env", "secrets.toml"}]
    return [ROOT / name for name in result.stdout.decode("utf-8").split("\0") if name]


def _read_text(path: Path) -> str | None:
    """Return a file's text, or None for binary or unreadable files."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _python_files() -> list[Path]:
    return [p for p in _walk_files() if p.suffix == ".py"]


def test_license_exists_at_repo_root() -> None:
    assert (ROOT / "LICENSE").is_file(), "An MIT LICENSE file must exist at the repo root (rule R5)."


def test_no_javascript_frontend() -> None:
    offenders: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = Path(dirpath).relative_to(ROOT)
        offenders += [(rel / d).as_posix() for d in dirnames if d == "node_modules"]
        offenders += [
            (rel / f).as_posix()
            for f in filenames
            if f == "package.json" or f.endswith((".jsx", ".tsx"))
        ]
        dirnames[:] = [d for d in dirnames if d != "node_modules"]
    assert not offenders, f"The frontend is Streamlit only; remove: {offenders}"


def test_requirements_exclude_js_ui_stacks() -> None:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    found = [term for term in FORBIDDEN_REQUIREMENTS if term in text]
    assert not found, f"requirements.txt mentions forbidden frontend stacks: {found}"


def test_raw_html_only_in_ui_theme_and_components() -> None:
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in _python_files()
        if p.relative_to(ROOT) not in HTML_ALLOWED_FILES and UNSAFE_HTML.search(_read_text(p) or "")
    ]
    assert not offenders, (
        f"Raw HTML is only allowed in cleat/ui/theme.py and cleat/ui/components.py: {offenders}"
    )


def test_no_novelty_effects() -> None:
    offenders = [
        p.relative_to(ROOT).as_posix() for p in _python_files() if NOVELTY_EFFECTS.search(_read_text(p) or "")
    ]
    assert not offenders, f"Balloons and snow effects are not allowed: {offenders}"


def test_env_file_is_gitignored() -> None:
    lines = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert ".env" in lines, ".env must be listed in .gitignore"


def test_no_secrets_in_committable_files() -> None:
    findings = [
        f"{path.relative_to(ROOT).as_posix()}: {label}"
        for path in _committable_files()
        if path.is_file()
        for label, pattern in SECRET_PATTERNS.items()
        if pattern.search(_read_text(path) or "")
    ]
    assert not findings, f"Possible secrets found (values not shown): {findings}"
