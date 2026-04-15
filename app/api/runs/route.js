import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, resolve } from 'path';

const IS_STATIC = process.env.DATA_MODE === 'static';

function getDataPath() {
  const candidates = [
    join(process.cwd(), 'data', 'runs.json'),
    resolve('.', 'data', 'runs.json'),
    join('/var/task', 'data', 'runs.json'),
  ];
  for (const p of candidates) {
    if (existsSync(p)) return p;
  }
  return candidates[0];
}

function loadRuns() {
  const dataFile = getDataPath();
  const dataDir = join(dataFile, '..');
  if (!existsSync(dataDir)) {
    try { mkdirSync(dataDir, { recursive: true }); } catch {}
  }
  if (!existsSync(dataFile)) return [];
  try {
    return JSON.parse(readFileSync(dataFile, 'utf-8'));
  } catch {
    return [];
  }
}

function saveRuns(runs) {
  const dataFile = getDataPath();
  const dataDir = join(dataFile, '..');
  if (!existsSync(dataDir)) {
    try { mkdirSync(dataDir, { recursive: true }); } catch {}
  }
  writeFileSync(dataFile, JSON.stringify(runs, null, 2));
}

const ALLOWED_FIELDS = [
  'id', 'tool', 'task', 'time', 'status', 'workspace',
  'mode', 'linesAdded', 'linesRemoved', 'filesChanged',
  'contextUsagePercent', 'subtitle',
];

function pickFields(obj) {
  const out = {};
  for (const key of ALLOWED_FIELDS) {
    if (obj[key] !== undefined) out[key] = obj[key];
  }
  return out;
}

export async function GET() {
  return Response.json({ runs: loadRuns() });
}

export async function POST(request) {
  if (IS_STATIC) {
    return Response.json({ error: 'Read-only mode (Vercel deployment)' }, { status: 405 });
  }

  try {
    const body = await request.json();
    const incoming = Array.isArray(body) ? body : [body];
    const runs = loadRuns();

    for (const run of incoming) {
      if (!run.tool || !run.task) {
        return Response.json({ error: 'tool and task are required' }, { status: 400 });
      }

      const idx = runs.findIndex(r => r.id === run.id);
      if (idx !== -1) {
        runs[idx] = { ...runs[idx], ...pickFields(run) };
      } else {
        runs.push({
          id: run.id || crypto.randomUUID().slice(0, 8),
          tool: run.tool,
          task: run.task,
          time: run.time || new Date().toISOString(),
          status: run.status || 'running',
          workspace: run.workspace || null,
          mode: run.mode || null,
          linesAdded: run.linesAdded ?? null,
          linesRemoved: run.linesRemoved ?? null,
          filesChanged: run.filesChanged ?? null,
          contextUsagePercent: run.contextUsagePercent ?? null,
          subtitle: run.subtitle || null,
        });
      }
    }

    saveRuns(runs);
    return Response.json({ ok: true, count: runs.length });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 400 });
  }
}

export async function DELETE(request) {
  if (IS_STATIC) {
    return Response.json({ error: 'Read-only mode (Vercel deployment)' }, { status: 405 });
  }

  const { searchParams } = new URL(request.url);
  const id = searchParams.get('id');
  let runs = loadRuns();

  if (id) {
    runs = runs.filter(r => r.id !== id);
  } else {
    runs = [];
  }

  saveRuns(runs);
  return Response.json({ ok: true });
}
