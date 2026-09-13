import hashlib
from pathlib import Path

import pytest

from app.webapp.assets import FrontendAssets


def _write_bundle(directory: Path, *, css: str = "body{}", js: str = "start();") -> None:
    (directory / "planner-v2.css").write_text(css, encoding="utf-8")
    (directory / "planner-v2.js").write_text(js, encoding="utf-8")
    (directory / "index.html").write_text(
        "css={{ PLANNER_CSS_VERSION }} js={{ PLANNER_JS_VERSION }}", encoding="utf-8"
    )
    (directory / "styles.css").write_text("css={{ PLANNER_CSS_VERSION }}", encoding="utf-8")
    (directory / "app.js").write_text("js={{ PLANNER_JS_VERSION }}", encoding="utf-8")


def test_asset_versions_follow_file_contents(tmp_path):
    _write_bundle(tmp_path)

    bundle = FrontendAssets.load(tmp_path)

    expected_css = hashlib.sha256(b"body{}").hexdigest()[:16]
    expected_js = hashlib.sha256(b"start();").hexdigest()[:16]
    assert bundle.css_version == expected_css
    assert bundle.js_version == expected_js
    assert bundle.index_html == f"css={expected_css} js={expected_js}"
    assert bundle.legacy_css == f"css={expected_css}"
    assert bundle.legacy_js == f"js={expected_js}"


def test_changing_css_only_changes_css_urls(tmp_path):
    _write_bundle(tmp_path)
    first = FrontendAssets.load(tmp_path)
    _write_bundle(tmp_path, css="body{color:red}")

    second = FrontendAssets.load(tmp_path)

    assert second.css_version != first.css_version
    assert second.js_version == first.js_version
    assert first.css_version not in second.index_html
    assert second.css_version in second.index_html


def test_missing_template_token_fails_at_startup(tmp_path):
    _write_bundle(tmp_path)
    (tmp_path / "styles.css").write_text("body{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="styles.css is missing"):
        FrontendAssets.load(tmp_path)
