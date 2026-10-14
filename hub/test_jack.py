"""Jack's side: what lands on his list is something he can act on, and work for him never hides in Done.

    python3 test_jack.py steps    # a task whose result is work for Jack can't finish until its steps are on his list
    python3 test_jack.py reply    # Jack answers an item on his list; the agent gets it and the task goes back to it
    python3 test_jack.py tools    # a product can be a tool: shared by every product, listed apart
    python3 test_jack.py doc      # the doc viewer only fetches Muse files and can't be broken out of
    python3 test_jack.py show     # any agent looks up any task's result link itself instead of asking the CEO
    python3 test_jack.py ui       # in the browser: Jack opens a #reference, replies from his list, sees Tools apart
"""
import sys

import hub
from test_autonomy import new_hub


def steps():
    """Jack, Oct 13: #59 "What Jack must set up for physical orders" went to Done and he never saw what to do."""
    h, muse, clock = new_hub("Neo")
    pj = h.add_project(h.add_product("Fulfillment", brief="ship things"), "setup")
    tid = h.add_task(pj, "What Jack must set up for physical orders", "optimizer", "ordered checklist", owner="Neo")
    h.tick(); h.tick()
    try:
        h.task_done("Neo", tid, "https://x/checklist.md")
        raise AssertionError("steps: a task for Jack finished with nothing on his list")
    except ValueError as e:
        assert "fleet task operator" in str(e), e
    h.task_for_jack("Neo", tid, "Open a Printful account at https://printful.com — needed before any order ships")
    need = [n for n in h.needs_jack() if n["task"] == tid]
    assert need and "Printful" in need[0]["text"] and need[0]["agent"] == "Neo", h.needs_jack()
    assert h.task(tid)["status"] == "working", "steps: filing a step doesn't park the task"
    h.task_done("Neo", tid, "https://x/checklist.md")
    assert h.task(tid)["status"] == "verifying"
    assert [n for n in h.needs_jack() if n["task"] == tid], "steps: Jack's step stays on his list after done"

    assert any("fleet task operator" in s for s in muse.sent.get("Neo", [])), \
        "steps: handed a task, the agent is told to file operator-only steps as it finds them"

    plain = h.add_task(pj, "Packaging research", "optimizer", "doc", owner="Neo")
    h.tick(); h.tick()
    h.task_done("Neo", plain, "https://x/pack.md")          # nothing for Jack: no step needed
    try:
        h.task_for_jack("Neo", plain, "x")
        raise AssertionError("steps: only the holder of a working task files steps for it")
    except PermissionError:
        pass
    h.add_agent("Bo", "muse")
    for _ in range(4):
        h.tick()
    asked = [s for s in muse.sent.get("Bo", []) + muse.sent.get("Neo", []) if "verify task" in s]
    assert asked and all("operator" in s for s in asked), f"steps: verifiers check nothing operator-only was left off: {asked}"
    print("steps OK")


def reply():
    h, muse, clock = new_hub("brutus")
    pj = h.add_project(h.add_product("Hats", brief="custom hats"), "launch")
    tid = h.add_task(pj, "Listing images", "designer", "images", owner="brutus")
    h.tick(); h.tick()
    h.task_wait("brutus", tid, "jack", "is physical product work in scope?")
    n = [n for n in h.needs_jack() if n["task"] == tid][0]
    assert n["agent"] == "brutus", n
    h.reply_need(n["id"], "jack", "Yes, physical products are in scope. Carry on.")
    for _ in range(3):
        h.tick()
    assert any("physical products are in scope" in s for s in muse.sent.get("brutus", [])), muse.sent.get("brutus")
    assert not [x for x in h.needs_jack() if x["id"] == n["id"]], "reply: answered item leaves his list"
    t = h.task(tid)
    assert t["waiting_on"] is None and "brutus" in (t["owner"], t["pin"]), f"reply: task back to brutus: {t}"
    try:
        h._needs_jack("a hub notice nobody raised")
        notice = [x for x in h.needs_jack() if x["text"] == "a hub notice nobody raised"][0]
        h.reply_need(notice["id"], "jack", "x")
        raise AssertionError("reply: an item no agent raised has nobody to reply to")
    except ValueError:
        pass
    print("reply OK")


def tools():
    h, muse, clock = new_hub("Dash")
    h.add_product("Physical fulfillment", brief="ship orders")
    h.add_product("Birthday paddles", brief="paddles")
    h.manage("jack", "product set \"Physical fulfillment\" kind tool")
    kinds = {p["name"]: p["kind"] for p in h.portfolio()}
    assert kinds == {"Physical fulfillment": "tool", "Birthday paddles": "product"}, kinds
    try:
        h.manage("jack", "product set \"Birthday paddles\" kind gadget")
        raise AssertionError("tools: kind is product or tool")
    except ValueError:
        pass
    assert "tool #1 Physical fulfillment" in h._portfolio(), "tools: agents' portfolio says which are tools"
    print("tools OK")


