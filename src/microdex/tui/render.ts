import type { HistoryMessage, SavedSession } from "./protocol.ts";

export type TranscriptEntry = {
  role: "user" | "assistant" | "tool" | "system";
  text: string;
};

const RESET = "\x1b[0m";
const DIM = "\x1b[90m";
const CYAN = "\x1b[36m";
const WHITE = "\x1b[97m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const REVERSE = "\x1b[7m";
const SCROLL_TRACK = "\x1b[90m│\x1b[0m";
const SCROLL_THUMB = "\x1b[7m \x1b[0m";
const HOME_MENU_ITEMS = ["Resume Session", "Changelog", "Quit"];
const transcriptLayoutCache = new WeakMap<TranscriptEntry[], Map<number, string[]>>();

type HomeMenuLayout = {
  cardWidth: number;
  start: number;
  left: number;
  menuTop: number;
};

function homeMenuLayout(width: number, height: number): HomeMenuLayout {
  const cardWidth = Math.min(78, width - 4);
  const panelHeight = HOME_MENU_ITEMS.length + 5;
  const start = Math.max(1, Math.floor((height - 7 - panelHeight) / 2));
  return {
    cardWidth,
    start,
    left: Math.floor((width - cardWidth) / 2),
    menuTop: start + 4,
  };
}

export function homeMenuIndexAt(
  width: number,
  height: number,
  x: number,
  y: number,
): number | undefined {
  const layout = homeMenuLayout(width, height);
  const index = y - layout.menuTop;
  if (
    x < layout.left ||
    x >= layout.left + layout.cardWidth ||
    index < 0 ||
    index >= HOME_MENU_ITEMS.length
  ) {
    return undefined;
  }
  return index;
}

export function renderHome(view: {
  width: number;
  height: number;
  cwd: string;
  version: string;
  provider: string;
  model: string;
  menuIndex: number;
  draft: string;
  status: string;
}): string[] {
  const lines = blankFrame(view.width, view.height);
  const menu = HOME_MENU_ITEMS;
  const { cardWidth, start } = homeMenuLayout(view.width, view.height);
  const inner = cardWidth - 4;
  const card = [
    ` Microdex  ${view.version}`,
    " A small coding agent for your terminal",
    "",
    ...menu.map((item, index) => {
      const hint = index === 2 ? "ctrl+q" : "enter";
      return fit(`  ${item}${" ".repeat(Math.max(1, inner - item.length - hint.length - 4))}${hint}`, inner);
    }),
  ];
  const panel = box(card, cardWidth);
  panel.forEach((line, index) => {
    const menuLine = index >= 4 && index < 4 + menu.length;
    const menuIndex = index - 4;
    const styled = menuLine
      ? menuIndex === view.menuIndex
        ? `${REVERSE}${line}${RESET}`
        : line
      : index === 1
        ? `${WHITE}${line}${RESET}`
        : index === 2
          ? `${DIM}${line}${RESET}`
          : line;
    put(lines, start + index, center(styled, cardWidth, view.width));
  });

  put(lines, view.height - 6, fit(`  ${view.status || "Type a task and press Enter to start in this directory."}`, view.width));
  put(lines, view.height - 5, fit(`  ${DIM}${view.cwd}${RESET}`, view.width));
  put(lines, view.height - 4, `+${"-".repeat(view.width - 2)}+`);
  put(lines, view.height - 3, `| ${fit(`› ${view.draft}`, view.width - 4)} |`);
  put(lines, view.height - 2, fit(`${DIM}  ↑↓ menu  ·  Enter select/send  ·  Ctrl+Q quit${RESET}`, view.width));
  put(lines, view.height - 1, fit(`${DIM}  ${view.provider} / ${view.model}  ·  ${view.cwd}${RESET}`, view.width));
  return lines;
}

function resumeListLayout(height: number): { top: number; rows: number } {
  return { top: 3, rows: Math.max(1, height - 6) };
}

export function resumeSessionIndexAt(
  width: number,
  height: number,
  sessionCount: number,
  selected: number,
  x: number,
  y: number,
): number | undefined {
  if (x < 0 || x >= width) return undefined;
  const layout = resumeListLayout(height);
  const startIndex = Math.max(
    0,
    Math.min(selected - layout.rows + 1, sessionCount - layout.rows),
  );
  const index = startIndex + y - layout.top;
  if (y < layout.top || y >= layout.top + Math.min(layout.rows, sessionCount - startIndex)) {
    return undefined;
  }
  return index;
}

export function renderResume(view: {
  width: number;
  height: number;
  cwd: string;
  sessions: SavedSession[];
  selected: number;
  status: string;
}): string[] {
  const lines = blankFrame(view.width, view.height);
  put(lines, 0, fit(`${WHITE}Resume Session${RESET}${DIM}  ${view.cwd}${RESET}`, view.width));
  put(lines, 1, fit(`${DIM}${view.sessions.length} sessions in this directory${RESET}`, view.width));
  put(lines, 2, fit(DIM + "-".repeat(view.width) + RESET, view.width));

  const { top, rows: availableRows } = resumeListLayout(view.height);
  const selected = Math.min(view.selected, Math.max(0, view.sessions.length - 1));
  const startIndex = Math.max(
    0,
    Math.min(selected - availableRows + 1, view.sessions.length - availableRows),
  );
  if (view.sessions.length === 0) {
    put(lines, top, fit(`${DIM}No sessions found for this directory.${RESET}`, view.width));
  } else {
    view.sessions.slice(startIndex, startIndex + availableRows).forEach((session, offset) => {
      const row = top + offset;
      const date = relativeDate(session.updated_at);
      const titleWidth = Math.max(8, view.width - date.length - 6);
      const label = fit(session.title || "Untitled session", titleWidth);
      const full = fit(`› ${label}${" ".repeat(Math.max(1, view.width - 3 - width(label) - date.length))}${date}`, view.width);
      put(lines, row, selected === startIndex + offset ? `${REVERSE}${full}${RESET}` : full);
    });
  }

  if (view.status) put(lines, view.height - 3, fit(`${YELLOW}${view.status}${RESET}`, view.width));
  put(lines, view.height - 2, fit(`${DIM}↑↓/PgUp/PgDn navigate  ·  hover/click resume  ·  Esc back${RESET}`, view.width));
  return lines;
}

export function renderChat(view: {
  width: number;
  height: number;
  provider: string;
  model: string;
  title: string;
  threadId: string;
  entries: TranscriptEntry[];
  busy: boolean;
  status: string;
  draft: string;
  scroll: number;
}): string[] {
  const lines = blankFrame(view.width, view.height);
  put(lines, 0, fit(`${WHITE}Microdex${RESET}  ${view.title}  ·  ${DIM}${view.threadId.slice(0, 8)}${RESET}`, view.width));

  const metrics = chatScrollMetrics(view.entries, view.width, view.height, view.scroll);
  const { transcriptTop, transcriptHeight, maxScroll, scroll } = metrics;
  const wrapped = metrics.wrappedLines;
  const end = Math.max(0, wrapped.length - scroll);
  const start = Math.max(0, end - transcriptHeight);
  const visible = wrapped.slice(start, end);
  visible.forEach((line, index) => put(lines, transcriptTop + index, line));

  if (maxScroll > 0) {
    for (let row = 0; row < transcriptHeight; row += 1) {
      const glyph = row >= metrics.thumbTop && row < metrics.thumbTop + metrics.thumbHeight
        ? SCROLL_THUMB
        : SCROLL_TRACK;
      const screenRow = transcriptTop + row;
      const current = lines[screenRow];
      const plain = current.replace(/\x1b\[[0-9;]*m/g, "");
      const content = plain.trim() ? current : " ".repeat(Math.max(0, view.width - 3));
      lines[screenRow] = `${content} ${glyph} `;
    }
  }

  if (view.status) put(lines, view.height - 6, fit(`${DIM}${view.status}${RESET}`, view.width));
  const frameWidth = Math.max(0, view.width - 2);
  put(lines, view.height - 5, `${CYAN}╭${"─".repeat(frameWidth)}╮${RESET}`);

  const composerInnerWidth = Math.max(0, view.width - 4);
  const providerModel = [view.provider, view.model].filter(Boolean).join(" · ");
  const modelWidth = Math.min(width(providerModel), Math.max(0, composerInnerWidth - 10));
  const promptWidth = Math.max(0, composerInnerWidth - modelWidth - (modelWidth > 0 ? 1 : 0));
  const promptText = fitInput(view.draft, promptWidth);
  const modelText = modelWidth > 0 ? fit(providerModel, modelWidth) : "";
  const spacer = " ".repeat(Math.max(0, composerInnerWidth - width(promptText) - width(modelText)));
  put(
    lines,
    view.height - 4,
    `${CYAN}│${RESET} ${WHITE}${promptText}${RESET}${spacer}${DIM}${modelText}${RESET} ${CYAN}│${RESET}`,
  );
  put(lines, view.height - 3, `${CYAN}╰${"─".repeat(frameWidth)}╯${RESET}`);
  put(lines, view.height - 1, fit(`${DIM}${view.busy ? "Enter steer" : "Enter send"}  ·  Ctrl+C interrupt  ·  Ctrl+Q quit${RESET}`, view.width));
  return lines;
}

export function chatScrollLimit(entries: TranscriptEntry[], width: number, height: number): number {
  return chatScrollMetrics(entries, width, height, 0).maxScroll;
}

export type ChatScrollMetrics = {
  wrappedLines: string[];
  transcriptTop: number;
  transcriptHeight: number;
  totalLines: number;
  maxScroll: number;
  scroll: number;
  thumbHeight: number;
  thumbTop: number;
};

export function chatScrollMetrics(
  entries: TranscriptEntry[],
  width: number,
  height: number,
  requestedScroll: number,
): ChatScrollMetrics {
  const transcriptTop = 3;
  const transcriptBottom = Math.max(transcriptTop, height - 6);
  const transcriptHeight = transcriptBottom - transcriptTop;
  const wrappedLines = cachedTranscriptLines(entries, width - 3);
  const totalLines = wrappedLines.length;
  const maxScroll = Math.max(0, totalLines - transcriptHeight);
  const scroll = Math.min(maxScroll, Math.max(0, requestedScroll));
  const thumbHeight = maxScroll > 0
    ? Math.max(1, Math.min(transcriptHeight, Math.round((transcriptHeight * transcriptHeight) / totalLines)))
    : transcriptHeight;
  const thumbTravel = Math.max(0, transcriptHeight - thumbHeight);
  const fromTop = maxScroll - scroll;
  const thumbTop = maxScroll > 0 && thumbTravel > 0
    ? Math.round((fromTop / maxScroll) * thumbTravel)
    : 0;

  return {
    wrappedLines,
    transcriptTop,
    transcriptHeight,
    totalLines,
    maxScroll,
    scroll,
    thumbHeight,
    thumbTop,
  };
}

export function invalidateChatLayout(entries: TranscriptEntry[]): void {
  transcriptLayoutCache.delete(entries);
}

function cachedTranscriptLines(entries: TranscriptEntry[], widthLimit: number): string[] {
  let layouts = transcriptLayoutCache.get(entries);
  if (!layouts) {
    layouts = new Map<number, string[]>();
    transcriptLayoutCache.set(entries, layouts);
  }
  let lines = layouts.get(widthLimit);
  if (!lines) {
    lines = wrapTranscript(entries, widthLimit);
    layouts.set(widthLimit, lines);
  }
  return lines;
}

export function chatScrollAtThumbTop(metrics: ChatScrollMetrics, requestedThumbTop: number): number {
  if (metrics.maxScroll === 0) return 0;
  const thumbTravel = metrics.transcriptHeight - metrics.thumbHeight;
  if (thumbTravel <= 0) return metrics.maxScroll;
  const thumbTop = Math.max(0, Math.min(thumbTravel, requestedThumbTop));
  const fromTop = Math.round((thumbTop / thumbTravel) * metrics.maxScroll);
  return metrics.maxScroll - fromTop;
}

export function renderChangelog(width: number, height: number, linesIn: string[], cwd: string): string[] {
  const lines = blankFrame(width, height);
  put(lines, 0, fit(`${WHITE}Changelog${RESET}  ${DIM}${cwd}${RESET}`, width));
  put(lines, 1, fit(`${DIM}Recent repository commits${RESET}`, width));
  const available = Math.max(0, height - 5);
  linesIn.slice(0, available).forEach((line, index) => put(lines, 3 + index, fit(line, width - 2)));
  put(lines, height - 2, fit(`${DIM}Esc back${RESET}`, width));
  return lines;
}

export function renderApproval(
  background: string[],
  width: number,
  height: number,
  approval: { toolName: string; cwd: string; details: string; scroll: number },
): string[] {
  const lines = [...background];
  const cardWidth = Math.min(width - 4, 100);
  const cardHeight = Math.min(height - 4, 16);
  const x = Math.max(0, Math.floor((width - cardWidth) / 2));
  const y = Math.max(1, Math.floor((height - cardHeight) / 2));
  const contentWidth = cardWidth - 4;
  const details = wrapText(approval.details || "(no arguments)", contentWidth);
  const displayRows = Math.max(1, cardHeight - 6);
  const visibleDetails = details.slice(approval.scroll, approval.scroll + displayRows);
  const content = [
    `Tool approval · ${approval.toolName}`,
    `cwd: ${approval.cwd}`,
    ...visibleDetails,
    `${approval.scroll + displayRows < details.length ? "↓ more" : ""}  y approve  ·  n / Esc deny`,
  ];
  const panel = box(content, cardWidth);
  panel.forEach((line, index) => put(lines, y + index, " ".repeat(x) + `${YELLOW}${line}${RESET}`));
  return lines;
}

export function historyToTranscript(history: HistoryMessage[]): TranscriptEntry[] {
  const entries: TranscriptEntry[] = [];
  for (const message of history) {
    if (message.role === "user") {
      entries.push({ role: "user", text: message.content });
      continue;
    }
    if (message.role === "assistant") {
      if (message.content) entries.push({ role: "assistant", text: message.content });
      for (const call of message.tool_calls ?? []) {
        entries.push({ role: "tool", text: `${call.name}  ${JSON.stringify(call.arguments)}` });
      }
      continue;
    }
    entries.push({ role: "tool", text: message.content });
  }
  return entries;
}

function wrapTranscript(entries: TranscriptEntry[], widthLimit: number): string[] {
  const lines: string[] = [];
  for (const entry of entries) {
    const label = entry.role === "user" ? "› " : entry.role === "assistant" ? "Microdex  " : entry.role === "system" ? "· " : "◇ ";
    const color = entry.role === "user" ? CYAN : entry.role === "assistant" ? WHITE : entry.role === "system" ? YELLOW : DIM;
    const content = entry.text;
    const wrapped = wrapText(content || " ", Math.max(8, widthLimit - width(label)));
    wrapped.forEach((part, index) => {
      const text = `${index === 0 ? label : "  "}${part}`;
      lines.push(`${color}${fit(text, widthLimit)}${RESET}`);
    });
    lines.push("");
  }
  return lines;
}

function wrapText(text: string, widthLimit: number): string[] {
  const result: string[] = [];
  for (const sourceLine of text.split("\n")) {
    let row = "";
    let rowWidth = 0;
    for (const character of Array.from(sourceLine)) {
      const characterWidth = width(character);
      if (row && rowWidth + characterWidth > widthLimit) {
        result.push(row);
        row = "";
        rowWidth = 0;
      }
      row += character;
      rowWidth += characterWidth;
    }
    result.push(row);
  }
  return result;
}

function box(content: string[], widthLimit: number): string[] {
  const inner = Math.max(8, widthLimit - 4);
  return [
    `+${"-".repeat(widthLimit - 2)}+`,
    ...content.map((line) => `| ${fit(line, inner)} |`),
    `+${"-".repeat(widthLimit - 2)}+`,
  ];
}

function blankFrame(widthLimit: number, height: number): string[] {
  return Array.from({ length: Math.max(1, height) }, () => " ".repeat(Math.max(1, widthLimit)));
}

function put(lines: string[], row: number, text: string): void {
  if (row >= 0 && row < lines.length) lines[row] = text;
}

function center(text: string, itemWidth: number, totalWidth: number): string {
  const left = Math.max(0, Math.floor((totalWidth - itemWidth) / 2));
  return " ".repeat(left) + text;
}

function fit(text: string, widthLimit: number): string {
  const raw = text.replace(/\x1b\[[0-9;]*m/g, "");
  if (width(raw) <= widthLimit) return text + " ".repeat(Math.max(0, widthLimit - width(raw)));
  let output = "";
  let used = 0;
  for (const character of Array.from(raw)) {
    const characterWidth = width(character);
    if (used + characterWidth > Math.max(0, widthLimit - 1)) break;
    output += character;
    used += characterWidth;
  }
  return output + "…" + " ".repeat(Math.max(0, widthLimit - used - 1));
}

function fitInput(draft: string, widthLimit: number): string {
  if (widthLimit <= 0) return "";
  const prefix = "› ";
  const cursor = "▏";
  const full = `${prefix}${draft}${cursor}`;
  if (width(full) <= widthLimit) return full + " ".repeat(widthLimit - width(full));

  const tailBudget = Math.max(0, widthLimit - width(prefix) - width("…") - width(cursor));
  let tail = "";
  for (const character of Array.from(draft).reverse()) {
    if (width(character) + width(tail) > tailBudget) break;
    tail = character + tail;
  }
  const truncated = `${prefix}…${tail}${cursor}`;
  return truncated + " ".repeat(Math.max(0, widthLimit - width(truncated)));
}

function width(text: string): number {
  let total = 0;
  for (const character of Array.from(text)) {
    const code = character.codePointAt(0) ?? 0;
    total +=
      code >= 0x1100 &&
      (code <= 0x115f || code === 0x2329 || code === 0x232a || (code >= 0x2e80 && code <= 0xa4cf) || (code >= 0xac00 && code <= 0xd7a3) || (code >= 0xf900 && code <= 0xfaff) || (code >= 0xfe10 && code <= 0xfe6f) || (code >= 0xff00 && code <= 0xff60) || (code >= 0x1f300 && code <= 0x1faff))
        ? 2
        : 1;
  }
  return total;
}

function relativeDate(value: string): string {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
