declare module "node:child_process" {
  export type ChildProcess = {
    stdin: { write(text: string): boolean; end(): void };
    stdout: unknown;
    on(event: string, listener: (...args: any[]) => void): this;
    kill(signal?: string): boolean;
  };
  export function spawn(command: string, args: string[], options: any): ChildProcess;
}

declare module "node:readline" {
  export function createInterface(options: any): {
    on(event: string, listener: (...args: any[]) => void): void;
    close(): void;
  };
  export function emitKeypressEvents(input: unknown): void;
}

declare const process: {
  argv: string[];
  env: Record<string, string | undefined>;
  stdin: {
    isTTY?: boolean;
    setRawMode?: (enabled: boolean) => void;
    resume(): void;
    pause(): void;
    on(event: string, listener: (...args: any[]) => void): this;
    removeAllListeners(event: string): this;
  };
  stdout: {
    isTTY?: boolean;
    columns?: number;
    rows?: number;
    write(text: string): boolean;
    on(event: string, listener: (...args: any[]) => void): this;
  };
  stderr: { write(text: string): boolean };
  on(event: string, listener: (...args: any[]) => void): this;
  exit(code?: number): never;
  exitCode?: number;
};
