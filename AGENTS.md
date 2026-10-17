# Repository instructions

## Interaction and instruction portability

These owner instructions apply to every coding agent, regardless of provider or interface. Preserve the project's safety and approval rules.

- Keep `AGENTS.md` as the canonical instruction file. `CLAUDE.md` is only a compatibility symlink to `AGENTS.md`; never keep separate rules there.
- Keep shared policies, skills, and workflows agent agnostic. Provider-specific launchers and configuration are adapters, not separate sources of behavioral rules. Do not require a named provider for ordinary work or review.
- Ask one question at a time, using the existing question-count convention when applicable.
- Put every answer option in its own paragraph, beginning with a bold letter label such as **A.**, **B.**, **C.**, or **D.**
- Leave a blank line between options. Never combine several options into one paragraph or put the question in a code block.
- Mark one recommended option when a recommendation is useful. Use short, plain explanations.

These instructions supersede older option-formatting examples and agent-specific wording. Read the shared `one-question-at-a-time` skill when available.


Read the repository README and applicable project documentation before changing files. Preserve existing project constraints and unrelated work.

## Shared port coordination

Before starting any development or test listener on Solomon, read
`/home/ubuntu/work/sys-admin/PORTS.md` and use the global `port-tool`.
Check and reserve all required ports before starting, using a unique task owner.
Reservations belong in that central Markdown register, never a project copy.
After stopping your own listener, release its ports with the same owner.
Never take another owner's reservation or stop their service to free a port.
Keep current server-stop approval requirements. Record retained reservations
in the session handoff. This rule applies to every agent and worktree.

Odoo checkouts get this automatically: `odoo-run` reserves the server port under
`odoo-<database>` and refuses to start when another owner holds it, and `odoo-test`
reserves each test pair under `odoo-test-<database>` and releases it on exit. Reserve by
hand only for other listeners. Shared-port handover is stop, release by the previous
owner, start; `PORTS.md` describes it. Browser checks against a non-production remote
target use `odoo-browser --target NAME`; production targets are refused.
