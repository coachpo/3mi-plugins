# Host adapters

Read only the section for the actual host. Discover available capabilities and
current schemas before using them; names below are examples, not guaranteed
dependencies. Do not install another plugin merely to obtain a desktop tool.

## Codex Desktop

Prefer an available subagent for bounded work inside the current task when a new
visible chat was not explicitly requested. `create_thread` requires a user
request for a separate chat; automatic skill selection is not that request. A
user request for worktree chats permits that route if exposed by the host. Get
project IDs from its project listing and use the requested starting state;
verify the resulting checkout rather than assuming it includes local changes.
Reuse suitable chats/worktrees within their ownership and authorization rules.

Creation may be asynchronous. Save the operation ID or client-side temporary ID,
wait using the corresponding status capability, and obtain the real thread ID,
host ID, and workspace before messaging, waiting, or assigning ready work. Never
pass a temporary client ID to tools requiring a thread ID. Failed registration
may leave a checkout: inspect and recover/attach it through host tools before
creating another. Record actual state if recovery fails.

For an explicitly requested new managed worktree, prefer host creation; otherwise
inspect attached worktrees and reuse a suitable one. The current chat may stay
in its original directory: execute against the returned workspace. Creation may
start from a remote default branch and omit uncommitted changes; specify the
intended supported ref/state and explicitly deliver additional materials. Verify
the trusted baseline in the checkout.

Before messaging another chat, confirm current human authorization under the
tool's rule; another executor's request alone is not authorization to reply.
Send self-contained assignments with accessible paths or transferred content.
Use bounded wait/status tools with returned cursors rather than repeatedly
reading full histories. Preserve explicit model/effort and tool limitations.

For managed cleanup, inspect attached artifact identities and pass the exact
identity accepted by the archive tool. Recoverable archival may save uncommitted
and non-ignored files but exclude ignored files; preserve those separately first.
Respect primary, pinned, shared, and other archive restrictions. Do not substitute
forced deletion when archival fails. Archive execution chats separately and
inspect remaining branches before deleting authorized task branches. Chat
archival does not remove its worktree; worktree archival does not archive its
chat. Subagents may have only a lifecycle/stop mechanism and no sidebar chat:
report that distinction accurately.

## Codex CLI and Claude Code

Use an available subagent, headless executor, or reusable session. Claude Code
may supply `steward-executor`; Codex may supply delegation or configured execution
profiles. Keep contracts and the unchanged executor protocol accessible so
execution does not depend on a plugin-specific agent. Use configured tier defaults
unless the user specifies model/effort. Verify support through current host
configuration/help; never silently fall back from an explicit setting.

When isolation is needed, use ordinary Git worktrees and task branches from the
same verified baseline, preserving required local source changes separately.
Use project/host branch conventions. Inspect `git status`, `git worktree list`,
and branch state before resuming or creating resources. Deliver ignored
plan/evidence/environment files explicitly and keep concurrent result writes
separate. A headless process may not see its parent's conversation, environment,
or another checkout's dependencies.

Record real session/process IDs, cwd/worktree, branch, baseline, result location,
and next action. Reuse sessions after checking their current task and state.
No API is implied for process resumption or chat archival: use available supported
mechanisms, or retain records and state the limitation.

Before authorized Git cleanup, verify accepted changes are integrated and save
recovery materials, including ignored files and evidence outside the checkout.
Use non-forcing worktree removal; dirty or unintegrated work stays recoverable.
Verify task-branch reachability before deletion: cherry-picked results may have
different commit identities, so inspect the accepted diff and integration record
rather than assuming ancestry proves inclusion. Do not use forced deletion to
resolve uncertain integration or recovery. Delete a non-ancestral task branch
only with applicable explicit deletion authority and preserved results. Archive
actual executor sessions separately if supported; otherwise report session
archival as unavailable, not complete.
