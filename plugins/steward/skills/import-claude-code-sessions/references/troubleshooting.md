# Troubleshooting Claude Code imports

Load this reference only after discovery, import, or verification fails. Recheck the current official behavior at https://learn.chatgpt.com/docs/import before diagnosing from memory.

## A native import surface is unavailable

Open the current official import documentation and inspect the visible native
desktop or independent local CLI surface. Treat those current sources as the
authority for menu placement, command availability, session restrictions, and
supported routes; do not diagnose from a remembered path or limit.

If one native route is unavailable, check the supported import history when available and the likely target before using the other route. If neither route is available, stop and report the exact missing surface or user action.

Do not work around an unavailable native importer with database writes, rollout edits, transcript conversion, a substituted home directory, or a synthetic source tree.

## The requested chat is not offered

Check only facts needed to identify the requested item:

1. Confirm the source is Claude Code; standard Claude Chat data is unsupported.
2. Confirm the requested chat is among the work currently shown by the native selector; use the official documentation for any current discovery window or item limit.
3. Narrow the native selection by the project and chat title shown to the user.

If the official importer still does not offer the chat, stop. Report the unsupported or unavailable source and do not bypass the importer's eligibility or selection limits.

## The import is incomplete

Treat the result as incomplete when the importer reports a failure or the imported target cannot be opened with the expected history. Capture only the result, selected item identity, and target identity that the supported surface exposes; do not inspect or modify internal Codex storage.

After an interruption, inspect the supported import history when available and open the likely target before retrying. Do not enable desktop automatic updates unless the user explicitly requested ongoing synchronization. If an existing or partial result cannot be distinguished safely, stop before creating another copy.

If the importer flags additional setup after the chat target is verified, report the chat as imported with setup pending. Review only the items it flags, such as tool permissions, MCP authentication or transport settings, hooks, plugins or marketplaces, and prompts that contain arguments, shell interpolation, or file-path placeholders. Authentication and connection changes remain user actions unless separately authorized.

## A possible duplicate exists

Open the likely imported target and compare its visible project, title, and history with the requested Claude Code work. Return the existing target when it is the same work. Import another copy only after the user explicitly requests a duplicate.

## Verification is unavailable

Do not infer success from the importer status alone. Report which target or history check could not be performed and the smallest action needed to open the imported target. Never expose message bodies while reporting verification evidence.
