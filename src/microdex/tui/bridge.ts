import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import type { BridgeMessage, BridgeRequest } from "./protocol.ts";

export class RuntimeBridge {
  private child: ChildProcess | undefined;
  private readonly options: {
    cwd: string;
    checkpoint: string;
    provider: string;
    model?: string;
    onMessage: (message: BridgeMessage) => void;
    onExit: (code: number) => void;
  };

  constructor(options: {
    cwd: string;
    checkpoint: string;
    provider: string;
    model?: string;
    onMessage: (message: BridgeMessage) => void;
    onExit: (code: number) => void;
  }) {
    this.options = options;
  }

  start(): void {
    const python = process.env.MICRODEX_BRIDGE_PYTHON || "python3";
    const args = [
      "-m",
      "microdex.tui_bridge",
      "--cwd",
      this.options.cwd,
      "--checkpoint",
      this.options.checkpoint,
      "--provider",
      this.options.provider,
    ];
    if (this.options.model) args.push("--model", this.options.model);

    this.child = spawn(python, args, {
      cwd: this.options.cwd,
      env: process.env,
      stdio: ["pipe", "pipe", "inherit"],
    });

    const lines = createInterface({ input: this.child.stdout, crlfDelay: Infinity });
    lines.on("line", (line: string) => {
      try {
        this.options.onMessage(JSON.parse(line) as BridgeMessage);
      } catch {
        this.options.onMessage({
          type: "bridge_error",
          message: `Runtime bridge sent invalid JSON: ${line.slice(0, 160)}`,
        });
      }
    });
    this.child.on("error", (error: Error) => {
      this.options.onMessage({ type: "bridge_error", message: error.message });
    });
    this.child.on("close", (code: number | null) => {
      this.options.onExit(code ?? 1);
    });
  }

  send(request: BridgeRequest): void {
    if (!this.child?.stdin) return;
    this.child.stdin.write(`${JSON.stringify(request)}\n`);
  }

  stop(): void {
    if (!this.child) return;
    this.send({ op: "quit" });
    this.child.stdin.end();
  }

  kill(): void {
    this.child?.kill("SIGTERM");
  }
}
