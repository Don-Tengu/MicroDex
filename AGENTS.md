# Microdex engineering contract

Microdex is a small, working reimplementation of the core Codex runtime in
Python and LangGraph. It is not an empty classroom scaffold. Implement the
behavior required by the current slice; do not leave core policy behind
NotImplementedError for the user to fill in.

The read-only reference repository is /Users/bartolomeoquaranto/Code/codex.
Read it to understand behavior, then write an independent Python
implementation here. Do not modify the reference repository.

Talk to the user in Simplified Chinese. Keep source code, comments, docstrings,
and repository documentation in English.

## Architecture

The runtime has three nested layers. Keep them separate.

1. Session layer: submission_loop
   - Long-lived asyncio loop for one conversation.
   - Receives TurnInput, Interrupt, and Shutdown through SessionIo.
   - Owns the active-task slot and steering queue.
2. Task layer: RegularTask
   - Owns one accepted user task.
   - Starts run_turn, forwards events, handles cancellation and failure, and
     closes the race between graph completion and late input.
3. Agent layer: run_turn
   - Executes the LangGraph model-tool loop until END.
   - Builds requests from history, samples the model, executes a complete tool
     batch, records results, merges pending input, and decides whether another
     sample is needed.

The live call path is:

    client
      -> MicrodexThread.start_turn
      -> SessionIo.submit
      -> submission_loop
      -> RegularTask.run
      -> run_turn
      -> LangGraph

The CLI is a client. It must never invoke graph.stream or graph.astream
directly.

## Object relationships

- ThreadManager is a live registry and lifecycle owner. It creates and closes
  MicrodexThread objects; it is not conversation memory.
- One MicrodexThread represents one chat/conversation. Despite its name, it
  is not an operating-system thread.
- One MicrodexThread owns one Session and one SessionIo.
- One Session owns one submission_loop and has at most one active RegularTask.
- One Session owns one ApprovalBroker for pending mutating-tool decisions.
- A Session may run many RegularTask instances over its lifetime, one after
  another.
- Multiple sessions are concurrent asyncio tasks on one event loop. Safe
  read-only tools from one model response may run in parallel workers.
- The caller chooses or restores the conversation id. ThreadManager answers
  whether that thread is live; the LangGraph checkpointer restores state for a
  reused id. Do not query SQLite merely to decide where every new prompt goes.

## Non-negotiable invariants

1. Every user prompt first becomes a Submission carrying TurnInput.
2. Every operation enters through SessionIo; every UI update leaves as
   EventMsg.
3. A Session has at most one active RegularTask.
4. Input arriving during an active task goes to InputQueue and is merged before
   the next model sample. Input racing with task completion must not be lost.
5. Interrupt and Shutdown belong to submission_loop, not to normal graph
   routing.
6. LangGraph state contains serializable conversation data only. asyncio
   Queue, Task, Lock, subprocess handles, and live clients stay in runtime.
7. All tool calls from one model response must finish before the next model
   request. Every result keeps the original tool call id. Result order remains
   model order even when safe tools run concurrently.
8. Tool failures become tool-result messages whenever the model can recover.
   They do not crash the session.
9. The SQLite checkpointer persists graph state. It is not SessionIo,
   ThreadManager, an event log, or long-term memory.
10. Project instructions are snapshotted when a Session is created. Discover
    AGENTS.override.md or AGENTS.md from project root down to cwd, preferring
    the override file at each level, and include the merged text in every model
    request.
11. `apply_patch` and `exec_command` wait for a matching ToolApprovalDecision
    through SessionIo before dispatch. Approval waiters stay in runtime state;
    interrupt and shutdown reject pending requests.
12. The TypeScript TUI is a client. It sends JSON-lines operations through
    `tui_bridge.py`; user input, interrupts, and approval decisions must still
    enter through MicrodexThread and SessionIo. The TUI may read checkpoint
    snapshots to build its resume picker and transcript.

## Code map

