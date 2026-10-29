import { RuntimeBridge } from "./bridge.ts";
import type { BridgeMessage, KeyPress, RuntimeEvent, SavedSession } from "./protocol.ts";
import {
  historyToTranscript,
  invalidateChatLayout,
  chatScrollAtThumbTop,
  chatScrollMetrics,
  chatScrollLimit,
  homeMenuIndexAt,
  resumeSessionIndexAt,
  renderApproval,
  renderChangelog,
  renderChat,
  renderHome,
  renderResume,
  type TranscriptEntry,
} from "./render.ts";
import { Terminal, type MouseEvent } from "./terminal.ts";
import { WheelNormalizer } from "./scroll.ts";

type Page = "home" | "resume" | "changelog" | "chat" | "loading";

export type TuiOptions = {
  cwd: string;
  checkpoint: string;
  provider: string;
  model?: string;
};

type Approval = {
  callId: string;
  toolName: string;
  cwd: string;
  details: string;
  scroll: number;
};

export class TuiApp {
  private readonly terminal = new Terminal();
  private readonly bridge: RuntimeBridge;
  private page: Page = "home";
  private cwd: string;
  private provider: string;
  private model: string;
  private version = "";
  private menuIndex = 0;
  private draft = "";
  private sessions: SavedSession[] = [];
  private selectedSession = 0;
  private threadId = "";
  private title = "New session";
  private entries: TranscriptEntry[] = [];
  private busy = false;
  private streamOpen = false;
  private chatScroll = 0;
  private readonly wheelNormalizer = new WheelNormalizer();
  private wheelFrameTimer: ReturnType<typeof setTimeout> | undefined;
  private pendingWheelDelta = 0;
  private pendingWheelPage: "chat" | "resume" | undefined;
  private scrollbarDragging = false;
  private scrollbarGrabOffset = 0;
  private approval: Approval | undefined;
  private initialPrompt: string | undefined;
  private status = "";
  private changelog: string[] = [];
  private closing = false;
  private shutdownTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(options: TuiOptions) {
    this.cwd = options.cwd;
    this.provider = options.provider;
    this.model = options.model || "";
    this.bridge = new RuntimeBridge({
      cwd: options.cwd,
      checkpoint: options.checkpoint,
      provider: options.provider,
      model: options.model,
      onMessage: (message) => this.onBridgeMessage(message),
      onExit: (code) => this.onBridgeExit(code),
    });
  }

  start(): void {
    this.terminal.setRender(() => this.render());
    try {
      this.terminal.start(
        (text, key) => this.onKey(text, key),
        (event) => this.onMouse(event),
      );
      this.bridge.start();
    } catch (error) {
      this.terminal.restore();
      throw error;
    }
    this.render();
  }

  private onBridgeMessage(message: BridgeMessage): void {
    if (this.closing) return;
    switch (message.type) {
      case "ready":
        this.cwd = message.cwd;
        this.provider = message.provider;
        this.model = message.model;
        this.version = message.version;
        break;
      case "sessions_loaded":
        this.sessions = message.sessions;
        this.cwd = message.cwd;
        this.selectedSession = Math.min(this.selectedSession, Math.max(0, this.sessions.length - 1));
        if (this.page === "resume") this.status = "";
        break;
      case "session_loaded":
        this.threadId = message.session.thread_id;
        this.cwd = message.session.cwd || this.cwd;
        this.title = message.title;
        this.entries = historyToTranscript(message.session.history || []);
        this.page = "chat";
        this.chatScroll = 0;
        this.busy = false;
        this.streamOpen = false;
        this.status = message.session.history.length ? "Session resumed" : "New session";
        if (this.initialPrompt) {
          const prompt = this.initialPrompt;
          this.initialPrompt = undefined;
          this.submit(prompt);
        }
        break;
      case "event":
        this.onRuntimeEvent(message.event);
        break;
      case "changelog_loaded":
        this.changelog = message.lines;
        this.page = "changelog";
        this.status = "";
        break;
      case "bridge_error":
        this.status = message.message;
        if (this.page === "loading") this.page = "home";
        break;
      case "submitted":
        break;
    }
    this.render();
  }

