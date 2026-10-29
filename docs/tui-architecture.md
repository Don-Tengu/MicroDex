# Microdex TUI MVP

## Current runtime and UX gap

Microdex already has a Python runtime with a `MicrodexThread` per conversation,
`SessionIo` as the operation boundary, an event stream for model/tool updates,
SQLite LangGraph checkpoints, per-call tool approvals, steering, and interrupt.
The previous CLI was a line-oriented client. It could run one conversation but
did not provide a launch menu, a directory-scoped session picker, or a
conversation transcript when restoring a checkpoint.

The TypeScript UI adds those client surfaces while leaving the Python runtime
and model/tool execution in place.

## User flow

- `microdex` opens a dark full-screen launcher with Resume Session, Changelog,
  and Quit. Typing a task and pressing Enter starts a new session in the current
  directory. New Worktree is temporarily hidden from the TUI.
- Resume Session shows a full-width, one-line list of checkpointed threads whose
  saved working directory exactly matches the current directory. The user can
  hover over or click a row, see its saved transcript, and continue the thread.
- Changelog displays the latest repository commits.
- Chat shows restored history, streamed assistant text, tool activity, a
  composer, steering/interrupt state, and an approval overlay for shell and
  patch tools.

## File boundaries

The organization follows the small set of responsibilities visible in Codex's
`codex-rs/tui/src/app.rs`, `resume_picker.rs`, `chatwidget.rs`,
`bottom_pane/chat_composer`, and `tui.rs`:

| Microdex file | Responsibility | Codex reference |
| --- | --- | --- |
| `src/microdex/tui/main.ts` | Parse UI launch arguments and start the app | `codex-rs/cli/src/main.rs` entry to `codex_tui::run_main` |
| `src/microdex/tui/app.ts` | Screen state, event dispatch, and UI transitions | `codex-rs/tui/src/app.rs` |
| `src/microdex/tui/render.ts` | Launcher, resume picker, transcript, composer, approval view | `resume_picker.rs`, `chatwidget.rs`, `bottom_pane` |
| `src/microdex/tui/terminal.ts` | Raw key input and terminal lifecycle | `codex-rs/tui/src/tui.rs` and `custom_terminal/` |
| `src/microdex/tui/bridge.ts` | JSON-lines client to the Python process | App-server client boundary |
| `src/microdex/tui_bridge.py` | Translate UI operations into runtime calls and events | Thin CLI/client adapter |
| `src/microdex/persistence/session_index.py` | Discover and restore checkpointed transcript data | `resume_picker` history query boundary |

The TUI never calls LangGraph to run a turn. Text, interrupt, and approval
decisions travel through `MicrodexThread` and `SessionIo`. The bridge reads
checkpoint snapshots only to populate the picker and hydrate the transcript.
The stdin/stdout JSON-lines stream is reserved for protocol messages; Python
diagnostics go to stderr.

## Runtime and distribution

The Python package contains the TypeScript sources as package data. Node.js
22.6 or newer runs the erasable TypeScript directly, so the first version does
not need npm dependencies or a separate JS build artifact. `microdex --plain`
keeps the line-oriented client available. Non-TTY invocations continue to use
the existing Python CLI, which preserves scripting behavior.

This is a small MVP, not parity with the full Codex TUI. It uses keyboard
navigation, hover and click on the launcher menu, normalized mouse-wheel
transcript scrolling with frame-coalesced redraws, a proportional draggable
scrollbar with a narrow track inset from the terminal edge and clickable gutter,
a focused one-line composer,
a single active conversation view, exact-directory session filtering, and
recent Git commits for the Changelog screen. It does not yet include multiline
editing, session deletion/forking, or session search.