- src/microdex/runtime/protocol.py: Op, Submission, and EventMsg boundary.
- src/microdex/runtime/session_io.py: submission and event queues.
- src/microdex/runtime/approval.py: runtime-owned approval waiters.
- src/microdex/runtime/input_queue.py: active-turn steering input.
- src/microdex/runtime/session.py: runtime-owned state and active-task slot.
- src/microdex/runtime/submission_loop.py: long-lived session event loop.
- src/microdex/runtime/regular_task.py: one user task.
- src/microdex/runtime/thread.py: public MicrodexThread handle.
- src/microdex/runtime/thread_manager.py: live conversation registry.
- src/microdex/agent/turn.py: run_turn execution boundary.
- src/microdex/agent/graph.py: inner LangGraph topology.
- src/microdex/agent/nodes/: request, model outcome, and tool-batch nodes.
- src/microdex/context/agents_md.py: project-instruction discovery.
- src/microdex/debug_walkthrough.py: deterministic offline end-to-end trace.
- src/microdex/tools/: schemas, dispatch, path checks, and tool bodies.
- src/microdex/persistence/checkpointer.py: synchronous and asynchronous SQLite
  checkpoint contexts.
- src/microdex/persistence/session_index.py: resumable sessions and history
  loaded from LangGraph checkpoints.
- src/microdex/tui_bridge.py: JSON-lines adapter from the TypeScript UI to the
  existing session runtime.
- src/microdex/tui/: TypeScript screens, terminal input/rendering, and the
  runtime bridge client. `app.ts` coordinates the home screen, resume picker,
  transcript, composer, and approval overlay.

## Reference source map

- submission_loop:
  codex-rs/core/src/session/handlers.rs
- RegularTask:
  codex-rs/core/src/tasks/regular.rs
- run_turn and model-tool follow-up:
  codex-rs/core/src/session/turn.rs
- Session:
  codex-rs/core/src/session/session.rs and session/mod.rs
- CodexThread:
  codex-rs/core/src/codex_thread.rs
- ThreadManager:
  codex-rs/core/src/thread_manager.rs
- Op and EventMsg:
  codex-rs/protocol/src/protocol.rs
- tool registry and dispatch:
  codex-rs/core/src/tools/registry.rs and tools/router.rs
- project instructions:
  codex-rs/core/src/agents_md.rs

Use Codex names when semantics match. Types carrying the Codex product prefix
use Microdex instead, so CodexThread becomes MicrodexThread. Do not reuse a
Codex name for a different responsibility.

## LangGraph rules

- Nodes never call one another. They read TurnState and return only changed
  fields.
- history uses an append reducer, so a node returns only newly added messages.
- pending_calls and control flags replace their previous values.
- Prompt assembly is deterministic. The model does not decide how history,
  tool results, or project instructions are formatted.
- A model response containing several tool calls is one batch. The tools node
  is a barrier before the next sample.
- run_turn is the only runtime entry point to the compiled graph.

## Current scope and extension seams

The working core includes the submission queue, multi-session runtime,
steering, cancellation, event stream, project instructions, SQLite
checkpoints, xAI and OpenAI providers, per-call approval for mutating tools,
and read/search/patch/shell tools.

The following are later slices and must attach at the existing boundaries:

- stronger OS sandbox policy: around tool execution (mutating tools now require
  client approval before dispatch);
- context compaction: before model sampling;
- stop hooks: after a candidate final answer, before graph END;
- background PTY: behind the tool runtime;
- subagents: child MicrodexThread instances with separate histories;
- long-term memory: extracted outside run_turn and injected as stable context;
- MCP and computer use: additional tools, not new agent loops.

Do not fake a future feature with an empty module. Add it when it is requested,
and preserve the three-layer architecture.

## Working rules

- Python 3.11 or newer.
- Prefer small typed modules with one responsibility.
- Do not add or run tests unless the user asks. When behavior changes, call out
  stale existing tests rather than silently preserving a false scaffold
  assertion.
- Do not add a second framework around LangGraph.
- Do not put UI-specific printing in runtime or graph modules.
- Do not let a client bypass SessionIo.
- Do not store runtime objects in TurnState.
- Preserve unrelated user changes.
