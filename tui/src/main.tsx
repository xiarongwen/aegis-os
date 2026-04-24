import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {Box, Text, useApp, useInput, render} from 'ink';
import TextInput from 'ink-text-input';
import {listModels, listSessions, showSession, startTaskStreaming, testModels} from './aegisClient.js';
import type {ModelHealth, SessionDetail, SessionRecord} from './types.js';

type View = 'main' | 'models' | 'sessions';
const ALT_SCREEN_ENABLE = '\u001B[?1049h\u001B[2J\u001B[H';
const ALT_SCREEN_DISABLE = '\u001B[?1049l';
const MODE_ORDER = ['moa', 'pair', 'swarm', 'pipeline', 'run'] as const;
type ModeOption = (typeof MODE_ORDER)[number];

type SubmitOptions = {
  request: string;
  execute?: boolean;
  simulate?: boolean;
  strategy?: string;
};

type SlashCommand = {
  name: string;
  description: string;
  hint: string;
  options?: Omit<SubmitOptions, 'request'>;
  view?: View;
};

const SLASH_COMMANDS: SlashCommand[] = [
  {name: '/models', description: '查看模型状态', hint: '/models', view: 'models'},
  {name: '/session', description: '查看最近会话', hint: '/session', view: 'sessions'},
  {name: '/simulate', description: '模拟执行完整协作流程', hint: '/simulate 修复登录 bug', options: {simulate: true}},
  {name: '/execute', description: '真实调用 runtime 执行任务', hint: '/execute 修复登录 bug', options: {execute: true}},
  {name: '/pair', description: '双模型编程 + 审查', hint: '/pair 重构认证模块', options: {strategy: 'pair'}},
  {name: '/swarm', description: '多 worker 并行协作', hint: '/swarm 补齐支付模块测试', options: {strategy: 'swarm'}},
  {name: '/pipeline', description: '流水线式分阶段执行', hint: '/pipeline 修复登录 bug', options: {strategy: 'pipeline'}},
  {name: '/moa', description: '多专家聚合评审', hint: '/moa 评审架构方案', options: {strategy: 'moa'}}
];

function slashSuggestions(value: string): SlashCommand[] {
  const input = value.trimStart();
  if (!input.startsWith('/') || input.includes(' ')) {
    return [];
  }
  return SLASH_COMMANDS.filter(command => command.name.startsWith(input)).slice(0, 7);
}

function parseCommand(value: string): SubmitOptions | {view: View} | null {
  const input = value.trim();
  if (!input) {
    return null;
  }
  for (const command of SLASH_COMMANDS) {
    if (input === command.name && command.view) {
      return {view: command.view};
    }
    if (input.startsWith(`${command.name} `)) {
      return {request: input.slice(command.name.length).trim(), ...(command.options ?? {})};
    }
  }
  return {request: input};
}

function nextMode(current: ModeOption): ModeOption {
  const index = MODE_ORDER.indexOf(current);
  return MODE_ORDER[(index + 1) % MODE_ORDER.length] ?? 'moa';
}

function modeLabel(mode: ModeOption): string {
  if (mode === 'moa') {
    return 'MOA 专家';
  }
  if (mode === 'pair') {
    return 'Pair';
  }
  if (mode === 'swarm') {
    return 'Swarm';
  }
  if (mode === 'pipeline') {
    return 'Pipeline';
  }
  return 'Run';
}

function modeDescription(mode: ModeOption): string {
  if (mode === 'moa') {
    return '多专家先独立判断，再讨论后聚合裁决。';
  }
  if (mode === 'pair') {
    return '双模型来回编写与审查，适合需要反复打磨的任务。';
  }
  if (mode === 'swarm') {
    return '并行拆分多个 worker 同时推进，再统一聚合。';
  }
  if (mode === 'pipeline') {
    return '按阶段顺序传递上下文，适合分步推进。';
  }
  return '单路径直接执行，适合明确且简单的任务。';
}

function statusColor(status: string): 'green' | 'red' | 'yellow' | 'gray' {
  if (['completed', 'passed'].includes(status)) {
    return 'green';
  }
  if (['failed', 'error'].includes(status)) {
    return 'red';
  }
  if (['running'].includes(status)) {
    return 'yellow';
  }
  return 'gray';
}

