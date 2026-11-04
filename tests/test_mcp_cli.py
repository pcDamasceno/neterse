"""Proxy argument forwarding without launching external services."""
from types import ModuleType, SimpleNamespace
import sys

import pytest

from neterse import mcp


@pytest.fixture
def proxy(monkeypatch):
    captured = {}
    server = ModuleType("fastmcp.server")
    transports = ModuleType("fastmcp.client.transports")

    def create_proxy(backend, **kwargs):
        captured["backend"] = backend
        return SimpleNamespace(
            add_middleware=lambda middleware: captured.update(middleware=middleware),
            run=lambda **kwargs: captured.update(ran=True),
        )

    server.create_proxy = create_proxy
    transports.StdioTransport = lambda **kwargs: SimpleNamespace(**kwargs)
    transports.StreamableHttpTransport = lambda url, **kwargs: SimpleNamespace(url=url, **kwargs)
    monkeypatch.setitem(sys.modules, "fastmcp.server", server)
    monkeypatch.setitem(sys.modules, "fastmcp.client.transports", transports)
    monkeypatch.setattr(mcp, "CompactMiddleware", lambda **kwargs: kwargs)
    return captured


@pytest.mark.parametrize("separator", [[], ["--"]])
@pytest.mark.parametrize("command", [
    ["docker", "run", "-i", "--rm", "-e", "TOKEN", "example/server"],
    ["npx", "-y", "example-server"],
    ["python", "server.py", "--quiet", "--header", "server-option", "--help"],
])
def test_upstream_flags_keep_their_order_and_owner(proxy, separator, command):
    assert mcp.main(["--keep-structured", *separator, *command]) == 0
    backend = proxy["backend"]
    assert backend.command == command[0]
    assert backend.args == command[1:]
    assert proxy["middleware"] == {"ledger": True, "dedupe_structured": False, "max_input_chars": None}


@pytest.mark.parametrize("url_first", [True, False])
def test_url_options_work_on_either_side_and_headers_can_use_env(proxy, monkeypatch, url_first):
    monkeypatch.setenv("REVIEW_AUTHORIZATION", "Bearer test-secret")
    options = ["--quiet", "--header", "X-Tenant: lab", "--header-env", "Authorization=REVIEW_AUTHORIZATION"]
    url = "https://example.test/mcp"
    args = [url, *options] if url_first else [*options, url]
    assert mcp.main(args) == 0
    assert proxy["backend"].headers == {"X-Tenant": "lab", "Authorization": "Bearer test-secret"}
    assert proxy["middleware"]["ledger"] is False


@pytest.mark.parametrize("args", [
    [], ["--"], ["https://example.test/mcp", "unexpected"],
    ["--max-input-chars", "0", "https://example.test/mcp"],
    ["--header-env", "X-Key=UNSET_REVIEW_KEY", "https://example.test/mcp"],
    ["--header-env", "X-Key=BAD VARIABLE", "https://example.test/mcp"],
    ["--header-env", "Authorization=TOKEN", "--", "python", "server.py"],
])
def test_invalid_proxy_configuration_exits_with_a_usage_error(args, monkeypatch):
    monkeypatch.delenv("UNSET_REVIEW_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        mcp.main(args)
    assert exc.value.code == 2


def test_invalid_secret_header_does_not_leak_its_value(monkeypatch, capsys):
    monkeypatch.setenv("REVIEW_AUTHORIZATION", "secret-value\r\ninjected")
    with pytest.raises(SystemExit):
        mcp.main(["--header-env", "Authorization=REVIEW_AUTHORIZATION", "https://example.test/mcp"])
    assert "secret-value" not in capsys.readouterr().err
