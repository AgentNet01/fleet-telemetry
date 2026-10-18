"""Social posts only count once live, and drafts can't pile up unposted (Jack, Oct 18).

    python3 test_social.py
"""
import hub
from test_company import new_hub


def held(h, prj, title):
    t = h.add_task(prj, title, role="marketer", done_def="x")
    h._set("tasks", t, owner="Ada", status="working")
    return t


def main():
    h, muse, clock = new_hub()
    pid = h.add_product("Hats")
    prj = h.add_project(pid, "launch")
    h.add_agent("Ada", "muse")

    post = held(h, prj, "Hats Pinterest batch 60")
    try:
        h.task_done("Ada", post, "https://gist.github.com/x/drafts")
        raise AssertionError("a post task took a gist")
    except ValueError as e:
        assert "pinterest.com" in str(e), e
    h.task_done("Ada", post, "https://www.pinterest.com/pin/123/")
    assert h.task(post)["status"] == "verifying"

    h.task_done("Ada", held(h, prj, "Hats TikTok concepts batch 1"), "https://gist.github.com/x/c1")   # a draft may be a gist
    h.task_done("Ada", held(h, prj, "Verify Instagram hats batch 2"), "https://gist.github.com/x/v")

    for i in range(2, hub.DRAFTS_UNPOSTED + 1):
        h.task_done("Ada", held(h, prj, f"Hats TikTok concepts batch {i}"), f"https://gist.github.com/x/c{i}")
    try:
        h.add_task(prj, "Hats TikTok concepts batch 99", role="marketer", done_def="x")
        raise AssertionError("a 7th unposted TikTok draft was accepted")
    except ValueError as e:
        assert "Post those first" in str(e), e
    h.add_task(prj, "Hats Pinterest concepts batch 61", role="marketer", done_def="x")   # Pinterest was posted
    h.add_task(prj, "Post hats TikTok batch 1", role="marketer", done_def="x")            # posting is always allowed

    h.task_done("Ada", held(h, prj, "Post hats TikTok batch 2"), "https://www.tiktok.com/@shop/video/9")
    h.add_task(prj, "Hats TikTok concepts batch 100", role="marketer", done_def="x")      # a live post clears it
    print("ok social")


if __name__ == "__main__":
    main()