function compactText(value: unknown, max = 92): string {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) {
    return text;
  }
  return `${text.slice(0, Math.max(0, max - 1))}…`;
}

function normalizeMultilineText(value: unknown): string[] {
  const raw = String(value ?? '').trim();
  if (!raw) {
    return [];
  }
  return raw
    .split(/\r?\n/)
    .map(line => line.trimEnd())
    .filter((line, index, arr) => line.length > 0 || (index > 0 && index < arr.length - 1));
}

type StartupEvent = {
  stage: string;
  message: string;
};

function startupMessage(payload: {
  stage?: string;
  message?: string;
  runtime?: string;
  advisor?: Record<string, unknown>;
  routing?: Record<string, unknown>;
  plan?: Record<string, unknown>;
}): string {
  if (payload.stage === 'advisor_done' && payload.advisor) {
    const taskType = String(payload.advisor.task_type ?? 'unknown');
    const strategy = String(payload.advisor.strategy ?? 'unknown');
    const models = Array.isArray(payload.advisor.models)
      ? payload.advisor.models.map(model => displayModelLabel(model)).join(', ')
      : '';
    return `${taskType} / ${strategy}${models ? ` / ${models}` : ''}`;
  }
  if (payload.stage === 'planning' && payload.routing) {
    const routing = payload.routing;
    const strategy = String(routing.strategy ?? 'unknown');
    const models = Array.isArray(routing.models)
      ? routing.models.map(model => displayModelLabel(model)).join(', ')
      : '';
    return `${strategy}${models ? ` / ${models}` : ''}`;
  }
  return String(payload.message ?? 'working');
}

function displayModelLabel(value: unknown): string {
  const model = String(value ?? '').trim();
  if (!model) {
    return '';
  }
  if (model === 'codex' || model.startsWith('codex')) {
    return 'codex';
  }
  if (model === 'claude' || model.startsWith('claude-')) {
    return 'claude';
  }
  if (model.startsWith('aider')) {
    return 'aider';
  }
  if (model.startsWith('opencode')) {
    return 'opencode';
  }
  return model;
}

function displayStageLabel(value: unknown): string {
  const stage = String(value ?? '').trim();
  if (!stage) {
    return '';
  }
  if (stage === 'aggregate') {
    return 'aggregate';
  }
  if (stage.startsWith('expert-') && stage.endsWith('-deliberate')) {
    return `discuss:${stage.slice('expert-'.length, -'-deliberate'.length)}`;
  }
  if (stage.startsWith('expert-')) {
    return `expert:${stage.slice('expert-'.length)}`;
  }
  if (stage.startsWith('review-round-')) {
    return `review:${stage.slice('review-round-'.length)}`;
  }
  if (stage.startsWith('code-round-')) {
    return `code:${stage.slice('code-round-'.length)}`;
  }
  return stage;
}

type ModelActivity = {
  model: string;
  state: 'queued' | 'running' | 'reviewing' | 'completed' | 'failed';
  stage: string;
  summary: string;
  updatedAt?: string;
};

function stageNameFromContent(content: string): string {
  const match = content.match(/starting\s+(.+)$/i);
  return match?.[1]?.trim() || '执行中';
}

function activityColor(state: ModelActivity['state']): 'green' | 'red' | 'yellow' | 'cyan' | 'gray' {
  if (state === 'completed') {
    return 'green';
  }
  if (state === 'failed') {
    return 'red';
  }
  if (state === 'reviewing') {
    return 'cyan';
  }
  if (state === 'running') {
    return 'yellow';
  }
  return 'gray';
}

function activityLabel(state: ModelActivity['state']): string {
  if (state === 'completed') {
    return '完成';
  }
  if (state === 'failed') {
    return '失败';
  }
  if (state === 'reviewing') {
    return '评审';
  }
  if (state === 'running') {
    return '执行';
  }
  return '等待';
}

