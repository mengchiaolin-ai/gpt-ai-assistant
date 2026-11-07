import json
import urllib.error
import urllib.request

import pytest

from duck_robot.animation import load_library
from duck_robot.backends.mock import MockBackend
from duck_robot.config import DuckConfig
from duck_robot.controller import DuckController
from duck_robot.server import start_server


@pytest.fixture
def server():
    cfg = DuckConfig()
    c = DuckController(MockBackend(cfg), cfg, load_library())
    srv = start_server(c, "127.0.0.1", 0, token="secret")
    yield f"http://127.0.0.1:{srv.server_address[1]}", c
    srv.shutdown()


def call(url, path, body=None, token="secret"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method="POST" if data else "GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_status_and_command(server):
    url, c = server
    status, body = call(url, "/status")
    assert status == 200 and "nod" in body["animations"]
    status, body = call(url, "/command", {"action": "stand"})
    assert status == 200 and body["mode"] == "stand"
    status, body = call(url, "/command", {"action": "play", "name": "nod"})
    assert body["animation"] == "nod"


def test_auth_required(server):
    url, _ = server
    assert call(url, "/status", token=None)[0] == 401
    assert call(url, "/command", {"action": "stand"}, token="wrong")[0] == 401


def test_bad_command_is_400(server):
    url, _ = server
    status, body = call(url, "/command", {"action": "fly"})
    assert status == 400 and "fly" in body["error"]
    assert call(url, "/command", [1, 2])[0] == 400


def test_remote_page_served(server):
    url, _ = server
    with urllib.request.urlopen(url + "/", timeout=5) as r:
        assert "Duck Remote" in r.read().decode()
