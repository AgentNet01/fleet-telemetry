"""Jack's side: what lands on his list is something he can act on, and work for him never hides in Done.

    python3 test_jack.py steps    # a task whose result is work for Jack can't finish until its steps are on his list
    python3 test_jack.py reply    # Jack answers an item on his list; the agent gets it and the task goes back to it
    python3 test_jack.py tools    # a product can be a tool: shared by every product, listed apart
    python3 test_jack.py doc      # the doc viewer only fetches Muse files and can't be broken out of
    python3 test_jack.py show     # any agent looks up any task's result link itself instead of asking the CEO
    python3 test_jack.py plain    # each item is one short action, why it blocks, and a link — rambling is refused
    python3 test_jack.py since    # the board says when each worker took its task, and since when an idle one has been free
    python3 test_jack.py pm       # agents' asks go to the PM, who merges them into Jack's list and routes his answer
    python3 test_jack.py ui       # in the browser: Jack opens a #reference, replies from his list, sees Tools apart
"""
import sys

import hub
from test_autonomy import new_hub

def open_page(page, name):
    """The pages live in the ☰ menu (Jack, Oct 15: the office is the whole page)."""
    page.locator(".menubtn:visible").first.click()
    page.get_by_role("tab", name=name).click()



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
    h.task_for_jack("Neo", tid, "Open a Printful account — needed before any order ships", None, "https://www.printful.com/auth/register")
    need = [n for n in h.needs_jack() if n["task"] == tid]
    assert need and "Printful" in need[0]["text"] and need[0]["agent"] == "Neo", h.needs_jack()
    assert h.task(tid)["status"] == "working", "steps: filing a step doesn't park the task"
    h.task_done("Neo", tid, "https://x/checklist.md")
    assert h.task(tid)["status"] == "verifying"
    assert [n for n in h.needs_jack() if n["task"] == tid], "steps: Jack's step stays on his list after done"

    handout = [s for s in muse.sent.get("Neo", []) if "fleet task operator" in s]
    assert handout and "Sign up for accounts yourself" in handout[0] and "account only they" not in handout[0] \
        and "decide yourself" in handout[0] and "approval" not in handout[0], \
        "steps: only real blockers go to the operators; choices stay with the agents"
    assert "AI-generated" in handout[0] and "PHOTO HERE" in handout[0] and "template" in handout[0], "steps: Jack, Oct 15: listing photos carry no AI/sample labels or placeholders"
    assert "Personalization instructions" in handout[0], "steps: Jack, Oct 15: personalization boxes are written for a layman"
    assert "never make" in handout[0], "steps: Jack, Oct 15 (paddles): agents are told the operators never make or ship anything"
    assert any("fleet task operator" in s for s in muse.sent.get("Neo", [])), \
        "steps: handed a task, the agent is told to file operator-only steps as it finds them"

    plain = h.add_task(pj, "Packaging research", "optimizer", "doc", owner="Neo")
    h.tick(); h.tick()
    h.task_done("Neo", plain, "https://x/pack.md")          # nothing for Jack: no step needed
    # Jack, Oct 15: #826's done-when only said "or the exact blocker if it needs an account only an operator can open",
    # and the forced step made the agent dump four decisions on his list
    quote = h.add_task(pj, "Run the BookVault quote", "optimizer",
                       "quote doc; or the exact blocker if the tool requires an account only an operator can open", owner="Neo")
    h.tick(); h.tick()
    h.task_done("Neo", quote, "https://x/quote.md")
    rule = h.add_task(pj, "Redesign listing images per Jack's Oct 15 photo rule", "designer", "image set", owner="Neo")
    h.tick(); h.tick()
    h.task_done("Neo", rule, "https://x/images.md")
    assert h.task(rule)["status"] == "verifying", "steps: a title that cites Jack's rule isn't work for Jack"
    assert h.task(quote)["status"] == "verifying", "steps: a done-when that only mentions an operator can finish"
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