  private onRuntimeEvent(event: RuntimeEvent): void {
    let transcriptChanged = false;
    switch (event.kind) {
      case "turn_started":
        this.busy = true;
        this.streamOpen = false;
        this.status = "Working";
        break;
      case "agent_message_content_delta":
        if (!this.streamOpen) {
          this.entries.push({ role: "assistant", text: event.text || "" });
          this.streamOpen = true;
          transcriptChanged = true;
        } else {
          const last = this.entries[this.entries.length - 1];
          if (last?.role === "assistant") last.text += event.text || "";
          else {
            this.entries.push({ role: "assistant", text: event.text || "" });
          }
          transcriptChanged = true;
        }
        this.chatScroll = 0;
        break;
      case "tool_start":
        this.streamOpen = false;
        this.entries.push({ role: "tool", text: `Running ${event.tool_name || "tool"}…` });
        transcriptChanged = true;
        this.status = `Running ${event.tool_name || "tool"}`;
        this.chatScroll = 0;
        break;
      case "tool_end":
        this.streamOpen = false;
        this.entries.push({
          role: "tool",
          text: `${event.tool_name || "Tool"} ${event.ok ? "completed" : "failed"}`,
        });
        transcriptChanged = true;
        this.status = event.ok ? "Tool completed" : "Tool failed";
        this.chatScroll = 0;
        break;
      case "tool_approval_requested":
        this.approval = {
          callId: event.tool_call_id || "",
          toolName: event.tool_name || "tool",
          cwd: event.cwd || this.cwd,
          details: this.approvalDetails(event),
          scroll: 0,
        };
        this.status = "Tool approval required";
        break;
      case "input_queued":
        this.status = "Instruction queued for this turn";
        break;
      case "turn_completed":
        this.busy = false;
        this.streamOpen = false;
        this.status = "Ready";
        break;
      case "turn_aborted":
        this.busy = false;
        this.streamOpen = false;
        this.status = `Turn interrupted${event.reason ? `: ${event.reason}` : ""}`;
        break;
      case "error":
        this.busy = false;
        this.streamOpen = false;
        this.status = event.text || "Runtime error";
        this.entries.push({ role: "system", text: event.text || "Runtime error" });
        transcriptChanged = true;
        break;
      case "interrupt_ignored":
        this.status = "There is no active turn to interrupt";
        break;
    }
    if (transcriptChanged) invalidateChatLayout(this.entries);
  }

  private approvalDetails(event: RuntimeEvent): string {
    const args = event.tool_arguments || {};
    if (event.tool_name === "exec_command") {
      return String(args.cmd || "") + (args.workdir ? `\nworkdir: ${String(args.workdir)}` : "");
    }
    if (event.tool_name === "apply_patch") return String(args.patch || "");
    return JSON.stringify(args, null, 2);
  }

  private onKey(text: string, key: KeyPress): void {
    if (this.closing) return;
    if (key.ctrl && key.name === "q") {
      this.quit();
      return;
    }
    if (key.ctrl && key.name === "c") {
      if (this.page === "chat" && this.busy) {
        this.bridge.send({ op: "interrupt" });
        this.status = "Interrupt requested";
      } else if (this.approval) {
        this.decideApproval(false);
      } else {
        this.quit();
      }
      this.render();
      return;
    }

    if (this.approval) {
      this.handleApprovalKey(text, key);
      this.render();
      return;
    }

    if (this.page === "loading") return;
    if (this.page === "home") this.handleHomeKey(text, key);
    else if (this.page === "resume") this.handleResumeKey(key);
    else if (this.page === "changelog") this.handleChangelogKey(key);
    else if (this.page === "chat") this.handleChatKey(text, key);
    this.render();
  }

