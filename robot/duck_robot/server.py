"""HTTP API：讓手機網頁、LINE 機器人或任何程式都能控制鴨子。

    GET  /           手機遙控網頁
    GET  /status     目前狀態（JSON）
    POST /command    送指令，body 是 JSON，例如 {"action": "play", "name": "nod"}

如果設定了 token，請求要帶 header：Authorization: Bearer <token>
只用 Python 標準函式庫，不需要額外安裝。
"""

from __future__ import annotations

import hmac
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .controller import CommandError, DuckController

MAX_BODY = 4096

REMOTE_PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Duck Remote</title>
<style>
:root{color-scheme:light dark;--bg:#f6f4ef;--fg:#1d1d1b;--btn:#fff;--line:#d6d2c8;--accent:#e0a100}
@media (prefers-color-scheme:dark){:root{--bg:#1b1a18;--fg:#f1efe9;--btn:#2a2926;--line:#45433e}}
body{margin:0;padding:16px;font-family:system-ui,sans-serif;background:var(--bg);color:var(--fg)}
h1{font-size:1.2rem;margin:0 0 12px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;max-width:420px}
button{padding:14px 6px;font-size:1rem;border:1px solid var(--line);border-radius:10px;background:var(--btn);color:var(--fg)}
button:active{border-color:var(--accent)}
section{margin:16px 0}
input{width:100%;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--btn);color:var(--fg);box-sizing:border-box}
pre{font-size:.8rem;white-space:pre-wrap;max-width:420px}
</style></head><body>
<h1>🦆 Duck Remote</h1>
<section><input id="token" placeholder="token（沒設定就留空）"></section>
<section class="grid">
<span></span><button data-c='{"action":"walk","vx":0.15,"duration":2}'>⬆️ 前進</button><span></span>
<button data-c='{"action":"walk","wz":0.8,"duration":2}'>↺ 左轉</button>
<button data-c='{"action":"stop"}'>⏹ 停</button>
<button data-c='{"action":"walk","wz":-0.8,"duration":2}'>↻ 右轉</button>
<button data-c='{"action":"walk","vy":0.15,"duration":2}'>⬅️ 左移</button>
<button data-c='{"action":"walk","vx":-0.1,"duration":2}'>⬇️ 後退</button>
<button data-c='{"action":"walk","vy":-0.15,"duration":2}'>➡️ 右移</button>
</section>
<section class="grid" id="anims"></section>
<section class="grid">
<button data-c='{"action":"stand"}'>🧍 站好</button>
<button data-c='{"action":"torque","enabled":false}'>💤 放鬆</button>
</section>
<pre id="out"></pre>
<script>
const out=document.getElementById('out'),tok=document.getElementById('token');
try{tok.value=localStorage.getItem('duckToken')||''}catch(e){}
tok.onchange=()=>{try{localStorage.setItem('duckToken',tok.value)}catch(e){}};
const hdr=()=>tok.value?{'Authorization':'Bearer '+tok.value}:{};
async function send(c){const r=await fetch('/command',{method:'POST',headers:{'Content-Type':'application/json',...hdr()},body:c});out.textContent=JSON.stringify(await r.json(),null,1)}
function bind(el){el.onclick=()=>send(el.dataset.c)}
document.querySelectorAll('button[data-c]').forEach(bind);
fetch('/status',{headers:hdr()}).then(r=>r.json()).then(s=>{(s.animations||[]).forEach(n=>{const b=document.createElement('button');b.textContent=n;b.dataset.c=JSON.stringify({action:'play',name:n});bind(b);document.getElementById('anims').append(b)})});
</script></body></html>"""


def make_handler(controller: DuckController, token: Optional[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DuckRobot/1.0"

        def log_message(self, fmt, *args):  # 安靜一點，不要每個請求都印
            pass

        def _authorized(self) -> bool:
            if not token:
                return True
            got = self.headers.get("Authorization", "")
            return hmac.compare_digest(got, f"Bearer {token}")

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                body = REMOTE_PAGE.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/status":
                if not self._authorized():
                    return self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                self._json(HTTPStatus.OK, controller.status())
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self):
            if self.path != "/command":
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if not self._authorized():
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "body 必須是 1~4096 位元組的 JSON"})
            try:
                cmd = json.loads(self.rfile.read(length))
                if not isinstance(cmd, dict):
                    raise ValueError
            except ValueError:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "body 不是 JSON 物件"})
            try:
                self._json(HTTPStatus.OK, controller.submit(cmd))
            except CommandError as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

    return Handler


def start_server(controller: DuckController, host: str, port: int, token: Optional[str]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(controller, token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
