# ADR-0001: One plugin, one package

## Context

gatekit ships an interview/mockup pipeline, a task and gate system, a job
runner with pluggable workers, and a set of hooks that enforce all of it.
Each of these could plausibly be its own plugin — separate marketplaces
entries, separate `plugin.json` files, separate version numbers — the way
a larger ecosystem of Claude Code plugins sometimes splits by concern.

Claude Code resolves `${CLAUDE_PLUGIN_ROOT}` per plugin, and cross-plugin
file paths do not exist: one plugin's hook script cannot reach into
another plugin's directory by a relative path, and one plugin's commands
cannot rely on another plugin's package being installed. Splitting gatekit
into multiple plugins would mean every cross-cutting piece — the ledger,
the verdict vocabulary, the hook I/O contract — either gets duplicated
across plugins or lives in a package none of them can import without a
brittle absolute-path assumption about sibling plugin installation.

## Decision

gatekit is exactly one plugin (`plugin/`) containing exactly one Python
package (`plugin/gatekit/`). Every command, skill, hook, and gate lives
under this single plugin. `.claude-plugin/marketplace.json` lists exactly
one entry, whose `source` is `./plugin`.

Internal organization (commands vs. skills vs. the kernel package vs.
spec-kit data) is expressed as directories within the one plugin, not as
separate installable units.

## Consequences

- `${CLAUDE_PLUGIN_ROOT}` reaches every script gatekit needs to run; no
  hook has to guess at another plugin's install path.
- A single `version` in `plugin.json` and a single `CHANGELOG.md` entry
  describe the whole system's state — there's no matrix of "which plugin
  version pairs with which other plugin version."
- The cost is size: `plugin/` is one large tree instead of several small
  ones. `docs/ARCHITECTURE.md` §1 exists specifically to keep that tree
  navigable, and `tools/gate_manifest.py` enforces that the manifests
  describing it stay accurate.
- If gatekit ever needs functionality that genuinely belongs to a
  different install lifecycle (for example, a companion plugin meant to
  be optional in a way `plugin/` itself is not), that would need its own
  ADR revisiting this decision rather than quietly growing a second
  `plugin.json` under the same repo.