  private onMouse(event: MouseEvent): void {
    if (this.closing || this.page === "loading") return;
    if (event.kind === "up") {
      this.finishScrollbarDrag();
      return;
    }
    if (this.approval) return;

    const width = Math.max(40, process.stdout.columns || 80);
    const height = Math.max(18, process.stdout.rows || 24);
    if (event.kind === "wheel") {
      if (event.delta === 0) return;
      if (this.page !== "chat" && this.page !== "resume") return;
      if (this.pendingWheelPage !== undefined && this.pendingWheelPage !== this.page) {
        this.pendingWheelDelta = 0;
      }
      if (this.pendingWheelDelta !== 0 && Math.sign(this.pendingWheelDelta) !== event.delta) {
        this.pendingWheelDelta = 0;
      }
      const delta = this.wheelNormalizer.consume(event.delta);
      if (delta === 0) return;
      this.pendingWheelPage = this.page;
      if (this.pendingWheelDelta !== 0 && Math.sign(this.pendingWheelDelta) !== Math.sign(delta)) {
        this.pendingWheelDelta = 0;
      }
      this.pendingWheelDelta = Math.max(-2, Math.min(2, this.pendingWheelDelta + delta));
      if (!this.wheelFrameTimer) {
        this.wheelFrameTimer = setTimeout(() => this.flushWheelFrame(), 16);
      }
      return;
    }

    if (this.page === "chat") {
      if (this.scrollbarDragging && event.kind === "move") {
        if (event.button !== 0) {
          this.finishScrollbarDrag();
          return;
        }
        if (this.scrollFromScrollbarPointer(event.y, width, height, this.scrollbarGrabOffset)) {
          this.render();
        }
        return;
      }
      if (event.kind === "down" && event.button === 0 && event.x >= width - 3 && event.x < width - 1) {
        const metrics = chatScrollMetrics(this.entries, width, height, this.chatScroll);
        const trackRow = event.y - metrics.transcriptTop;
        if (metrics.maxScroll > 0 && trackRow >= 0 && trackRow < metrics.transcriptHeight) {
          const onThumb = trackRow >= metrics.thumbTop && trackRow < metrics.thumbTop + metrics.thumbHeight;
          this.scrollbarGrabOffset = onThumb
            ? trackRow - metrics.thumbTop
            : Math.floor(metrics.thumbHeight / 2);
          this.scrollbarDragging = true;
          if (this.scrollFromScrollbarPointer(event.y, width, height, this.scrollbarGrabOffset)) {
            this.render();
          }
        }
      }
      return;
    }

    if (event.kind !== "move" && event.kind !== "down") return;

    if (this.page === "resume") {
      const index = resumeSessionIndexAt(
        width,
        height,
        this.sessions.length,
        this.selectedSession,
        event.x,
        event.y,
      );
      if (index === undefined) return;
      const changed = this.selectedSession !== index;
      this.selectedSession = index;
      if (event.kind === "down" && event.button === 0) {
        const session = this.sessions[index];
        if (session) this.startSession(session.cwd, undefined, session.id);
        this.render();
      } else if (changed) {
        this.render();
      }
      return;
    }
    if (this.page !== "home") return;

    const index = homeMenuIndexAt(width, height, event.x, event.y);
    if (index === undefined) return;
    const changed = this.menuIndex !== index;
    this.menuIndex = index;
    if (event.kind === "down" && event.button === 0) {
      this.activateMenuItem();
      this.render();
    } else if (changed) {
      this.render();
    }
  }

  private scrollFromScrollbarPointer(
    pointerY: number,
    width: number,
    height: number,
    grabOffset: number,
  ): boolean {
    const metrics = chatScrollMetrics(this.entries, width, height, this.chatScroll);
    const trackRow = pointerY - metrics.transcriptTop;
    const requestedThumbTop = trackRow - grabOffset;
    const nextScroll = chatScrollAtThumbTop(metrics, requestedThumbTop);
    if (nextScroll === this.chatScroll) return false;
    this.chatScroll = nextScroll;
    return true;
  }

