export type ToolCall = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
};

export type HistoryMessage = {
  role: "user" | "assistant" | "tool";
  content: string;
  tool_call_id?: string;
  tool_calls?: ToolCall[];
};

export type SavedSession = {
  id: string;
  cwd: string;
  title: string;
  preview: string;
  updated_at: string;
  user_turns: number;
};

export type RuntimeEvent = {
  kind: string;
  thread_id: string;
  turn_id?: string;
  submission_id?: string;
  text?: string;
  tool_name?: string;
  tool_call_id?: string;
  ok?: boolean;
  reason?: string;
  tool_arguments?: Record<string, unknown>;
  cwd?: string;
};

export type BridgeMessage =
  | { type: "ready"; cwd: string; provider: string; model: string; version: string }
  | { type: "sessions_loaded"; cwd: string; sessions: SavedSession[] }
  | { type: "session_loaded"; title: string; session: { thread_id: string; cwd: string; history: HistoryMessage[] } }
  | { type: "event"; event: RuntimeEvent }
  | { type: "submitted"; submission_id: string }
  | { type: "changelog_loaded"; lines: string[] }
  | { type: "bridge_error"; op?: string; message: string };

export type BridgeRequest =
  | { op: "list_sessions"; cwd?: string }
  | { op: "start_session"; cwd?: string; thread_id?: string }
  | { op: "submit"; text: string }
  | { op: "interrupt" }
  | { op: "approval_decision"; tool_call_id: string; approved: boolean }
  | { op: "changelog" }
  | { op: "quit" };

export type KeyPress = {
  name?: string;
  sequence?: string;
  ctrl?: boolean;
  shift?: boolean;
  meta?: boolean;
};