function deriveModelActivities(detail: SessionDetail): ModelActivity[] {
  const execution = detail.metadata.execution as {
    stage_results?: Array<{
      stage_name?: string;
      model?: string;
      kind?: string;
      exit_code?: number;
      output?: string;
    }>;
  } | undefined;
  const plan = detail.metadata.execution_plan as {
    steps?: Array<{name?: string; model?: string; kind?: string}>;
  } | undefined;
  const stageResults = execution?.stage_results ?? [];
  const activities = new Map<string, ModelActivity>();

  for (const step of plan?.steps ?? []) {
    const model = String(step.model ?? '').trim();
    if (!model || activities.has(model)) {
      continue;
    }
    activities.set(model, {
      model,
      state: 'queued',
      stage: String(step.name ?? '等待调度'),
      summary: `等待 ${String(step.kind ?? 'stage')}`,
    });
  }

  for (const result of stageResults) {
    const model = String(result.model ?? '').trim();
    if (!model) {
      continue;
    }
    activities.set(model, {
      model,
      state: Number(result.exit_code ?? 0) === 0 ? 'completed' : 'failed',
      stage: String(result.stage_name ?? '完成'),
      summary: compactText(result.output ?? '', 56) || (Number(result.exit_code ?? 0) === 0 ? '阶段完成' : '阶段失败'),
    });
  }

  for (const message of detail.messages) {
    const sender = String(message.sender ?? '').trim();
    const recipient = message.recipient ? String(message.recipient).trim() : '';
    const content = String(message.content ?? '');
    const metadata = message.metadata ?? {};
    const model = String((metadata as Record<string, unknown>).model ?? sender).trim();

    if (message.channel === 'lifecycle' && message.message_type === 'stage_start' && model) {
      activities.set(model, {
        model,
        state: sender === 'router' ? 'running' : 'running',
        stage: stageNameFromContent(content),
        summary: `${String((metadata as Record<string, unknown>).kind ?? 'stage')} 正在运行`,
        updatedAt: message.created_at,
      });
      continue;
    }

    if (message.channel === 'reviews' && sender) {
      activities.set(sender, {
        model: sender,
        state: 'reviewing',
        stage: String((metadata as Record<string, unknown>).iteration ? `review round ${(metadata as Record<string, unknown>).iteration}` : 'review'),
        summary: compactText(content, 56) || '正在审查实现',
        updatedAt: message.created_at,
      });
      if (recipient) {
        activities.set(recipient, {
          model: recipient,
          state: 'running',
          stage: '等待修正',
          summary: `收到 ${sender} 的评审反馈`,
          updatedAt: message.created_at,
        });
      }
      continue;
    }

    if (message.channel === 'errors' && model) {
      activities.set(model, {
        model,
        state: 'failed',
        stage: '失败',
        summary: compactText(content, 56),
        updatedAt: message.created_at,
      });
      continue;
    }

    if (message.channel === 'stages' && sender) {
      const result = stageResults.find(stage => stage.model === sender && stage.stage_name === (metadata as Record<string, unknown>).stage);
      activities.set(sender, {
        model: sender,
        state: result && Number(result.exit_code ?? 0) !== 0 ? 'failed' : 'completed',
        stage: String((metadata as Record<string, unknown>).stage ?? '完成'),
        summary: compactText(content, 56) || '阶段输出已生成',
        updatedAt: message.created_at,
      });
      continue;
    }

    if (message.channel === 'runtime' && sender) {
      const existing = activities.get(sender);
      activities.set(sender, {
        model: sender,
        state: existing?.state === 'reviewing' ? 'reviewing' : 'running',
        stage: String((metadata as Record<string, unknown>).stage ?? existing?.stage ?? '执行中'),
        summary: compactText(content, 56) || existing?.summary || '正在输出',
        updatedAt: message.created_at,
      });
    }
  }

  const activeStates: Record<ModelActivity['state'], number> = {
    running: 0,
    reviewing: 1,
    queued: 2,
    failed: 3,
    completed: 4
  };

  return Array.from(activities.values()).sort((left, right) => {
    const stateOrder = activeStates[left.state] - activeStates[right.state];
    if (stateOrder !== 0) {
      return stateOrder;
    }
    return left.model.localeCompare(right.model);
  });
}

