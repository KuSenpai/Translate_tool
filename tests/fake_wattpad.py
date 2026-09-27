"""A tiny local imitation of the Wattpad writer flow, used only to test the Playwright publisher.

It is NOT Wattpad: real selectors are configured in app/publishing/wattpad_selectors.json and must
be verified against the live site.

Stories: 111 (normal), 222 (normal), 333 ("flaky": the first publish attempt fails).
"""
from __future__ import annotations

import html
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

STORIES = {"111": "Truyện Thử Nghiệm", "222": "Second Story", "333": "Flaky Story"}


class FakeWattpad:
    def __init__(self, port: int = 0, auto_login: bool = False):
        self.auto_login = auto_login  # /login signs in by itself (stands in for the user typing)
        self.empty_myworks = False
        self.parts: dict[str, dict] = {}
        self.next_id = 9000
        self.flaky_failures = {"333": 1}
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code=200, body="", ctype="text/html; charset=utf-8", headers=()):
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _redirect(self, to, headers=()):
                self._send(302, "", headers=[("Location", to), *headers])

            def _logged_in(self):
                return "token=ok" in (self.headers.get("Cookie") or "")

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/dev-login":
                    return self._redirect("/myworks", [("Set-Cookie", "token=ok; Path=/; Max-Age=86400")])
                if path == "/login":
                    auto = "<script>setTimeout(() => location.href = '/dev-login', 800)</script>" if fake.auto_login else ""
                    return self._send(body=f"<h1>Log in</h1><form><input name=u><input type=password name=p></form>{auto}")
                if path == "/":
                    trending = "".join(f'<a href="/story/{n}">.</a>' for n in (319781399, 351599673, 90623050))
                    login = "" if self._logged_in() else '<a href="/login">Log in</a>'
                    return self._send(body=f"<header>{login}</header><h3>Trending</h3>{trending}")
                if path.startswith("/myworks") and not self._logged_in():
                    return self._redirect("/")
                if path == "/myworks":
                    # Rendered by JavaScript after a delay, like a single-page app; the only links are
                    # "Continue writing" (…/write/…) and "View as reader" (/story/…), titles sit in <h3>.
                    cards = [] if fake.empty_myworks else [
                        f'<li class="story-card"><h3>{html.escape(t)}</h3>'
                        f'<a href="/myworks/{sid}-slug/write/{sid}0">Continue writing</a> '
                        f'<a href="/story/{sid}-slug">View as reader</a></li>' for sid, t in STORIES.items()]
                    script = ("<script>setTimeout(() => { document.querySelector('#list').innerHTML = "
                              + json.dumps("".join(cards)) + "; }, 2500)</script>")
                    return self._send(body=f"<h1>My Works</h1><ul id='list'></ul>{script}")
                m = re.fullmatch(r"/myworks/(\d+)(?:-[\w-]+)?", path)
                if m:
                    if m.group(1) not in STORIES:
                        return self._send(404, "<h1>Page not found</h1>")
                    return self._send(body=f'<h1>{STORIES[m.group(1)]}</h1><a href="/myworks/{m.group(1)}/write/new">+ New Part</a>')
                m = re.fullmatch(r"/myworks/(\d+)/write/new", path)
                if m:
                    fake.next_id += 1
                    pid = str(fake.next_id)
                    fake.parts[pid] = {"story": m.group(1), "title": "", "html": "", "text": "", "published": False}
                    return self._redirect(f"/myworks/{m.group(1)}/write/{pid}")
                m = re.fullmatch(r"/myworks/(\d+)/write/(\d+)", path)
                if m:
                    if m.group(2) not in fake.parts:
                        return self._send(404, "<h1>Page not found</h1>")
                    return self._send(body=EDITOR.replace("__PART__", m.group(2)))
                m = re.fullmatch(r"/(\d+)", path)
                if m and m.group(1) in fake.parts:
                    return self._send(body=f"<h1>{html.escape(fake.parts[m.group(1)]['title'])}</h1>")
                return self._send(404, "<h1>Page not found</h1>")

            def do_POST(self):
                path = urlparse(self.path).path
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                m = re.fullmatch(r"/api/(save|publish)/(\d+)", path)
                if not m or m.group(2) not in fake.parts or not self._logged_in():
                    return self._send(403, "{}", "application/json")
                part = fake.parts[m.group(2)]
                part.update(title=body["title"], html=body["html"], text=body["text"])
                if m.group(1) == "publish":
                    if fake.flaky_failures.get(part["story"], 0) > 0:
                        fake.flaky_failures[part["story"]] -= 1
                        return self._send(500, '{"error":"server error"}', "application/json")
                    part["published"] = True
                return self._send(200, "{}", "application/json")

        return H


EDITOR = """<!doctype html><html><body>
<input id="story-title" placeholder="Untitled Part">
<button class="on-save">Save</button> <button class="on-publish">Publish</button> <span id="st"></span>
<div id="storytext" contenteditable="true" style="min-height:200px;border:1px solid #ccc"></div>
<div id="dlg" role="dialog" hidden><p>Publish this part?</p><button id="go">Publish</button></div>
<script>
const part = "__PART__";
const payload = () => ({title: document.querySelector('#story-title').value,
  html: document.querySelector('#storytext').innerHTML, text: document.querySelector('#storytext').innerText});
document.querySelector('.on-save').onclick = async () => {
  await fetch('/api/save/' + part, {method: 'POST', body: JSON.stringify(payload())});
  document.querySelector('#st').textContent = 'Saved';
};
document.querySelector('.on-publish').onclick = () => { document.querySelector('#dlg').hidden = false; };
document.querySelector('#go').onclick = async () => {
  const r = await fetch('/api/publish/' + part, {method: 'POST', body: JSON.stringify(payload())});
  document.querySelector('#dlg').hidden = true;
  if (r.ok) location.href = '/' + part; else document.querySelector('#st').textContent = 'Error publishing';
};
</script></body></html>"""
