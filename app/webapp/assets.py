from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

CSS_VERSION_TOKEN = "{{ PLANNER_CSS_VERSION }}"
JS_VERSION_TOKEN = "{{ PLANNER_JS_VERSION }}"


def _fingerprint(path: Path) -> str:
    """Return a stable, URL-friendly fingerprint of one asset's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _render(path: Path, replacements: dict[str, str]) -> str:
    content = path.read_text(encoding="utf-8")
    missing = [token for token in replacements if token not in content]
    if missing:
        raise RuntimeError(f"Asset template {path.name} is missing: {', '.join(missing)}")
    for token, value in replacements.items():
        content = content.replace(token, value)
    return content


@dataclass(frozen=True)
class FrontendAssets:
    index_html: str
    legacy_css: str
    legacy_js: str
    css_version: str
    js_version: str

    @classmethod
    def load(cls, static_dir: Path) -> FrontendAssets:
        css_version = _fingerprint(static_dir / "planner-v2.css")
        js_version = _fingerprint(static_dir / "planner-v2.js")
        replacements = {
            CSS_VERSION_TOKEN: css_version,
            JS_VERSION_TOKEN: js_version,
        }
        return cls(
            index_html=_render(static_dir / "index.html", replacements),
            legacy_css=_render(static_dir / "styles.css", {CSS_VERSION_TOKEN: css_version}),
            legacy_js=_render(static_dir / "app.js", {JS_VERSION_TOKEN: js_version}),
            css_version=css_version,
            js_version=js_version,
        )