function progressFor(session: SessionRecord): string {
  const execution = session.metadata.execution as {stage_results?: unknown[]} | undefined;
  const plan = session.metadata.execution_plan as {steps?: unknown[]} | undefined;
  const total = plan?.steps?.length ?? 0;
  const done = Math.min(execution?.stage_results?.length ?? 0, total || 0);
  if (!total) {
    return session.status === 'completed' || session.status === 'failed' ? '100%' : '0%';
  }
  return `${done}/${total}`;
}

function SessionList({sessions, selected}: {sessions: SessionRecord[]; selected: number}) {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="blue" paddingX={1}>
      <Text bold>最近会话</Text>
      {sessions.slice(0, 10).map((session, index) => (
        <Box key={session.session_id}>
          <Text color={index === selected ? 'cyan' : undefined}>
            {index === selected ? '› ' : '  '}
            {session.session_id.padEnd(18)} {session.strategy.padEnd(8)} {progressFor(session).padEnd(5)}{' '}
          </Text>
          <Text color={statusColor(session.status)}>{session.status.padEnd(10)} </Text>
          <Text>{session.request.slice(0, 46)}</Text>
        </Box>
      ))}
      {sessions.length === 0 && <Text color="gray">暂无会话，直接在底部输入任务开始。</Text>}
    </Box>
  );
}

function relativeTimeLabel(value: string): string {
  const target = Date.parse(value);
  if (Number.isNaN(target)) {
    return '--';
  }
  const deltaSeconds = Math.max(0, Math.floor((Date.now() - target) / 1000));
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`;
  }
  const deltaMinutes = Math.floor(deltaSeconds / 60);
  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`;
  }
  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) {
    return `${deltaHours}h ago`;
  }
  const deltaDays = Math.floor(deltaHours / 24);
  return `${deltaDays}d ago`;
}

function WelcomePanel() {
  const logoLines = [
    ' █████╗ ███████╗ ██████╗ ██╗███████╗',
    '██╔══██╗██╔════╝██╔════╝ ██║██╔════╝',
    '███████║█████╗  ██║  ███╗██║███████╗',
    '██╔══██║██╔══╝  ██║   ██║██║╚════██║',
    '██║  ██║███████╗╚██████╔╝██║███████║',
    '╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝╚══════╝'
  ];

  return (
    <Box flexDirection="column" alignItems="center" marginTop={1} marginBottom={1}>
      <Text bold color="cyan">Welcome back</Text>
      <Text color="gray">AEGIS v2</Text>
      <Box flexDirection="column" marginTop={1}>
        {logoLines.map((line, index) => (
          <Text key={`logo-${index}`} color="cyan">
            {line}
          </Text>
        ))}
      </Box>
      <Text color="gray" dimColor>claude / codex</Text>
      <Text color="gray" dimColor>{compactText(process.cwd(), 72)}</Text>
    </Box>
  );
}

function StartupPanel({events}: {events: StartupEvent[]}) {
  if (events.length === 0) {
    return null;
  }
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1}>
      <Text bold>启动过程</Text>
      {events.slice(-6).map((event, index) => (
        <Text key={`${event.stage}-${index}`}>
          <Text color="yellow">{event.stage.padEnd(12)}</Text>
          <Text color="gray"> {event.message}</Text>
        </Text>
      ))}
    </Box>
  );
}

function DetailPanel({detail}: {detail: SessionDetail | null}) {
  if (!detail) {
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1}>
        <Text bold>运行详情</Text>
        <Text color="gray">选择一个会话或输入新任务。</Text>
      </Box>
    );
  }
  const messages = detail.messages.slice(-8);
  const visibleModels = Array.from(new Set(detail.models.map(model => displayModelLabel(model))));
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
      <Text bold>
        运行详情 <Text color={statusColor(detail.status)}>{detail.status}</Text>
      </Text>
      <Text>任务: {detail.request}</Text>
      <Text>
        类型: {detail.task_type}  策略: {detail.strategy}  模型: {visibleModels.join(', ')}
      </Text>
      <Text color="gray">
        检查点: {detail.checkpoints.length}  消息: {detail.messages.length}
      </Text>
      <Text bold>消息</Text>
      {messages.length === 0 && <Text color="gray">暂无消息。</Text>}
      {messages.map((message, index) => (
        <Text key={`${message.created_at}-${index}`}>
          <Text color="gray">{message.created_at.slice(11, 16)} </Text>
          <Text color="yellow">[{message.channel}] </Text>
          <Text>{message.content.replace(/\s+/g, ' ').slice(0, 88)}</Text>
        </Text>
      ))}
    </Box>
  );
}

