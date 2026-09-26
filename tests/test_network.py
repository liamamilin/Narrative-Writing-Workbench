from __future__ import annotations

from workbench.network import server_info


def test_server_info_exposes_configured_lan_url(monkeypatch):
    monkeypatch.setenv("WORKBENCH_PUBLIC_HOST", "0.0.0.0")
    monkeypatch.setenv("WORKBENCH_PUBLIC_PORT", "18600")
    monkeypatch.setenv("WORKBENCH_ADVERTISED_HOST", "192.168.1.23")

    info = server_info()

    assert info["local_url"] == "http://127.0.0.1:18600"
    assert info["lan_url"] == "http://192.168.1.23:18600"
    assert info["lan_enabled"] is True


def test_server_info_hides_lan_url_in_local_only_mode(monkeypatch):
    monkeypatch.setenv("WORKBENCH_PUBLIC_HOST", "127.0.0.1")
    monkeypatch.setenv("WORKBENCH_PUBLIC_PORT", "18601")
    monkeypatch.setenv("WORKBENCH_ADVERTISED_HOST", "192.168.1.23")

    info = server_info()

    assert info["local_url"] == "http://127.0.0.1:18601"
    assert info["lan_url"] is None
    assert info["lan_enabled"] is False
