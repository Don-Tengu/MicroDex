import { emitKeypressEvents } from "node:readline";
import type { KeyPress } from "./protocol.ts";

export type MouseEvent = {
  kind: "move" | "down" | "up" | "wheel";
  x: number;
  y: number;
  button: number;
  delta: -1 | 0 | 1;
};

export class Terminal {
  private active = false;
  private keyHandler: ((text: string, key: KeyPress) => void) | undefined;
  private mouseHandler: ((event: MouseEvent) => void) | undefined;
  private mouseBuffer: string | undefined;
  private readonly resizeHandler = () => this.renderCurrent?.();
  private renderCurrent: (() => void) | undefined;

  start(
    onKey: (text: string, key: KeyPress) => void,
    onMouse: (event: MouseEvent) => void,
  ): void {
    if (!process.stdin.isTTY || !process.stdout.isTTY || !process.stdin.setRawMode) {
      throw new Error("The Microdex TUI needs an interactive terminal. Try --plain for line mode.");
    }
    if (this.active) return;
    this.active = true;
    this.keyHandler = onKey;
    this.mouseHandler = onMouse;
    emitKeypressEvents(process.stdin);
    process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1003h\x1b[?1006h\x1b]0;microdex\u0007");
    process.stdin.on("keypress", this.handleKeypress);
    process.stdout.on("resize", this.resizeHandler);
    process.on("SIGINT", this.handleInterrupt);
  }

  setRender(callback: () => void): void {
    this.renderCurrent = callback;
  }

  draw(lines: string[]): void {
    if (!this.active) return;
    process.stdout.write(`\x1b[2J\x1b[H${lines.join("\r\n")}`);
  }

  restore(): void {
    if (!this.active) return;
    this.active = false;
    if (process.stdin.setRawMode) process.stdin.setRawMode(false);
    process.stdin.pause();
    process.stdin.removeAllListeners("keypress");
    this.mouseBuffer = undefined;
    process.stdout.write("\x1b[?1003l\x1b[?1006l\x1b[0m\x1b[?25h\x1b[?1049l\x1b]0;\u0007");
  }

  private readonly handleKeypress = (text: string, key: KeyPress) => {
    if (this.mouseBuffer !== undefined) {
      this.appendMouseSequence(text ?? "");
      return;
    }
    if (key.sequence?.startsWith("\u001b[<")) {
      const payload = key.sequence.slice(3);
      if (/[Mm]$/.test(payload)) this.dispatchMouseSequence(payload);
      else this.mouseBuffer = payload;
      return;
    }
    this.keyHandler?.(text ?? "", key);
  };

  private appendMouseSequence(text: string): void {
    const buffer = `${this.mouseBuffer ?? ""}${text}`;
    const end = buffer.search(/[Mm]/);
    if (end === -1) {
      this.mouseBuffer = buffer.length > 64 ? undefined : buffer;
      return;
    }
    this.dispatchMouseSequence(buffer.slice(0, end + 1));
    this.mouseBuffer = undefined;
    const remainder = buffer.slice(end + 1);
    for (const character of remainder) {
      this.keyHandler?.(character, { name: character });
    }
  }

  private dispatchMouseSequence(sequence: string): void {
    const match = /^(\d+);(\d+);(\d+)([Mm])$/.exec(sequence);
    if (!match) return;
    const code = Number(match[1]);
    const wheel = (code & 64) !== 0;
    const motion = (code & 32) !== 0;
    const kind = wheel
      ? "wheel"
      : motion
        ? "move"
        : match[4] === "m" || (code & 3) === 3
          ? "up"
          : "down";
    this.mouseHandler?.({
      kind,
      x: Math.max(0, Number(match[2]) - 1),
      y: Math.max(0, Number(match[3]) - 1),
      button: code & 3,
      delta: wheel ? ((code & 1) === 0 ? -1 : 1) : 0,
    });
  }

  private readonly handleInterrupt = () => {
    this.keyHandler?.("", { name: "c", ctrl: true });
  };
}
