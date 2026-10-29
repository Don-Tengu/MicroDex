import { TuiApp } from "./app.ts";
import type { TuiOptions } from "./app.ts";

function parseArgs(argv: string[]): TuiOptions {
  const options: TuiOptions = {
    cwd: process.env.PWD || ".",
    checkpoint: ".microdex/checkpoints.sqlite",
    provider: "xai",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index + 1];
    if (argv[index] === "--cwd" && value) {
      options.cwd = value;
      index += 1;
    } else if (argv[index] === "--checkpoint" && value) {
      options.checkpoint = value;
      index += 1;
    } else if (argv[index] === "--provider" && value) {
      options.provider = value;
      index += 1;
    } else if (argv[index] === "--model" && value) {
      options.model = value;
      index += 1;
    }
  }
  options.model ||= options.provider === "openai"
    ? process.env.OPENAI_MODEL
    : process.env.XAI_MODEL;
  return options;
}

try {
  new TuiApp(parseArgs(process.argv.slice(2))).start();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 2;
}