def plain():
    """Jack, Oct 13: "these are incredibly unclear instructions" — each item says what to do in one line."""
    h, muse, clock = new_hub("Boboe 6")
    pj = h.add_project(h.add_product("Shop", brief="etsy"), "launch")
    tid = h.add_task(pj, "Automate order updates", "engineer", "spec", owner="Boboe 6")
    h.tick(); h.tick()
    h.task_for_jack("Boboe 6", tid, "Create an Etsy API app for your shop",
                    "Agents can't send tracking numbers or buyer messages through Etsy until it exists",
                    "https://www.etsy.com/developers/register")
    n = [x for x in h.needs_jack() if x["task"] == tid][0]
    assert (n["what"], n["why"], n["link"]) == ("Create an Etsy API app for your shop",
        "Agents can't send tracking numbers or buyer messages through Etsy until it exists",
        "https://www.etsy.com/developers/register"), n
    try:
        h.task_for_jack("Boboe 6", tid, "Log into the Printful and PrintKK seller dashboards and report the production times "
                        "and US transit times for our products (Printful: art prints, mugs, tumblers; PrintKK: ornaments)")
        raise AssertionError("plain: a rambling action line is refused")
    except ValueError as e:
        assert "one short line" in str(e), e
    try:
        h.task_for_jack("Boboe 6", tid, "Open Printful", "needed", "printful.com")
        raise AssertionError("plain: a link must be a web address")
    except ValueError:
        pass
    print("plain OK")


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
    h.task_for_jack("Pericles", ops, "Open a Printful account", None, "https://www.printful.com/auth/register")
    out = subprocess.run([sys.executable, "fleet.py", "task", "show", str(ops)], env=env, capture_output=True, text=True)
    assert "Open a Printful account" in out.stdout, "show: what's on the operator list for the task: " + out.stdout
    print("show OK")


def since():
    """Jack, Oct 14: above everybody, how long they've been on the task, or how long they've been idle."""
    h, muse, clock = new_hub("Ada", "Bo")
    pj = h.add_project(h.add_product("Shop", brief="x"), "launch")
    h.tick(); taken = clock()
    t = h.add_task(pj, "build the sheet", "engineer", "xlsx", owner="Ada")
    h.tick(); h.tick()
    clock.go(1500); h.tick()
    rows = {a["name"]: a for a in h.board()["agents"]}
    assert rows["Ada"]["task"]["id"] == t and abs(rows["Ada"]["task"]["since"] - (taken)) < 60, rows["Ada"]["task"]
    assert rows["Bo"]["task"] is None and rows["Bo"]["free_since"] and clock() - rows["Bo"]["free_since"] >= 1500, rows["Bo"]
    print("since OK")


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
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
        page.wait_for_timeout(1500)
        assert not errors, f"ui: the page runs without errors (one blanked the office): {errors}"
        page.wait_for_function("window.Office3D && Office3D.debug.state().ready", timeout=30000)
        page.mouse.click(*page.evaluate("(() => { const s = Office.sim.SHRINE; return Office3D.debug.project(s.x + .4, s.y + .4, .4); })()"))   # the shrine points to the page
        expect(page.locator("#needs")).to_be_visible()
        expect(page.locator('[data-tab="needs"]')).to_have_attribute("aria-selected", "true")
        row = page.locator(".njrow", has_text="is physical work in scope")
        expect(row.get_by_role("textbox")).to_be_hidden()                   # the reply box opens on Reply, not before
        expect(row).to_contain_text("brutus")
        expect(row.get_by_role("link", name="https://muse.ai/files/1/2/x/scope.md")).to_have_attribute(
            "href", "doc?u=https%3A%2F%2Fmuse.ai%2Ffiles%2F1%2F2%2Fx%2Fscope.md")
        row.get_by_role("link", name=f"#{tid}").click()
        expect(page.get_by_role("dialog")).to_contain_text("Listing images")
        page.get_by_role("dialog").get_by_role("button", name="Close").click()
        row.get_by_role("button", name="Reply").click()
        row.get_by_role("textbox", name="Reply to brutus").fill("Yes, physical products are in scope.")
        row.get_by_role("button", name="Send").click()
        expect(page.locator(".njrow", has_text="is physical work in scope")).to_have_count(0)
        open_page(page, "Portfolio")
        expect(page.locator("#tools")).to_contain_text("Physical fulfillment")
        expect(page.locator("#products")).not_to_contain_text("Physical fulfillment")
    assert any("physical products are in scope" in s for s in muse.sent.get("brutus", [])), muse.sent.get("brutus")
    print("ui OK")


