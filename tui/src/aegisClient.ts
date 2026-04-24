import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import type {ModelHealth, ModelSpec, RunResult, SessionDetail, SessionRecord} from './types.js';

const dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(dirname, '../..');

type CommandResult = {
  code: number;
  stdout: string;
  stderr: string;
};

function runPython(args: string[]): Promise<CommandResult> {
  return new Promise((resolve, reject) => {
    const child = spawn('python3', ['-m', 'tools.aegis_v2', ...args], {
      cwd: repoRoot,
      env: {
        ...process.env,
        AEGIS_CORE_ROOT: repoRoot,
        PYTHONPATH: [repoRoot, process.env.PYTHONPATH].filter(Boolean).join(':')
      },
      stdio: ['ignore', 'pipe', 'pipe']
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', chunk => {
      stdout += String(chunk);
    });
    child.stderr.on('data', chunk => {
      stderr += String(chunk);
    });
    child.on('error', reject);
    child.on('close', code => resolve({code: code ?? 1, stdout, stderr}));
  });
}

async function jsonCommand<T>(args: string[]): Promise<T> {
  const result = await runPython([...args, '--format', 'json']);
  const payload = result.stdout.trim();
  if (result.code !== 0) {
    try {
      const parsed = JSON.parse(payload) as {error?: string};
      throw new Error(parsed.error || result.stderr || payload || `命令失败: ${args.join(' ')}`);
    } catch (error) {
      if (error instanceof SyntaxError) {
        throw new Error(result.stderr || payload || `命令失败: ${args.join(' ')}`);
      }
      throw error;
    }
  }
  return JSON.parse(payload) as T;
}

export async function listSessions(): Promise<SessionRecord[]> {
  return jsonCommand<SessionRecord[]>(['session', 'list']);
}

export async function showSession(sessionId: string): Promise<SessionDetail> {
  return jsonCommand<SessionDetail>(['session', 'show', sessionId]);
}

export async function listModels(): Promise<ModelSpec[]> {
  return jsonCommand<ModelSpec[]>(['models', 'list']);
}

export async function testModels(): Promise<ModelHealth[]> {
  return jsonCommand<ModelHealth[]>(['models', 'test']);
}

export async function runTask(request: string, options: {execute?: boolean; simulate?: boolean; strategy?: string}): Promise<RunResult> {
  const args: string[] = [options.strategy || 'run', request];
  if (options.execute) {
    args.push('--execute');
  }
  if (options.simulate) {
    args.push('--simulate');
  }
  return jsonCommand<RunResult>(args);
}

export function startTaskStreaming(
  request: string,
  options: {execute?: boolean; simulate?: boolean; strategy?: string},
  handlers: {
    onStarted: (payload: {session: SessionRecord}) => void;
    onFinished?: (payload: {result: RunResult}) => void;
    onProgress?: (payload: {stage?: string; message?: string; runtime?: string; advisor?: Record<string, unknown>; routing?: Record<string, unknown>; plan?: Record<string, unknown>}) => void;
    onError?: (error: Error) => void;
  }
): Promise<RunResult> {
  const args: string[] = [options.strategy || 'run', request, '--stream-jsonl'];
  if (options.execute) {
    args.push('--execute');
  }
  if (options.simulate) {
    args.push('--simulate');
  }
  return new Promise((resolve, reject) => {
    const child = spawn('python3', ['-m', 'tools.aegis_v2', ...args], {
      cwd: repoRoot,
      env: {
        ...process.env,
        AEGIS_CORE_ROOT: repoRoot,
        PYTHONPATH: [repoRoot, process.env.PYTHONPATH].filter(Boolean).join(':')
      },
      stdio: ['ignore', 'pipe', 'pipe']
    });
    let stdoutBuffer = '';
    let stderr = '';
    let finalResult: RunResult | null = null;

    const handleLine = (line: string) => {
      const trimmed = line.trim();
      if (!trimmed) {
        return;
      }
      const payload = JSON.parse(trimmed) as
        | {event: 'session_started'; session: SessionRecord}
        | {event: 'session_finished'; result: RunResult}
        | {event: 'startup_progress'; stage?: string; message?: string; runtime?: string; advisor?: Record<string, unknown>; routing?: Record<string, unknown>; plan?: Record<string, unknown>};
      if (payload.event === 'session_started') {
        handlers.onStarted(payload);
      } else if (payload.event === 'startup_progress') {
        handlers.onProgress?.(payload);
      } else if (payload.event === 'session_finished') {
        finalResult = payload.result;
        handlers.onFinished?.(payload);
      }
    };

    child.stdout.on('data', chunk => {
      stdoutBuffer += String(chunk);
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() ?? '';
      for (const line of lines) {
        try {
          handleLine(line);
        } catch (error) {
          const err = error instanceof Error ? error : new Error(String(error));
          handlers.onError?.(err);
        }
      }
    });
    child.stderr.on('data', chunk => {
      stderr += String(chunk);
    });
    child.on('error', error => {
      handlers.onError?.(error);
      reject(error);
    });
    child.on('close', code => {
      if (stdoutBuffer.trim()) {
        try {
          handleLine(stdoutBuffer);
        } catch (error) {
          const err = error instanceof Error ? error : new Error(String(error));
          handlers.onError?.(err);
          reject(err);
          return;
        }
      }
      if (code !== 0) {
        const error = new Error(stderr || `任务进程退出: ${code}`);
        handlers.onError?.(error);
        reject(error);
        return;
      }
      if (!finalResult) {
        const error = new Error('任务结束但没有返回结果');
        handlers.onError?.(error);
        reject(error);
        return;
      }
      resolve(finalResult);
    });
  });
}
