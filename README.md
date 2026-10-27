# Microdex

Microdex is a compact Codex-style coding-agent runtime implemented with
Python, asyncio, and LangGraph. The repository now contains the actual
three-layer loop rather than only a sample/tools graph.

## The loop

    CLI or another client
      |
      | TurnInput Submission
      v
    MicrodexThread + SessionIo
      |
      v
    submission_loop                 session layer
      |
      v
    RegularTask                     task layer
      |
      v
    run_turn
      |
      v
    LangGraph                       agent layer
      sample -> tools -> drain input -> sample or END

One MicrodexThread is one conversation, not one operating-system thread. It
owns one Session. A Session runs one long-lived submission_loop and at most one
RegularTask at a time. Over the life of a conversation it can run many tasks
sequentially.

Multiple conversations work concurrently as asyncio tasks. The read_file and
rg calls from the same model response can run in parallel; state-changing
tools form ordering barriers.

## What happens to a prompt

1. The client submits TurnInput to SessionIo.
2. submission_loop starts a RegularTask when the Session is idle.
3. RegularTask invokes run_turn.
4. run_turn asks the model for the next response.
5. If the response contains tools, the complete batch executes. Each result is
   written to history with its original call id.
6. Input received while the task is active is merged before the next sample.
7. A response with no tools and no pending input reaches END.
8. The runtime emits turn_completed, turn_aborted, or error as EventMsg.

The CLI consumes those events. It does not call LangGraph directly.

## Offline debug walkthrough

Run the complete architecture without an API key or network request:

    microdex debug-loop

To stop after each architecture stage:

    microdex debug-loop --pause

The same entry point is also installed as:

    microdex-debug --pause

The walkthrough creates a temporary workspace and uses a gated scripted model.
It demonstrates ThreadManager creation, Submission routing, submission_loop,
RegularTask, steering through InputQueue, a parallel read/search batch,
apply_patch, exec_command, model follow-up, turn completion, and the final
checkpoint history. The temporary workspace is printed and removed at the end.
Pass --workspace with an empty directory to keep the generated files.

## Run

Create an environment and install the package:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .

Authenticate with xAI or provide XAI_API_KEY:

    microdex login
    microdex --cwd .

With no positional prompt, the process stays open on one conversation. A
single task can be run non-interactively:

    microdex "fix this test" --cwd .

Reuse checkpointed history by supplying the same id:

    microdex --thread my-thread --cwd .

The caller supplies the conversation id. ThreadManager tracks live
conversations in the process; SQLite restores LangGraph state for a reused id.
SQLite is not consulted to route every incoming prompt.

## Source layout

    src/microdex/
      runtime/
        protocol.py          operations in and events out
        session_io.py        submission and event queues
        input_queue.py       steering during an active task
        session.py           one live session
        submission_loop.py   session event loop
        regular_task.py      one user task
        thread.py            MicrodexThread handle
        thread_manager.py    concurrent conversation registry
      agent/
        turn.py              run_turn execution boundary
        graph.py             LangGraph topology
        state.py             serializable TurnState
        nodes/               model and tool-batch steps
      context/
        agents_md.py         layered project instructions
      tools/                 read, rg, apply_patch, exec_command
      persistence/
        checkpointer.py      SQLite graph checkpoint contexts

## Deliberate next slices

Approval, stronger sandboxing, context compaction, stop hooks, PTY sessions,
subagents, long-term memory, MCP, and computer use are extension points rather
than fake stubs. Their intended boundaries are documented in AGENTS.md.