def pm():
    """Jack, Oct 14: Pericles decides what reaches him. An agent's ask goes to the CEO first, who answers it itself
    (which print company to use) or rewrites it into a plain line for Jack. One the CEO hasn't decided in SCREEN_WAIT
    goes to Jack as it is, so nothing gets stuck with the CEO again (49 did)."""
    h, muse, clock = new_hub("Neo", "Bo", "Pam")
    h.seat("ceo", "Pam")
    pj = h.add_project(h.add_product("Hats", brief="hats", pm="Pam"), "launch")
    a = h.add_task(pj, "Print partner runbook", "engineer", "doc", owner="Neo")
    b = h.add_task(pj, "Hat ads", "marketer", "doc", owner="Bo")
    h.tick(); h.tick()

    def ceo_says(text):
        muse.say("Pam", text); h.tick(); clock.go(61); h.tick(); h.tick()

    h.task_for_jack("Neo", a, "Get PrintKK dashboard access", "test order", "https://printkk.com")
    assert not h.needs_jack(), f"pm: an agent's ask isn't on Jack's list before the CEO has looked: {h.needs_jack()}"
    h.tick()
    assert any("Get PrintKK dashboard access" in m for m in muse.sent.get("Pam", [])), "pm: the CEO is shown the ask"
    ceo_says("ANSWER: Use Printify, it's set up. Skip PrintKK.")
    assert any("Use Printify" in m for m in muse.sent.get("Neo", [])), "pm: the CEO's answer goes to the agent"
    assert not h.needs_jack(), f"pm: an ask the CEO answered never reaches Jack: {h.needs_jack()}"

    h.task_wait("Bo", b, "jack", "Pls approve ads spend 14 for hats per plan #553")
    h.tick()
    ceo_says("JACK: Approve $14 of Etsy ads for the hats listing, $1 a day for 2 weeks. https://www.etsy.com/listing/1")
    mine = h.needs_jack()
    assert len(mine) == 1 and mine[0]["what"].startswith("Approve $14 of Etsy ads") and mine[0]["agent"] == "Bo", \
        f"pm: what reaches Jack is the CEO's plain line: {mine}"
    assert mine[0]["link"] == "https://www.etsy.com/listing/1", f"pm: with the CEO's link: {mine[0]}"

    # Oct 16: a screener forwarded "solve a ProtonMail CAPTCHA by screen-share" to Jack. Forwarded or not, only payment or ID reaches him
    for said in ("JACK: Solve the ProtonMail signup CAPTCHA by screen-share with Neo", "ok, looking into it"):
        h.task_for_jack("Neo", a, "Solve a CAPTCHA for my ProtonMail signup", "need a mailbox", "https://proton.me/mail")
        h.tick()
        ceo_says(said)
        assert not [n for n in h.needs_jack() if "CAPTCHA" in n["what"]], f"pm: {said!r} doesn't put a non-money ask on Jack's list"
        assert any("isn't payment or ID" in m and "CAPTCHA" in m for m in muse.sent.get("Neo", [])), "pm: the agent is told it's its own"

    h.task_for_jack("Neo", a, "Add a card to PrintKK", "orders", "https://printkk.com/billing")
    h.tick()
    clock.go(hub.SCREEN_WAIT + 1); h.tick()
    assert any(n["what"] == "Add a card to PrintKK" for n in h.needs_jack()), "pm: an ask the CEO sat on reaches Jack anyway"

    nid = h.jack_add("Pam", "Open a Printify account and connect it to Etsy", "hats can't sell", "https://printify.com")
    assert nid in [n["id"] for n in h.needs_jack()], "pm: the CEO or a PM can still put its own line on Jack's list"
    try:
        h.jack_add("Neo", "x")
        raise AssertionError("pm: only a PM or the CEO adds to Jack's list")
    except PermissionError:
        pass
    print("pm OK")


