"""Tests for ProofMesh read-only local web status panel."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.error
import urllib.request
import pytest

from proofmesh.demo import run_seeded_demo
from proofmesh.storage.store import ProofMeshStore
from proofmesh.ui import (
    create_ui_server,
    get_receipt_for_session,
    render_dashboard_html,
)


def test_render_dashboard_html_none() -> None:
    """Fallback HTML is rendered when no session receipt exists."""
    html = render_dashboard_html(None)
    assert "<!DOCTYPE html>" in html
    assert "No Active ProofMesh Session" in html


def test_render_dashboard_html_populated(tmp_path: Path) -> None:
    """Dashboard HTML renders tables, badges, pills, and contract metadata."""
    demo_dir = tmp_path / "demo_target"
    db_file = tmp_path / "store" / "demo.db"
    demo_result = run_seeded_demo(demo_dir, db_path=db_file)
    blocked_receipt = demo_result["blocked_receipt_json"]

    html_blocked = render_dashboard_html(blocked_receipt)
    assert "<!DOCTYPE html>" in html_blocked
    assert "ProofMesh Control Layer" in html_blocked
    assert "task-calc-extension" in html_blocked
    assert "BLOCK" in html_blocked
    assert "config/security.toml" in html_blocked
    assert "Restricted" in html_blocked

    final_receipt = demo_result["receipt_json"]
    html_final = render_dashboard_html(final_receipt)
    assert "ALLOW" in html_final
    assert "pytest" in html_final


def test_ui_server_endpoints_and_security(tmp_path: Path) -> None:
    """Test HTTP server endpoints (HTML, /api/status), 405 rejection, and localhost binding."""
    demo_dir = tmp_path / "demo_target"
    db_file = tmp_path / "store" / "demo.db"
    run_seeded_demo(demo_dir, db_path=db_file)

    store = ProofMeshStore(db_file)

    # Security check: Non-localhost binding must raise ValueError
    with pytest.raises(ValueError, match="must only bind to 127.0.0.1 or localhost"):
        create_ui_server(store, host="0.0.0.0", port=0)

    # Start server on ephemeral port (0)
    server = create_ui_server(store, host="127.0.0.1", port=0)
    host, port = server.server_address

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://{host}:{port}"
    try:
        # 1. GET / -> HTML
        req = urllib.request.Request(f"{base_url}/")
        with opener.open(req) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            content = resp.read().decode("utf-8")
            assert "ProofMesh Control Layer" in content
            assert "task-calc-extension" in content

        # 2. GET /api/status -> JSON
        req_api = urllib.request.Request(f"{base_url}/api/status")
        with opener.open(req_api) as resp:
            assert resp.status == 200
            assert "application/json" in resp.headers.get("Content-Type", "")
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("schema_version") == "1.0"
            assert "verdict" in data

        # 3. POST / -> 405 Method Not Allowed
        post_req = urllib.request.Request(f"{base_url}/", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(post_req)
        assert exc_info.value.code == 405

        # 4. GET /unknown -> 404 Not Found
        unknown_req = urllib.request.Request(f"{base_url}/nonexistent")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(unknown_req)
        assert exc_info.value.code == 404

    finally:
        server.shutdown()
        server.server_close()
