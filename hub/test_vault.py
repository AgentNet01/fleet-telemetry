"""Vault: an agent reads only its own, its product's and fleet secrets; every read is logged.

    python3 test_vault.py
"""
import os
import tempfile

import hub
from test_hub import Clock, FakeMuse


def main():
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    h.add_agent("Nia", "muse")
    h.place("Nia", "Shop", "developer")

    h.secret_put("etsy-key", "ETSY-SECRET-1", "product:Shop", by="jack")
    h.secret_put("nia-login", "NIA-PW", "agent:Nia", by="jack")
    h.secret_put("openai", "OPENAI-KEY", "fleet", by="jack")
    h.secret_put("rival-key", "NOPE", "product:Rival", by="jack")

    assert h.secret_get("etsy-key", "Nia") == "ETSY-SECRET-1", "reads its product's secret"
    assert h.secret_get("nia-login", "Nia") == "NIA-PW", "reads its own secret"
    assert h.secret_get("openai", "Nia") == "OPENAI-KEY", "reads a fleet secret"

    assert h.secrets_for("Nia") == ["etsy-key", "nia-login", "openai"], "lists only what it may read"
    can = h.status("Nia")["can"]
    assert "nia-login" in can and "rival-key" not in can and "NIA-PW" not in can, "status names its secrets, never values"

    try:
        h.secret_get("rival-key", "Nia")
        assert False, "a secret outside scope must be refused"
    except PermissionError:
        pass
    assert h.secret_get("missing", "Nia") is None, "an unknown secret is just empty"

    reads = h.secret_reads()
    assert sorted(r["secret"] for r in reads) == ["etsy-key", "nia-login", "openai"], reads
    assert all(r["agent"] == "Nia" for r in reads), reads
    assert all("value" not in r and "NIA-PW" not in str(r) for r in reads), "the log never holds values"
    print("vault OK")


if __name__ == "__main__":
    main()
