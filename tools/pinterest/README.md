# tools/pinterest — post pins to the fleet's Pinterest account from the hub machine

Pinterest blocks the agent VMs; this posts from the hub machine instead.

```
fleet tool run pinterest --check
fleet tool run pinterest --image <image url> --title "<title, max 100>" --description "<text, max 500>" --link <etsy listing url> --board "<board name>"
```

`--check` reports whether it's signed in and lists the boards (check.json, check.png). A post prints the live pin
URL and writes pin.json — that URL is the evidence for a Pinterest post task. On failure, error.png shows the page.

Images: a muse.ai file link or any public image URL; 1000x1500 (2:3) works best.

Sign-in lives in an Edge profile at `~/.fleet-pinterest/profile` of the tools account. When signed out it uses
`~/.fleet-pinterest/login.json` (`{"email": "...", "password": "..."}`), placed once by an operator.
Playwright installs itself on first run and drives the machine's Edge (no browser download).

Don't spam: one pin per listing per board per day at most, each with a fresh image or angle.