function TaskPanel({detail}: {detail: SessionDetail | null}) {
  if (!detail) {
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
        <Text bold>任务面板</Text>
        <Text color="gray">任务创建后会自动进入这里。</Text>
      </Box>
    );
  }
  const execution = detail.metadata.execution as {
    final_output?: string;
    iterations?: number | null;
    approximate_cost?: number;
    stage_results?: Array<{
      stage_name?: string;
      model?: string;
      kind?: string;
      exit_code?: number;
      output?: string;
      duration_ms?: number;
    }>;
  } | undefined;
  const plan = detail.metadata.execution_plan as {steps?: Array<{name?: string; model?: string; kind?: string}>} | undefined;
  const steps = plan?.steps ?? [];
  const results = execution?.stage_results ?? [];
  const resultByStage = new Map(results.map(result => [result.stage_name, result]));
  const recentMessages = detail.messages.slice(-6);
  const nextStep = steps.find(step => !resultByStage.has(step.name));
  const lastResult = results.at(-1);
  const focusStage = detail.status === 'completed' || detail.status === 'failed' ? lastResult?.stage_name : nextStep?.name ?? lastResult?.stage_name;
  const focusModel = detail.status === 'completed' || detail.status === 'failed' ? lastResult?.model : nextStep?.model ?? lastResult?.model;
  const focusKind = detail.status === 'completed' || detail.status === 'failed' ? lastResult?.kind : nextStep?.kind ?? lastResult?.kind;
  const doneCount = results.length;
  const totalCount = steps.length || results.length;
  const finalOutput = execution?.final_output ?? String(detail.metadata.final_output ?? '');
  const finalOutputLines = normalizeMultilineText(finalOutput);
  const modelActivities = deriveModelActivities(detail);
  const visibleSteps = (() => {
    if (steps.length === 0) {
      return [];
    }
    const focusIndex = Math.max(0, steps.findIndex(step => step.name === focusStage));
    const start = Math.max(0, Math.min(focusIndex - 2, Math.max(steps.length - 5, 0)));
    return steps.slice(start, start + 5);
  })();
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" paddingX={1}>
      <Text bold>
        任务面板 <Text color={statusColor(detail.status)}>{detail.status}</Text>
      </Text>
      <Text>任务: {compactText(detail.request, 84)}</Text>
      <Text color="gray">
        会话: {detail.session_id}  策略: {detail.strategy}  进度: {doneCount}/{totalCount || '?'}
      </Text>
      <Text>
        当前: <Text color={detail.status === 'running' ? 'yellow' : statusColor(detail.status)}>{displayStageLabel(focusStage ?? '等待调度')}</Text>
        <Text color="gray">  {String(focusKind ?? detail.task_type)} / {String(displayModelLabel(focusModel ?? detail.models.join(', ')) || '未分配')}</Text>
      </Text>
      <Text bold>阶段</Text>
      {visibleSteps.map(step => {
        const result = resultByStage.get(step.name);
        const isFocus = step.name === focusStage;
        const status = result ? (result.exit_code === 0 ? '完成' : '失败') : (isFocus && detail.status === 'running' ? '执行' : '等待');
        return (
          <Text key={step.name}>
            <Text color={result ? (result.exit_code === 0 ? 'green' : 'red') : 'gray'}>{status.padEnd(4)} </Text>
            <Text color={isFocus ? 'cyan' : undefined}>{displayStageLabel(step.name ?? '').padEnd(18)}</Text>
            <Text color="gray"> {String(step.kind ?? '').padEnd(10)} {compactText(displayModelLabel(step.model), 28)}</Text>
          </Text>
        );
      })}
      {steps.length > visibleSteps.length && <Text color="gray">… 已折叠 {steps.length - visibleSteps.length} 个阶段</Text>}
      {steps.length === 0 && <Text color="gray">计划已创建，尚无阶段数据。</Text>}
      <Text bold>模型活动</Text>
      {modelActivities.length === 0 && <Text color="gray">等待模型开始执行...</Text>}
      {modelActivities.map(activity => (
        <Text key={`${activity.model}-${activity.stage}`}>
          <Text color={activityColor(activity.state)}>{activityLabel(activity.state).padEnd(4)} </Text>
          {displayModelLabel(activity.model).padEnd(22)}
          <Text color="gray"> {compactText(displayStageLabel(activity.stage), 18).padEnd(18)} </Text>
          <Text>{compactText(activity.summary, 44)}</Text>
        </Text>
      ))}
      {results.length > 0 && (
        <>
          <Text bold>最近输出</Text>
          {results.slice(-3).map(result => (
            <Text key={`${result.stage_name}-${result.model}`}>
              <Text color={result.exit_code === 0 ? 'green' : 'red'}>{result.exit_code === 0 ? '完成' : '失败'} </Text>
              {displayStageLabel(result.stage_name ?? '').padEnd(18)}
              <Text color="gray"> {compactText(result.output, detail.status === 'completed' ? 120 : 74)}</Text>
            </Text>
          ))}
        </>
      )}
      {finalOutputLines.length > 0 && (
        <>
          <Text bold>最终结果</Text>
          {finalOutputLines.map((line, index) => (
            <Text key={`final-output-${index}`} color="gray">
              {line}
            </Text>
          ))}
        </>
      )}
      <Text bold>实时事件</Text>
      {recentMessages.length === 0 && <Text color="gray">等待 agent 事件...</Text>}
      {recentMessages.map((message, index) => (
        <Text key={`${message.created_at}-${index}`}>
          <Text color="gray">{message.created_at.slice(11, 16)} </Text>
          <Text color="yellow">[{message.channel}] </Text>
          {message.sender}: {compactText(message.content, 76)}
        </Text>
      ))}
    </Box>
  );
}