def repeat():
    """Jack, Oct 15: he got asked to connect Printify (already linked) and to approve the magnets listing again, and the
    CEO's own ask ("DO NOT PUBLISH gate on storybooks…") reached him unchecked. Whoever screens an ask now sees what Jack
    already answered, and the CEO's own asks go to its stand-in."""
    h, muse, clock = new_hub("Neo", "Bo", "Pam")
    h.seat("ceo", "Pam"); h.seat("ceo_backup", "Bo")
    pj = h.add_project(h.add_product("Magnets", brief="magnets", pm="Pam"), "launch")
    a = h.add_task(pj, "Magnet listing", "designer", "doc", owner="Neo")
    c = h.add_task(pj, "Launch checklist", "pm", "doc", owner="Pam")
    h.tick(); h.tick()

    def ceo_says(text):
        muse.say("Pam", text); h.tick(); clock.go(61); h.tick(); h.tick()

    nid = h.jack_add("Pam", "Publish the magnets listing on Etsy", None, "https://www.etsy.com/listing/9")
    h.reply_need(nid, "jack", "Approved, publish it.")
    h.tick()
    ceo_says("Thanks.")
    h.resolve_need(h.jack_add("Pam", "Connect Printify to the Etsy shop", None, "https://printify.com"))
    h.task_for_jack("Neo", a, "Approve publishing the magnets listing", "can't go live", "https://www.etsy.com/listing/9")
    h.tick()
    shown = [m for m in muse.sent.get("Pam", []) if "Approve publishing the magnets listing" in m]
    assert shown and "Approved, publish it." in shown[-1] and "Connect Printify to the Etsy shop" in shown[-1], \
        f"repeat: the CEO sees what Jack already answered: {shown}"

    h.task_wait("Pam", c, "jack", "DO NOT PUBLISH gate on storybooks — checklist not actionable until publish is authorized")
    h.tick()
    assert not [n for n in h.needs_jack() if n["task"] == c], f"repeat: the CEO's own ask isn't on Jack's list unchecked: {h.needs_jack()}"
    assert any("DO NOT PUBLISH gate" in m for m in muse.sent.get("Bo", [])), "repeat: the CEO's stand-in checks it"
    print("repeat OK")


def pmwait():
    """Jack, Oct 15: five listing tasks sat on "PM decision needed" waiting on 'outside', so the PM never heard.
    Waiting on "pm" reaches the product's PM; the screener is told posting is the agents' job, only spending is Jack's."""
    h, muse, clock = new_hub("Neo", "Pam")
    pj = h.add_project(h.add_product("Keychains", brief="k", pm="Pam"), "launch")
    t = h.add_task(pj, "Keychain listing assembly", "designer", "doc", owner="Neo")
    h.tick(); h.tick()
    h.task_wait("Neo", t, "pm", "pick the keychain price: A 9.99, B 4.99 or C 6.99")
    for _ in range(3):
        h.tick()
    assert h.task(t)["waiting_on"] == "Pam", h.task(t)
    assert any("pick the keychain price" in m for m in muse.sent.get("Pam", [])), "pmwait: the PM is told"
    assert "posting" in hub.OPERATOR_ONLY.lower() and "spend" in hub.OPERATOR_ONLY.lower(), hub.OPERATOR_ONLY
    print("pmwait OK")


def said_not_raised():
    """Jack, Oct 16: "they need a BookVault account ... Pericles said it was waiting on me because they need payment info,
    and it wasn't on my needs list." Waits and notes said "waiting on Jack" in words; nothing reached his list."""
    h, muse, clock = new_hub("Neo")
    pj = h.add_project(h.add_product("Books", brief="b"), "launch")
    def start(name):
        t = h.add_task(pj, name, "marketer", "done", owner="Neo"); h.tick(); h.tick()
        assert h.task(t)["status"] == "working", h.task(t)
        return t
    ads = start("Ads")
    h.task_wait("Neo", ads, "outside", "No ad spend approval from Jack: 14 dollars of Etsy Ads")
    assert [n for n in h.db.execute("select * from needs_jack where task=?", (ads,))], "said_not_raised: money from Jack, parked on outside, still reaches his list"
    pins = start("Pins")
    h.task_wait("Neo", pins, "outside", "Pinterest account decision, then I sign up per Jack's rule")
    assert not h.db.execute("select 1 from needs_jack where task=?", (pins,)).fetchone(), "said_not_raised: naming Jack's rule isn't an ask"
    vault = start("BookVault")
    try:
        h.task_note("Neo", vault, "Blocked: waiting on Jack for payment info on the BookVault signup")
        raise AssertionError("said_not_raised: a note claiming it waits on Jack, with nothing on his list, is refused")
    except ValueError as e:
        assert "fleet task operator" in str(e), e
    h.task_note("Neo", vault, "Drafted the interior; cover next")
    print("said_not_raised OK")


