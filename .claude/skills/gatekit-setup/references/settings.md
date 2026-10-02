# The PowerShell settings in `.claude/settings.json`

Read this when the `S12-settings` item of `/gatekit-setup` is `fail`. Nothing
is installed for this item; it is fixed by adding a key to one file, and only
after the user says yes in the chat.

## What must be there

`.claude/settings.json` must carry both values:

| Key | Value | What it does |
|---|---|---|
| `env.CLAUDE_CODE_USE_POWERSHELL_TOOL` | `"1"` | turns on Claude Code's PowerShell tool |
| `defaultShell` | `"powershell"` | the input-box `!` commands run in PowerShell 7 |

As JSON:

```
{
  "env": { "CLAUDE_CODE_USE_POWERSHELL_TOOL": "1" },
  "defaultShell": "powershell"
}
```

## Procedure

1. The item's `detail` says which key is missing. Tell the user which one, in
   plain words, and what it is for.
2. Ask in the chat whether to add it. This is its own question: a yes to an
   install does not cover it. Wait for the answer.
3. On yes, read `.claude/settings.json`, then add **only the missing key**
   with the Edit tool:
   - `env` already exists: add the one entry inside it and keep every other
     entry.
   - a key is present with another value: show the current value and ask
     before changing it.
   - never rewrite the whole file, and never touch `hooks` or `permissions`.
4. If the file is not valid JSON, do not repair it by guessing. Show the user
   the parse problem and stop.
5. Run the check from Step 1 again; `S12-settings` should now be `ok`.
6. The setting takes effect in a new session. Tell the user to close Claude
   Code completely (the desktop app, the VS Code window, or the terminal it
   runs in) and open it again. In Korean: "Claude Code(데스크톱 앱, VS Code 창,
   또는 실행 중인 터미널)를 완전히 닫고 다시 여세요".

On no, leave the file as it is and say that the PowerShell tool stays off
until the key is added.