function ModelView({health}: {health: ModelHealth[]}) {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="magenta" paddingX={1}>
      <Text bold>模型状态</Text>
      {health.map(model => (
        <Text key={model.name}>
          {model.name.padEnd(22)} {model.runtime.padEnd(16)}{' '}
          <Text color={model.available ? 'green' : 'red'}>{model.available ? '可用' : '不可用'}</Text>
          <Text color="gray"> {model.details.slice(0, 80)}</Text>
        </Text>
      ))}
      {health.length === 0 && <Text color="gray">暂无模型状态。</Text>}
    </Box>
  );
}

function InputBar({
  value,
  busy,
  interactive,
  mode,
  onChange,
  onSubmit
}: {
  value: string;
  busy: boolean;
  interactive: boolean;
  mode: ModeOption;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" paddingX={2} paddingY={1}>
      <Box justifyContent="space-between">
        <Text color="cyan" bold>任务</Text>
        <Text color="gray">Tab 切模式 · /session /models /execute /simulate</Text>
      </Box>
      <Box marginTop={1}>
        {MODE_ORDER.map(item => {
          const active = item === mode;
          return (
            <Text key={`mode-${item}`} color={active ? 'black' : 'gray'} backgroundColor={active ? 'cyan' : undefined}>
              {' '}
              {modeLabel(item)}
              {' '}
            </Text>
          );
        })}
      </Box>
      <Box marginTop={1}>
        <Text color="gray">{modeDescription(mode)}</Text>
      </Box>
      <Box marginTop={1}>
        <Text color="gray">› </Text>
        {interactive ? (
          <TextInput
            value={value}
            onChange={onChange}
            onSubmit={onSubmit}
            placeholder={busy ? '正在处理...' : `当前模式: ${modeLabel(mode)} · 描述目标、问题或你想推进的工程`}
          />
        ) : (
          <Text color="gray">描述目标、问题或你想推进的工程</Text>
        )}
      </Box>
    </Box>
  );
}

