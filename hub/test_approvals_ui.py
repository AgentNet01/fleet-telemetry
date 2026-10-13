"""Browser: a Muse permission pop-up an agent is stuck on shows at the top of the dashboard; Allow decides it.

    python3 test_approvals_ui.py
"""
import sys, os, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import hub, tempfile
from test_autonomy import ActiveMuse
from test_hub import Clock
from test_fleet import free_port, PASSWORD
from playwright.sync_api import sync_playwright
h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), ActiveMuse(), Clock())
h.add_agent("brutus", "muse")
h.clock.t = time.time()
h.transport.pending["brutus"] = [{"id": "connector-1", "label": "Upload a file and create a public link",
    "detail": "File: pet-portrait-style-sheet-v2.png", "options": ["allow_once", "deny"], "expires": time.time() + 3000}]
h.observe()
port = free_port(); srv = hub.serve(h, "127.0.0.1", port, PASSWORD)
threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    pg = b.new_context(http_credentials={"username": "jack", "password": PASSWORD}).new_page()
    pg.goto(f"http://127.0.0.1:{port}/")
    pg.get_by_role("heading", name="Waiting for your OK").wait_for()
    assert pg.get_by_text("Upload a file and create a public link").is_visible()
    pg.get_by_role("button", name="Allow").click()
    pg.wait_for_function("document.getElementById('apwrap').hidden === true", timeout=5000)
    assert h.transport.decided == [("brutus", "connector-1", "allow_once")], h.transport.decided
    print("ui approve OK")
    b.close()