  private finishScrollbarDrag(): void {
    this.scrollbarDragging = false;
    this.scrollbarGrabOffset = 0;
  }

  private flushWheelFrame(): void {
    this.wheelFrameTimer = undefined;
    const delta = this.pendingWheelDelta;
    const page = this.pendingWheelPage;
    this.pendingWheelDelta = 0;
    this.pendingWheelPage = undefined;
    if (this.closing || delta === 0 || page !== this.page || this.approval) return;

    if (page === "chat") {
      this.scrollChat(-delta);
    } else {
      this.selectedSession = Math.max(
        0,
        Math.min(this.sessions.length - 1, this.selectedSession - delta),
      );
    }
    this.render();
  }

  private handleHomeKey(text: string, key: KeyPress): void {
    if (key.name === "up") {
      this.menuIndex = (this.menuIndex + 2) % 3;
      return;
    }
    if (key.name === "down") {
      this.menuIndex = (this.menuIndex + 1) % 3;
      return;
    }
    if (key.name === "backspace") {
      this.draft = removeLastCharacter(this.draft);
      return;
    }
    if (key.name === "return") {
      if (this.draft.trim()) {
        const prompt = this.draft;
        this.draft = "";
        this.startSession(this.cwd, prompt);
        return;
      }
      this.activateMenuItem();
      return;
    }
    if (key.name === "escape") {
      this.draft = "";
      return;
    }
    if (!key.ctrl && !key.meta && text && isPrintable(text)) this.draft += text;
  }

  private activateMenuItem(): void {
    if (this.menuIndex === 0) {
      this.page = "resume";
      this.selectedSession = 0;
      this.status = "Loading sessions…";
      this.bridge.send({ op: "list_sessions", cwd: this.cwd });
    } else if (this.menuIndex === 1) {
      this.status = "Loading recent changes…";
      this.bridge.send({ op: "changelog" });
    } else {
      this.quit();
    }
  }

  private handleResumeKey(key: KeyPress): void {
    if (key.name === "escape") {
      this.page = "home";
      this.status = "";
    } else if (key.name === "up") {
      this.selectedSession = Math.max(0, this.selectedSession - 1);
    } else if (key.name === "down") {
      this.selectedSession = Math.min(Math.max(0, this.sessions.length - 1), this.selectedSession + 1);
    } else if (key.name === "pageup") {
      this.selectedSession = Math.max(0, this.selectedSession - 8);
    } else if (key.name === "pagedown") {
      this.selectedSession = Math.min(Math.max(0, this.sessions.length - 1), this.selectedSession + 8);
    } else if (key.name === "return") {
      const selected = this.sessions[this.selectedSession];
      if (selected) this.startSession(selected.cwd, undefined, selected.id);
    }
  }

  private handleChangelogKey(key: KeyPress): void {
    if (key.name === "escape" || key.name === "return") {
      this.page = "home";
      this.status = "";
    }
  }

  private handleChatKey(text: string, key: KeyPress): void {
    if (key.name === "pageup") {
      this.scrollChat(8);
    } else if (key.name === "pagedown") {
      this.scrollChat(-8);
    } else if (key.name === "up" && !this.draft) {
      this.scrollChat(1);
    } else if (key.name === "down" && !this.draft) {
      this.scrollChat(-1);
    } else if (key.name === "backspace") {
      this.draft = removeLastCharacter(this.draft);
    } else if (key.name === "return") {
      if (this.draft.trim()) {
        const prompt = this.draft;
        this.draft = "";
        this.submit(prompt);
      }
    } else if (!key.ctrl && !key.meta && text && isPrintable(text)) {
      this.draft += text;
    }
  }

  private scrollChat(delta: number): void {
    const width = Math.max(40, process.stdout.columns || 80);
    const height = Math.max(18, process.stdout.rows || 24);
    const limit = chatScrollLimit(this.entries, width, height);
    this.chatScroll = Math.max(0, Math.min(limit, this.chatScroll + delta));
  }

