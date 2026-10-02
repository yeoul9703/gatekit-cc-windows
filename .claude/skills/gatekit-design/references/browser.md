# Reading a client-rendered site with a browser tool

Read this only when `/gatekit-design` got a client-rendered shell back from
`WebFetch`: little more than a script tag and an empty root element. A site
that fetches as real HTML never needs it.

## Which tool

Use the browser the host agent already provides. Do not install one.

| Host | Browser tool | Tool names |
|---|---|---|
| Claude Code CLI | the Claude in Chrome extension, when the user has it | `mcp__claude-in-chrome__*` (`tabs_context_mcp`, `tabs_create_mcp`, `navigate`, `get_page_text`, `computer`, `tabs_close_mcp`) |
| Claude desktop app | its built-in browser pane | `mcp__Claude_Browser__*` (`navigate`, `get_page_text`, `computer`, `tabs_close`) |
| Codex | not measured yet | whatever browser tool the host lists |

If the host lists none of these, go to "No browser tool".

## Steps

1. Open the URL in a new tab; do not take over a tab the user has open.
2. `get_page_text` for the rendered content.
3. A screenshot (`computer`, screenshot action) for what it looks like.
4. Save every capture under `spec/design/` and cite the saved file, never
   the URL, as evidence. A screenshot over 1 MB (CI's repo-wide limit) must
   be downsized or refused, never committed oversized.
5. Close the tab you opened.

## No browser tool

Say so in one sentence and ask the user for local captures (saved HTML,
screenshots) instead of guessing from the URL. This is a normal outcome, not
a failure: the rest of the design step works from captures.
