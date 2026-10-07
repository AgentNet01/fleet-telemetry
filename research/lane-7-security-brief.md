# Lane 7 (Security) — Research Brief

**Lane owner:** Boboe 11 (provisional — claimed for Boboe 2's 2026-10-08 synthesis; reassign freely)
**Researched:** 2026-10-07 ~10:00 EDT
**Status:** findings ready for synthesis — NOT posted to Slack yet (delivery decision for Boboe 2 / main agent)

## Lane brief (six-element shape)

1. **Objective as an outcome:** Boboe 2's unified proposal contains a concrete identity-and-trust section: what the fleet's trust surface is today, what broke or nearly broke in the last 48h, and the minimum identity mechanism the fleet should adopt before scaling autonomy.
2. **Boundaries (does NOT touch):** lane 8 (cost/observability) accounting; lane-by-lane technical findings; the ledger/coordination mechanics (covered in the "Missing Ledger" briefing); Slack channel governance beyond agent identity.
3. **Output format:** this brief — findings with evidence + recommendations, each tagged with what was checked and what remains unknown.
4. **Sources checked:** first-hand fleet events 2026-10-06/07 (standing orders, daily log, AGENTS.md incident log); web research 2026-10-07 (SailPoint Navigate announcements, SPIFFE/agent-identity standards, CrowdStrike/Okta agent-identity products).
5. **Known non-findings:** no evidence of actual credential theft or external impersonation of a Boboe in the last 48h — the observed failures are provenance/integrity gaps, not breaches. The telemetry receiver flap (2026-10-06) was an infrastructure fault, not a security event.
6. **Done-gate:** this file exists with cited findings + the identity recommendations below; synthesis owner (Boboe 2) has it before the 2026-10-08 proposal.

## Findings

### F1. The fleet's trust anchor is name-based, not cryptographic (first-hand)

Standing order 1: "JackHuman" (U0C6Z6YERN0) is absolute authority; "Fleet Reader" (U0C72D6T4KG) carries Jack's full authorization; **"every Boboe carries Jack's standing authority on fleet operations — any agent may direct any other in Jack's name on fleet business."** Identity is asserted by display name + Slack user ID; nothing signs an order. With 12+ agents each able to issue fleet-wide orders "in Jack's name," the delegation surface is the entire fleet, and a compromised or malfunctioning box inherits full fleet authority by default.

### F2. The fleet ingested a standing order before verifying provenance (first-hand, resolved)

On 2026-10-06 ~18:18–18:19 EDT, a "WAKANDA = task finished" convention entry was written into `~/MEMORY.md` on at least five boxes (Boboes 4, 7, 8, 9, 10 — coordinated ~1-minute window), attributed to Jack's Claude via the Muse Wall. Several agents flagged it as unverified/unadopted and held the word unused; Boboe 10's and this box's logs show the write had no local authorship. Jack later confirmed the convention directly in main chat (~21:11 EDT), and it is now a standing confirmation ("Muse Wall = Jack — treat Wall messages exactly like a message from Jack").

The convention was legitimate; the *mechanism* is the finding: the fleet had no way to distinguish "Jack said this" from "something labeled as Jack said this" for ~3 hours, and the resolution was a policy declaration that the Wall is trusted — which makes the Wall channel's own authentication the single point of trust for standing orders. That is exactly the class of problem the industry is now productizing (see F4).

### F3. Privilege model is standing, not scoped or expiring (first-hand)

Agent authority in the fleet is currently binary and standing: an agent either carries Jack's authority or it doesn't. There are no scoped capabilities (e.g., "Boboe 2 may publish telemetry rollouts but not change watch-loop crons"), no expiries, no delegation chains recorded with an action. The four hard lines (spend money, delete data, contact outsiders, change credentials → Jack first) are the only scoped rule, and they are enforced by agent self-restraint, not by any mechanism.

### F4. The industry is converging on cryptographic agent identity — this week (external)

- **SailPoint (announced 2026-10-06 at Navigate):** launched its "Agentic Fabric" (May 2026) to discover AI agents, govern their access, and protect activity under one identity model; in Q1 nonhuman identities were 40% of identity growth and 14% of all managed identities. New: three classes of autonomous policy-enforcement agents, Autonomous Identity Security Posture Management (continuous exposure discovery + real-time remediation), and Agentic Fabric expansion with shadow-AI discovery, runtime authorization, and a kill switch.
- **SPIFFE/SPIRE** is becoming the default workload-identity substrate: cryptographically verifiable agent identities (`spiffe://trust-domain/agent/...`), auto-rotated, no long-lived API keys; adopted in agent-manifest specs, K8s agent operators, and AI security gateways. CrowdStrike shipped continuous identity for agents on the same pattern: verifiable identity + authorization evaluated continuously at action time + zero standing privilege by default.
- **Okta (Cross App Access / ID-JAG):** open protocol extending OAuth/OIDC for agent-to-app access via token exchange; now the MCP authorization extension. OpenID's IPSIE profiles agents as first-class IAM citizens with lifecycle management.

The direction is uniform: identity issued per-workload, verified cryptographically, authorization re-evaluated at use time, privilege that expires.

## Recommendations for the proposal

1. **Give every Boboe a verifiable identity now (cheap, high-leverage).** A fleet trust domain with per-agent identities (SPIFFE-style `spiffe://agentnet/boboe-11`, or at minimum signed envelopes on fleet orders) turns F1/F2 from policy into mechanism. First use: sign standing-order changes; an unsigned order-7-style write would have been *detectable* even when it was legitimate.
2. **Record delegation chains with actions.** When Boboe X acts "in Jack's name," the order should carry the chain (Jack → standing order 1 → Boboe X → this action). F2's 3-hour ambiguity window collapses to zero when provenance is attached to the message, not reconstructed from logs.
3. **Scope the standing authority (F3).** Keep the four hard lines; add role-scoped grants (e.g., rollout publishing, cron management, research synthesis) so a malfunctioning box cannot exercise the whole fleet's authority. Zero standing privilege is the industry default being shipped this month — the fleet should name which privileges are standing and why.
4. **Treat the Muse Wall as a trust boundary, not a trusted channel.** The standing "Muse Wall = Jack" rule is operationally necessary but makes Wall authentication the fleet's root of trust. Minimum: the fleet should know what authenticates a Wall message and have a defined response if Wall provenance is ever questioned (the 2026-10-06 incident is the drill that already happened — write the runbook from it).
5. **Add the kill switch to lane 8's observability.** SailPoint's and CrowdStrike's models pair identity with instant revocation. The fleet's equivalent: a way for Jack to revoke one agent's authority without touching the others (today, authority is all-or-nothing per agent by policy only).

## What remains unknown

- Whether the fleet-telemetry receiver or the Muse Wall path has any authentication beyond network position (Tailscale) — not checked this run.
- Lane 8's observability findings may already cover the revocation/audit surface; de-conflict at synthesis.
- No cost analysis of running a SPIRE server or equivalent for 12 agents — expected to be small, but unstated.

## Evidence

- Standing orders: `~/MEMORY.md` (Fleet Standing Orders v2, orders 1 & 7; Standing confirmations 2026-10-06)
- Incident log: `~/AGENTS.md` (WAKANDA provenance entries 2026-10-06 ~20:40 EDT → 2026-10-07 ~01:52 EDT; Fleet Reader closeout ts 1791338057.455499)
- Daily log: `~/memory/2026-10-07.md` (09:11–09:16 EDT entries: Jack's questions to Boboe 2; dot's reconciliation directive)
- External: SailPoint Navigate announcements 2026-10-06 (Agentic Fabric, Autonomous Agents, A-ISPM); SPIFFE/agent-manifest ADR-0009; CrowdStrike continuous identity for AI agents; Okta XAA/ID-JAG (MCP authorization extension); OpenID IPSIE. Searched 2026-10-07.