  private handleApprovalKey(text: string, key: KeyPress): void {
    if (!this.approval) return;
    if (key.name === "pageup" || key.name === "up") {
      this.approval.scroll = Math.max(0, this.approval.scroll - 6);
    } else if (key.name === "pagedown" || key.name === "down") {
      this.approval.scroll += 6;
    } else if (key.name === "escape" || text.toLowerCase() === "n") {
      this.decideApproval(false);
    } else if (text.toLowerCase() === "y") {
      this.decideApproval(true);
    }
  }

  private decideApproval(approved: boolean): void {
    if (!this.approval) return;
    this.bridge.send({
      op: "approval_decision",
      tool_call_id: this.approval.callId,
      approved,
    });
    this.status = approved ? `Approved ${this.approval.toolName}` : `Denied ${this.approval.toolName}`;
    this.approval = undefined;
  }

  private startSession(cwd: string, prompt?: string, threadId?: string): void {
    this.initialPrompt = prompt;
    this.page = "loading";
    this.status = threadId ? "Loading session history…" : "Starting a new session…";
    this.bridge.send({ op: "start_session", cwd, thread_id: threadId });
  }

  private submit(text: string): void {
    if (this.entries.length === 0) {
      this.title = text.trim().split(/\r?\n/, 1)[0] || "New session";
    }
    this.entries.push({ role: "user", text });
    invalidateChatLayout(this.entries);
    this.chatScroll = 0;
    this.status = this.busy ? "Steering message sent" : "Working";
    this.bridge.send({ op: "submit", text });
  }

  private render(): void {
    if (this.closing) return;
    const width = Math.max(40, process.stdout.columns || 80);
    const height = Math.max(18, process.stdout.rows || 24);
    let lines: string[];
    if (this.page === "resume") {
      lines = renderResume({
        width,
        height,
        cwd: this.cwd,
        sessions: this.sessions,
        selected: this.selectedSession,
        status: this.status,
      });
    } else if (this.page === "chat") {
      lines = renderChat({
        width,
        height,
        provider: this.provider,
        model: this.model,
        title: this.title,
        threadId: this.threadId,
        entries: this.entries,
        busy: this.busy,
        status: this.status,
        draft: this.draft,
        scroll: this.chatScroll,
      });
    } else if (this.page === "changelog") {
      lines = renderChangelog(width, height, this.changelog, this.cwd);
    } else {
      const homeStatus = this.page === "loading"
          ? this.status || "Starting…"
          : this.status;
      lines = renderHome({
        width,
        height,
        cwd: this.cwd,
        version: this.version,
        provider: this.provider,
        model: this.model || "model required",
        menuIndex: this.menuIndex,
        draft: this.draft,
        status: homeStatus,
      });
    }
    if (this.approval && this.page === "chat") {
      lines = renderApproval(lines, width, height, this.approval);
    }
    this.terminal.draw(lines);
  }

  private onBridgeExit(code: number): void {
    if (this.shutdownTimer) clearTimeout(this.shutdownTimer);
    if (!this.closing) {
      this.status = `Runtime bridge exited (${code})`;
      this.render();
      return;
    }
    process.exitCode = code === 0 ? 0 : 1;
  }

  private quit(): void {
    if (this.closing) return;
    this.closing = true;
    if (this.wheelFrameTimer) clearTimeout(this.wheelFrameTimer);
    this.wheelFrameTimer = undefined;
    this.pendingWheelDelta = 0;
    this.scrollbarDragging = false;
    this.scrollbarGrabOffset = 0;
    this.terminal.restore();
    this.bridge.stop();
    this.shutdownTimer = setTimeout(() => this.bridge.kill(), 3000);
  }
}

function removeLastCharacter(value: string): string {
  return Array.from(value).slice(0, -1).join("");
}

function isPrintable(value: string): boolean {
  return !value.includes("\u001b") && !value.includes("\u0000") && value !== "\r" && value !== "\n";
}