def doc():
    ok = "https://muse.ai/files/1/2/abc/plan-216.md"
    assert hub.doc_source_ok(ok)
    for bad in ("http://muse.ai/files/1/x.md", "https://muse.ai.evil.com/files/x.md", "https://evil.com/?https://muse.ai/files/",
                "https://muse.ai/api/secret", "file:///etc/passwd", "https://muse.ai@evil.com/files/x.md"):
        assert not hub.doc_source_ok(bad), bad
    page = hub.doc_page(ok, "# Title\n</script><script>alert(1)</script>")
    assert page.count("</script>") == page.count("<script") , "doc: the text can't close the data script"
    assert "DOMPurify" in page and "marked" in page
    print("doc OK")


def show():
    """Oct 13: Neo asked dot (the CEO, over Slack) for #188's evidence link; nothing let it look the link up."""
    import os, subprocess, tempfile, threading
    h, muse, clock = new_hub("Neo", "Pericles")
    pj = h.add_project(h.add_product("Books", brief="storybooks"), "launch")
    copy = h.add_task(pj, "storybook listing copy", "marketer", "copy doc", owner="Pericles")
    h.tick(); h.tick()
    h.task_done("Pericles", copy, "https://muse.ai/files/1/2/x/copy-188.md")
    tok = h.add_agent("Neo", "muse")
    srv = hub.serve(h, "127.0.0.1", 0, "pw")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ, FLEET_HUB=f"http://127.0.0.1:{srv.server_address[1]}", FLEET_TOKEN=tok, FLEET_HOME=tempfile.mkdtemp())
    out = subprocess.run([sys.executable, "fleet.py", "task", "show", str(copy)], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "https://muse.ai/files/1/2/x/copy-188.md" in out.stdout and "Pericles" in out.stdout, out.stdout
    ops = h.add_task(pj, "What an operator must set up", "marketer", "steps on the operator list", owner="Pericles")
    h.tick(); h.tick()
    h.task_for_jack("Pericles", ops, "Open a Printful account at https://printful.com")
    out = subprocess.run([sys.executable, "fleet.py", "task", "show", str(ops)], env=env, capture_output=True, text=True)
    assert "Open a Printful account" in out.stdout, "show: what's on the operator list for the task: " + out.stdout
    print("show OK")


def ui():
    import threading
    from playwright.sync_api import expect, sync_playwright
    h, muse, clock = new_hub("brutus")
    pj = h.add_project(h.add_product("Hats", brief="custom hats"), "launch")
    h.add_product("Physical fulfillment", brief="ship orders")
    h.manage("jack", 'product set "Physical fulfillment" kind tool')
    tid = h.add_task(pj, "Listing images", "designer", "images", owner="brutus")
    h.tick(); h.tick()
    h.task_wait("brutus", tid, "jack", "is physical work in scope? See https://muse.ai/files/1/2/x/scope.md")
    srv = hub.serve(h, "127.0.0.1", 0, "pw")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page(http_credentials={"username": "jack", "password": "pw"})
        page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
        row = page.locator(".njrow", has_text="is physical work in scope")
        expect(row.get_by_role("link", name="https://muse.ai/files/1/2/x/scope.md")).to_have_attribute(
            "href", "doc?u=https%3A%2F%2Fmuse.ai%2Ffiles%2F1%2F2%2Fx%2Fscope.md")
        row.get_by_role("link", name=f"#{tid}").click()
        expect(page.get_by_role("dialog")).to_contain_text("Listing images")
        page.get_by_role("dialog").get_by_role("button", name="Close").click()
        row.get_by_role("button", name="Reply").click()
        row.get_by_role("textbox", name="Reply to brutus").fill("Yes, physical products are in scope.")
        row.get_by_role("button", name="Send").click()
        expect(page.locator(".njrow", has_text="is physical work in scope")).to_have_count(0)
        page.get_by_role("tab", name="Portfolio").click()
        expect(page.locator("#tools")).to_contain_text("Physical fulfillment")
        expect(page.locator("#products")).not_to_contain_text("Physical fulfillment")
    assert any("physical products are in scope" in s for s in muse.sent.get("brutus", [])), muse.sent.get("brutus")
    print("ui OK")


{"steps": steps, "reply": reply, "tools": tools, "doc": doc, "show": show, "ui": ui}[sys.argv[1]]()
