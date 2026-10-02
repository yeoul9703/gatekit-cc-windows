# Reading a Figma file

Read this only when the input is a Figma URL. Nothing else in
`/gatekit-mockup` or `/gatekit-design` needs Figma: screenshots, HTML files,
a live site, a preset and a pattern file all work without it.

## What it needs

The Figma MCP server, connected to the coding agent in use. Its four tools:
`get_metadata`, `get_design_context`, `get_variable_defs`, `get_screenshot`.
The skill does not pre-approve them; the agent's own permission mode decides
whether a call asks first.

## Order

1. `get_metadata` — the frame tree. One screen row per frame, with the frame
   name as evidence.
2. `get_design_context` — structure and component names.
3. `get_variable_defs` — the tokens. Keep the design system's own spelling.
4. `get_screenshot` — a visual check of what the first three returned, never
   a source of values on its own.

Every extracted item carries the frame name or variable name it came from.

## When the tools are missing

Say so in one sentence, ask for an export or screenshots, and stop reading
Figma. **Never guess a design from a URL.** Carry on with whatever files the
user then provides, through the Screenshots or HTML branch.