function SlashCommandMenu({input, selected}: {input: string; selected: number}) {
  const suggestions = slashSuggestions(input);
  if (suggestions.length === 0) {
    return null;
  }
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1}>
      <Text bold color="yellow">可用命令</Text>
      {suggestions.map((command, index) => (
        <Box key={command.name}>
          <Text color={index === selected ? 'cyan' : 'white'}>{index === selected ? '› ' : '  '}{command.name.padEnd(12)} </Text>
          <Text>{command.description}</Text>
          <Text color="gray">  {command.hint}</Text>
        </Box>
      ))}
    </Box>
  );
}

function App({interactive}: {interactive: boolean}) {
  const {exit} = useApp();
  const [view, setView] = useState<View>('main');
  const [taskMode, setTaskMode] = useState(false);
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [selected, setSelected] = useState(0);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [models, setModels] = useState<ModelHealth[]>([]);
  const [input, setInput] = useState('');
  const [slashSelected, setSlashSelected] = useState(0);
  const [status, setStatus] = useState('就绪');
  const [busy, setBusy] = useState(false);
  const [startupEvents, setStartupEvents] = useState<StartupEvent[]>([]);
  const [mode, setMode] = useState<ModeOption>('moa');

  const selectedSession = useMemo(() => sessions[selected], [sessions, selected]);
  const suggestions = useMemo(() => slashSuggestions(input), [input]);

  const refreshSessions = useCallback(async () => {
    const next = await listSessions();
    setSessions(next);
    setSelected(current => Math.max(0, Math.min(current, next.length - 1)));
    return next;
  }, []);

  const refreshDetail = useCallback(async (sessionId: string) => {
    setDetail(await showSession(sessionId));
  }, []);

  useEffect(() => {
    void refreshSessions().catch(error => setStatus(`加载会话失败: ${String(error.message || error)}`));
  }, [refreshSessions]);

  useEffect(() => {
    if (!selectedSession) {
      setDetail(null);
      return;
    }
    void refreshDetail(selectedSession.session_id).catch(error => setStatus(`加载详情失败: ${String(error.message || error)}`));
  }, [refreshDetail, selectedSession]);

  useEffect(() => {
    if (!interactive) {
      return undefined;
    }
    const timer = setInterval(() => {
      void refreshSessions().then(next => {
        const session = next[selected];
        if (session) {
          return refreshDetail(session.session_id);
        }
        return undefined;
      }).catch(() => undefined);
    }, taskMode || selectedSession?.status === 'running' ? 500 : 1500);
    return () => clearInterval(timer);
  }, [interactive, refreshDetail, refreshSessions, selected, selectedSession?.status, taskMode]);

  useEffect(() => {
    setSlashSelected(0);
  }, [input]);

  const submit = useCallback(async () => {
    const parsed = parseCommand(input);
    setInput('');
    if (!parsed) {
      return;
    }
    if ('view' in parsed) {
      setView(parsed.view);
      setTaskMode(false);
      if (parsed.view === 'models') {
        setBusy(true);
        try {
          await listModels();
          setModels(await testModels());
          setStatus('模型状态已刷新');
        } catch (error) {
          setStatus(`模型状态失败: ${String((error as Error).message || error)}`);
        } finally {
          setBusy(false);
        }
      }
      return;
    }
    if (!parsed.request) {
      setStatus('任务不能为空');
      return;
    }
    const runOptions = {
      ...parsed,
      execute: true,
      strategy: parsed.strategy ?? mode,
      simulate: parsed.simulate || (!parsed.execute && process.env.AEGIS_TUI_DEFAULT_SIMULATE === '1')
    };
    setBusy(true);
    setStartupEvents([{stage: 'bootstrap', message: 'preparing task startup'}]);
    setStatus('正在启动任务...');
    try {
      const result = await startTaskStreaming(parsed.request, runOptions, {
        onProgress: payload => {
          const stage = String(payload.stage ?? 'progress');
          const message = startupMessage(payload);
          setStartupEvents(current => [...current, {stage, message}].slice(-10));
          setStatus(`启动中: ${message}`);
        },
        onStarted: payload => {
          setView('main');
          setTaskMode(true);
          setStatus(`任务已启动: ${payload.session.session_id}`);
          setStartupEvents([]);
          void refreshSessions().then(next => {
            const index = next.findIndex(session => session.session_id === payload.session.session_id);
            if (index >= 0) {
              setSelected(index);
            }
            return refreshDetail(payload.session.session_id);
          }).catch(error => setStatus(`加载任务失败: ${String((error as Error).message || error)}`));
        },
        onFinished: payload => {
          setStatus(payload.result.executed ? `执行完成: ${payload.result.session.session_id}` : `计划已创建: ${payload.result.session.session_id}`);
          setStartupEvents([]);
        },
        onError: error => {
          setStatus(`任务失败: ${String(error.message || error)}`);
        }
      });
      const next = await refreshSessions();
      const index = next.findIndex(session => session.session_id === result.session.session_id);
      if (index >= 0) {
        setSelected(index);
        await refreshDetail(result.session.session_id);
      }
    } catch (error) {
      setStatus(`任务失败: ${String((error as Error).message || error)}`);
    } finally {
      setBusy(false);
    }
  }, [input, refreshDetail, refreshSessions]);

  useInput((inputKey, key) => {
    if (suggestions.length > 0) {
      if (key.upArrow) {
        setSlashSelected(current => Math.max(0, current - 1));
        return;
      }
      if (key.downArrow) {
        setSlashSelected(current => Math.min(suggestions.length - 1, current + 1));
        return;
      }
      if (key.return) {
        const command = suggestions[slashSelected] ?? suggestions[0];
        setInput(command.view ? command.name : `${command.name} `);
        setSlashSelected(0);
        return;
      }
    }
    if (key.return && input.trim()) {
      void submit();
      return;
    }
    if (input) {
      return;
    }
    if (key.tab) {
      setMode(current => nextMode(current));
      return;
    }
    if (inputKey === 'q') {
      exit();
    } else if ((key.upArrow || inputKey === 'k') && view === 'sessions') {
      setTaskMode(false);
      setSelected(current => Math.max(0, current - 1));
    } else if ((key.downArrow || inputKey === 'j') && view === 'sessions') {
      setTaskMode(false);
      setSelected(current => Math.min(Math.max(sessions.length - 1, 0), current + 1));
    } else if (inputKey === 'b') {
      setView('main');
      setTaskMode(false);
    }
  }, {isActive: interactive});

  return (
    <Box flexDirection="column" paddingX={1}>
      <Box justifyContent="space-between" marginBottom={1}>
        <Text bold color="cyan">AEGIS v2</Text>
        <Text color={busy ? 'yellow' : 'gray'}>{status}</Text>
      </Box>
      {view === 'models' ? (
        <ModelView health={models} />
      ) : view === 'sessions' ? (
        <>
          {!taskMode && busy && <StartupPanel events={startupEvents} />}
          <SessionList sessions={sessions} selected={selected} />
          <DetailPanel detail={detail} />
        </>
      ) : (
        <>
          {!taskMode && busy && <StartupPanel events={startupEvents} />}
          {!taskMode && !busy && <WelcomePanel />}
          {taskMode && <TaskPanel detail={detail} />}
        </>
      )}
      <SlashCommandMenu input={input} selected={slashSelected} />
      <InputBar value={input} busy={busy} interactive={interactive} mode={mode} onChange={setInput} onSubmit={() => undefined} />
      <Box marginTop={1}>
        <Text color="gray">直接输入任务回车启动；Tab 切换模式；默认 MOA 专家模式；/session 会话；/models 模型状态；b 返回；q 退出</Text>
      </Box>
    </Box>
  );
}

const interactive = Boolean(process.stdin.isTTY && process.stdout.isTTY);
let altScreenActive = false;

const restoreAltScreen = () => {
  if (!altScreenActive || !interactive) {
    return;
  }
  process.stdout.write(ALT_SCREEN_DISABLE);
  altScreenActive = false;
};

if (interactive) {
  process.stdout.write(ALT_SCREEN_ENABLE);
  altScreenActive = true;
  process.once('exit', restoreAltScreen);
}

render(<App interactive={interactive} />, {
  exitOnCtrlC: true
});