def busy_ceo():
    """Jack, Oct 15: Pericles was busy in the Etsy dashboard, so "review the banner images" sat 30 min unscreened and
    reached Jack as written. A busy CEO's ask goes to the stand-in first; only if it sits there too does Jack get it."""
    h, muse, clock = new_hub("Neo", "Bo", "Pam")
    h.seat("ceo", "Pam"); h.seat("ceo_backup", "Bo")
    pj = h.add_project(h.add_product("Banners", brief="b", pm="Pam"), "launch")
    t = h.add_task(pj, "Banner images", "designer", "images", owner="Neo")
    h.tick(); h.tick()
    muse.say("Pam", "on it"); h.tick()
    h.task_for_jack("Neo", t, "Review the banner images and approve them", "listing", "https://www.etsy.com/listing/1")
    h.tick()
    clock.go(hub.SCREEN_WAIT + 1); h.tick(); h.tick()
    assert not h.needs_jack(), f"busy_ceo: one unsorted wait isn't enough to reach Jack: {h.needs_jack()}"
    assert any("Review the banner images" in m and "you decide" in m for m in muse.sent.get("Bo", [])), "busy_ceo: the stand-in screens it"
    clock.go(hub.SCREEN_WAIT + 1); h.tick(); h.tick()
    # Oct 15: with Pericles swamped, "reactivate the listing", "check the Printful rate" and "connect Outlook" were heading
    # to Jack unscreened. Unsorted twice, only payment or ID reaches him; anything else goes back to the agent as its own
    assert not h.needs_jack(), f"busy_ceo: unscreened, an ask that isn't money or ID never reaches Jack: {h.needs_jack()}"
    assert any("Review the banner images" in m and "yours" in m for m in muse.sent.get("Neo", [])), \
        f"busy_ceo: the agent is told it's its own call: {muse.sent.get('Neo')}"
    assert h.task(t)["waiting_on"] is None, "busy_ceo: its task isn't left waiting on Jack"
    h.task_for_jack("Neo", t, "Approve 14 dollars of Etsy Ads for the banners", "ads cost money", "https://www.etsy.com/your/shops/me/advertising")
    h.tick()
    for _ in range(2):
        clock.go(hub.SCREEN_WAIT + 1); h.tick(); h.tick()
    assert [n["what"] for n in h.needs_jack()] == ["Approve 14 dollars of Etsy Ads for the banners"], "busy_ceo: money still reaches Jack"
    print("busy_ceo OK")


def actionable():
    """Jack, Oct 15: "I click on open and it just opens this really long confusing markdown file ... I don't know what
    email to create this BookVault account with." An item for him links to the page where he acts, not the agent's notes."""
    h, muse, clock = new_hub("Dash")
    pj = h.add_project(h.add_product("Books", brief="b"), "launch")
    t = h.add_task(pj, "Book proofs", "engineer", "doc", owner="Dash")
    h.tick(); h.tick()
    try:
        h.task_for_jack("Dash", t, "Set up the BookVault account", "orders need it", "https://muse.ai/files/1/2/x/bookvault-steps.md")
        raise AssertionError("actionable: a notes file isn't where Jack acts")
    except ValueError as e:
        assert "notes" in str(e) and "email" in str(e), e
    h.task_for_jack("Dash", t, "Add a card to BookVault (sign in with pericleswilliams106@gmail.com)", "orders need it",
                    "https://bookvault.app/billing")
    print("actionable OK")


def keys():
    """Jack, Oct 15: Neo told Jack "Printify isn't connected, I can't read the key" while PRINTIFY_API_KEY sat in the
    vault for every agent. Each task tells its holder which keys it can read."""
    h, muse, clock = new_hub("Neo")
    h.secret_put("PRINTIFY_API_KEY", "k", "fleet", by="jack")
    h.secret_put("darraghs-bank", "k", "agent:Darragh", by="jack")
    h.jobs_dir = __import__("tempfile").mkdtemp()
    open(h.jobs_dir + "/tools.json", "w").write('[{"name": "imagegen", "about": "local image generation"}]')
    pj = h.add_project(h.add_product("Cups", brief="c"), "launch")
    h.add_task(pj, "Price the cups", "optimizer", "doc", owner="Neo")
    h.tick(); h.tick()
    task = [m for m in muse.sent.get("Neo", []) if "Price the cups" in m]
    assert "fleet tool run imagegen" in task[-1], f"keys: the hub's GPU tools are named too: {task}"
    assert "$10 or less" in task[-1] and "AliExpress" in task[-1] and "CAPTCHA" in task[-1], "keys: Jack's Oct 16 rules (cheap new products, no browser takeovers) ride with every task"
    assert task and "PRINTIFY_API_KEY" in task[-1] and "fleet secret get" in task[-1] and "darraghs-bank" not in task[-1], f"keys: {task}"
    print("keys OK")


