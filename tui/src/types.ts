export type SessionRecord = {
  session_id: string;
  request: string;
  task_type: string;
  strategy: string;
  models: string[];
  mode: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SessionMessage = {
  session_id: string;
  channel: string;
  sender: string;
  recipient: string | null;
  message_type: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type SessionDetail = SessionRecord & {
  checkpoints: Array<{stage: string; payload: unknown; created_at: string}>;
  messages: SessionMessage[];
};

export type ModelSpec = {
  name: string;
  provider: string;
  runtime: string;
  capabilities: string[];
};

export type ModelHealth = {
  name: string;
  available: boolean;
  runtime: string;
  provider: string;
  details: string;
};

export type RunResult = {
  session: SessionRecord;
  executed: boolean;
  message: string;
  execution?: {
    strategy: string;
    final_output: string;
    stage_results: Array<{
      stage_name: string;
      model: string;
      kind: string;
      output: string;
      exit_code: number;
      duration_ms: number;
      approximate_cost?: number;
      metadata?: Record<string, unknown>;
    }>;
    iterations?: number | null;
    approximate_cost?: number;
    shared_context?: Record<string, unknown>;
  };
};
