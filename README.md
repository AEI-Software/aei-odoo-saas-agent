# aei-odoo-saas-agent

Addon delivery repo for the **aei_assistant** feature (tenant AI agent in Discuss)
of [aei-odoo-saas](https://github.com/AEI-Software/aei-odoo-saas).

Cloned into each opted-in tenant's pod by the standard `clone-addons` init
container (`addons.json` / `saas.instance.addons_repos_json`) — **not** baked
into the tenant Docker image (`docker/odoo/Dockerfile` is deliberately kept
thin; addons are always injected at pod-start time, same as every other
tenant addon). See `/home/kali/.claude/plans/parsed-wobbling-dusk.md` for the
full design and why this repo exists rather than pointing tenants at the main
monorepo directly (that would also expose admin-only addons like
`odoo_k8s_saas`).

## Contents

- `muk_mcp/`, `muk_web_utils/` — mirrored from `aei-odoo-saas/external_addons/`
  (MuK MCP Server — third-party, per-user API keys, Odoo ACL enforcement).
- `saas_ai_agent/` — AEI's own addon: bot partner reachable via Discuss,
  postcommit hook to the tenant's `agent` pod, per-message ephemeral MCP
  keys, Layer-1 ORM guardrails (no app installs, no user creation via the
  agent).

## Syncing

Currently synced manually from the main monorepo. `saas_ai_agent/` is
developed in `aei-odoo-saas` proper; changes need to be copied here and
version-bumped before tenants relying on this repo pick them up.

## Branching

One branch per Odoo version, no `main` — see the AEI-Software org's repo
naming standard. Currently: `18.0`.