def newpm():
    """Jack, Oct 15: nine products got new PMs while the fleet sat idle, but the "no work lined up" asks stayed with
    the old PM, so the new ones weren't asked to plan for hours. A new PM is asked at once."""
    h, muse, clock = new_hub("Neo", "Bo", "Pam")
    h.add_project(h.add_product("Hats", brief="hats", pm="Pam"), "launch")
    h.tick(); h.tick()
    assert any("Hats has no work lined up" in m for m in muse.sent.get("Pam", [])), "newpm: the old PM was asked first"
    h.set_pm("Hats", "Bo")
    h.tick(); h.tick()
    assert any("Hats has no work lined up" in m for m in muse.sent.get("Bo", [])), f"newpm: the new PM is asked: {muse.sent.get('Bo')}"
    print("newpm OK")


def listed():
    """Jack, Oct 15: listings posted through Printify (not `fleet etsy post`) never set the product's link, so the
    dashboard showed pet portraits as not live. A task finished with an Etsy listing as its evidence sets it."""
    h, muse, clock = new_hub("Neo")
    pj = h.add_project(h.add_product("Pets", brief="p"), "launch")
    t = h.add_task(pj, "Publish the pet listing", "engineer", "live", owner="Neo")
    h.tick(); h.tick()
    h.evidence_ok = lambda link: True
    h.task_done("Neo", t, "https://www.etsy.com/listing/4595880794/custom-pet-portrait-from-photo")
    assert [p["link"] for p in h.portfolio() if p["name"] == "Pets"] == ["https://www.etsy.com/listing/4595880794/custom-pet-portrait-from-photo"], h.portfolio()
    print("listed OK")


def tidy():
    """Jack, Oct 14: a newer line that replaces an older one must take its place, one ask per task, and a link to
    every product's listing so he can see what he's approving ad spend for."""
    h, muse, clock = new_hub("Neo", "Pam")
    pj = h.add_project(h.add_product("Hats", brief="hats", pm="Pam"), "launch")
    old = h.jack_add("Pam", "Open Printify, PrintKK accounts; add card", "no accounts", "https://printify.com")
    new = h.jack_add("Pam", "Add a card to Printify", "agents opened it", "https://printify.com/app/billing")
    h.jack_done("Pam", [old])
    assert [n["id"] for n in h.needs_jack()] == [new], f"tidy: the replaced line leaves Jack's list: {h.needs_jack()}"

    t = h.add_task(pj, "Imagegen fix", "engineer", "doc", owner="Neo")
    h.tick(); h.tick()
    try:
        h.task_for_jack("Neo", t, "Add a card to PrintKK", "orders can't ship")
        raise AssertionError("tidy: an agent's step for Jack without the sign-up or payment page is refused")
    except ValueError:
        pass
    h.task_for_jack("Neo", t, "Clear the model cache on the hub", "tool broken", "https://example.com/steps")
    h.task_wait("Neo", t, "jack", "Clear the model cache on the hub")
    asks = [r for r in h.needs_jack() if r["task"] == t]
    assert len(asks) == 1, f"tidy: waiting on Jack for a step already asked doesn't ask twice: {asks}"

    try:
        h.jack_add("Pam", "Approve the hats ad test")
        raise AssertionError("tidy: a line on Jack's list without a link is refused")
    except ValueError:
        pass

    h.manage("Pam", 'product set Hats link https://www.etsy.com/listing/123')
    assert [p["link"] for p in h.portfolio() if p["name"] == "Hats"] == ["https://www.etsy.com/listing/123"], "tidy: product shows its listing"
    try:
        h.manage("Pam", 'product set Hats link etsy.com/listing/123')
        raise AssertionError("tidy: a product link must be a web address")
    except ValueError:
        pass
    print("tidy OK")


{"said_not_raised": said_not_raised, "busy_ceo": busy_ceo, "actionable": actionable, "listed": listed, "newpm": newpm, "keys": keys, "pmwait": pmwait, "repeat": repeat, "tidy": tidy, "pm": pm, "steps": steps, "reply": reply, "tools": tools, "doc": doc, "show": show, "plain": plain, "since": since, "ui": ui}[sys.argv[1]]()
