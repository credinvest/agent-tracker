'use client';
import { useState, useEffect } from 'react';

const TOOLS = { claude: 'Claude', cursor: 'Cursor' };
const STATUSES = ['running', 'idle', 'done', 'failed'];
const STATUS_COLORS = { running: '#2ecc71', idle: '#f1c40f', done: '#6b7280', failed: '#e74c3c' };
const MODE_COLORS = { agent: 'bg-purple-500/20 text-purple-300', chat: 'bg-sky-500/20 text-sky-300', plan: 'bg-amber-500/20 text-amber-300' };

function clamp(min, max, v) { return Math.min(max, Math.max(min, v)); }

function localDateStr(date) {
  const d = date || new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function computeComplexity(r) {
  if (!r.linesAdded && !r.linesRemoved && !r.filesChanged && !r.contextUsagePercent) return null;
  return Math.round(clamp(0, 100,
    ((r.linesAdded || 0) + (r.linesRemoved || 0)) * 0.3
    + (r.filesChanged || 0) * 8
    + (r.contextUsagePercent || 0) * 0.4
  ));
}

function effortColor(v) {
  if (v == null) return 'bg-gray-700';
  if (v < 30) return 'bg-emerald-500';
  if (v < 60) return 'bg-amber-500';
  return 'bg-red-500';
}

export default function Dashboard() {
  const [runs, setRuns] = useState([]);
  const [filter, setFilter] = useState('all');
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState({ tool: 'cursor', task: '', time: '', status: 'running' });

  useEffect(() => {
    loadRuns();
    const interval = setInterval(loadRuns, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (runs.length > 0) saveToIDB(runs);
  }, [runs]);

  async function loadRuns() {
    try {
      const res = await fetch('/api/runs');
      const data = await res.json();
      if (data.runs?.length > 0) {
        setRuns(prev => mergeRuns(prev, data.runs));
        return;
      }
    } catch {}
    const local = await loadFromIDB();
    if (local?.length > 0) setRuns(local);
  }

  function mergeRuns(existing, incoming) {
    const map = new Map();
    existing.forEach(r => map.set(r.id, r));
    incoming.forEach(r => map.set(r.id, { ...map.get(r.id), ...r }));
    return Array.from(map.values());
  }

  async function addRun() {
    if (!form.task.trim()) return;
    const run = {
      id: crypto.randomUUID().slice(0, 8),
      tool: form.tool,
      task: form.task.trim(),
      time: form.time || new Date().toISOString().slice(0, 16),
      status: form.status,
    };
    setRuns(prev => [run, ...prev]);
    setShowModal(false);
    setForm({ tool: 'cursor', task: '', time: '', status: 'running' });
    try { await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(run) }); } catch {}
  }

  async function updateStatus(id, status) {
    setRuns(prev => prev.map(r => r.id === id ? { ...r, status } : r));
    try { await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, status }) }); } catch {}
  }

  async function deleteRun(id) {
    setRuns(prev => prev.filter(r => r.id !== id));
    try { await fetch(`/api/runs?id=${id}`, { method: 'DELETE' }); } catch {}
  }

  function exportData() {
    const blob = new Blob([JSON.stringify(runs, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `agent-tracker-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
  }

  function importData(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result);
        if (Array.isArray(data)) {
          setRuns(prev => mergeRuns(prev, data));
          fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).catch(() => {});
        }
      } catch { alert('Invalid JSON'); }
    };
    reader.readAsText(file);
    e.target.value = '';
  }

  // Stats
  const today = localDateStr();
  const todayRuns = runs.filter(r => r.time?.slice(0, 10) === today);
  const running = runs.filter(r => r.status === 'running').length;
  const claudeTotal = runs.filter(r => r.tool === 'claude').length;
  const cursorTotal = runs.filter(r => r.tool === 'cursor').length;

  // Complexity stats
  const complexities = runs.map(computeComplexity).filter(c => c != null);
  const avgComplexity = complexities.length > 0 ? Math.round(complexities.reduce((a, b) => a + b, 0) / complexities.length) : 0;
  const peakComplexity = complexities.length > 0 ? Math.max(...complexities) : 0;
  const todayComplexities = todayRuns.map(computeComplexity).filter(c => c != null);
  const todayAvg = todayComplexities.length > 0 ? Math.round(todayComplexities.reduce((a, b) => a + b, 0) / todayComplexities.length) : 0;

  // Chart data - last 7 days
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    days.push(localDateStr(d));
  }
  const maxDay = Math.max(1, ...days.map(d => runs.filter(r => r.time?.slice(0, 10) === d).length));

  // Filtered table
  let filtered = [...runs];
  if (filter === 'claude' || filter === 'cursor') filtered = filtered.filter(r => r.tool === filter);
  else if (filter === 'running' || filter === 'idle') filtered = filtered.filter(r => r.status === filter);
  filtered.sort((a, b) => (b.time || '').localeCompare(a.time || ''));

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="px-8 py-5 border-b border-[#2e3345] flex justify-between items-center flex-wrap gap-3">
        <h1 className="text-xl font-semibold m-0">
          <span className="text-[#6c63ff]">Agent</span> Tracker
        </h1>
        <div className="flex gap-2">
          <button onClick={exportData} className="px-4 py-2 rounded-lg border border-[#2e3345] bg-[#1a1d27] text-sm hover:bg-[#242834] transition-colors">Export</button>
          <label className="px-4 py-2 rounded-lg border border-[#2e3345] bg-[#1a1d27] text-sm cursor-pointer hover:bg-[#242834] transition-colors">
            Import<input type="file" accept=".json" className="hidden" onChange={importData} />
          </label>
          <button
            onClick={() => { setForm(f => ({ ...f, time: new Date().toISOString().slice(0, 16) })); setShowModal(true); }}
            className="px-4 py-2 rounded-lg bg-[#6c63ff] text-white text-sm font-medium hover:bg-[#5b54e6] transition-colors"
          >+ Add Run</button>
        </div>
      </header>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 p-6 px-8">
        <StatCard label="Today" value={todayRuns.length} sub={`${todayRuns.filter(r => r.tool === 'claude').length}C / ${todayRuns.filter(r => r.tool === 'cursor').length}Cu`} />
        <StatCard label="Running" value={running} color="text-emerald-400" sub="Active now" />
        <StatCard label="Claude" value={claudeTotal} color="text-[#9b94ff]" sub="Total sessions" />
        <StatCard label="Cursor" value={cursorTotal} color="text-teal-400" sub="Total runs" />
        <StatCard label="All Time" value={runs.length} sub="Total tracked" />
        <StatCard label="Avg Effort" value={avgComplexity} color="text-amber-400" sub={`Peak: ${peakComplexity}`} />
      </div>

      {/* Charts + Complexity Gauge row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mx-8 mb-5">
        {/* 7-Day Activity */}
        <div className="lg:col-span-2 bg-[#1a1d27] border border-[#2e3345] rounded-xl">
          <div className="px-5 py-4 border-b border-[#2e3345]">
            <h2 className="text-sm font-semibold">7-Day Activity</h2>
          </div>
          <div className="p-5">
            <div className="flex items-end gap-2 h-40">
              {days.map(d => {
                const dr = runs.filter(r => r.time?.slice(0, 10) === d);
                const c = dr.filter(r => r.tool === 'claude').length;
                const cu = dr.filter(r => r.tool === 'cursor').length;
                const hC = (c / maxDay) * 130;
                const hCu = (cu / maxDay) * 130;
                const label = new Date(d + 'T12:00').toLocaleDateString('en', { weekday: 'short', day: 'numeric' });
                return (
                  <div key={d} className="flex-1 flex flex-col items-center gap-1">
                    <span className="text-[10px] text-gray-500">{c + cu || ''}</span>
                    <div className="flex flex-col justify-end w-full max-w-11 gap-0.5" style={{ height: 140 }}>
                      {cu > 0 && <div className="rounded-t bg-teal-400 min-h-[2px] transition-all duration-300" style={{ height: hCu }} title={`${cu} Cursor`} />}
                      {c > 0 && <div className="rounded-t bg-[#6c63ff] min-h-[2px] transition-all duration-300" style={{ height: hC }} title={`${c} Claude`} />}
                    </div>
                    <span className="text-[10px] text-gray-500">{label}</span>
                  </div>
                );
              })}
            </div>
            <div className="flex gap-4 mt-3">
              <span className="flex items-center gap-1.5 text-xs text-gray-500"><span className="w-2.5 h-2.5 rounded-sm bg-[#6c63ff] inline-block" /> Claude</span>
              <span className="flex items-center gap-1.5 text-xs text-gray-500"><span className="w-2.5 h-2.5 rounded-sm bg-teal-400 inline-block" /> Cursor</span>
            </div>
          </div>
        </div>

        {/* Complexity Gauge */}
        <div className="bg-[#1a1d27] border border-[#2e3345] rounded-xl">
          <div className="px-5 py-4 border-b border-[#2e3345]">
            <h2 className="text-sm font-semibold">Effort Overview</h2>
          </div>
          <div className="p-5 flex flex-col items-center justify-center h-[calc(100%-52px)]">
            <RadialGauge value={todayAvg} label="Today Avg" />
            <div className="grid grid-cols-2 gap-4 w-full mt-5">
              <div className="text-center">
                <div className="text-2xl font-bold text-[#e2e4eb]">{avgComplexity}</div>
                <div className="text-[10px] text-gray-500 uppercase tracking-wide">All-time Avg</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-red-400">{peakComplexity}</div>
                <div className="text-[10px] text-gray-500 uppercase tracking-wide">Peak</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="bg-[#1a1d27] border border-[#2e3345] rounded-xl mx-8 mb-8">
        <div className="px-5 py-4 border-b border-[#2e3345] flex justify-between items-center flex-wrap gap-2">
          <h2 className="text-sm font-semibold">All Runs</h2>
          <div className="flex gap-1.5">
            {['all', 'claude', 'cursor', 'running', 'idle'].map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded-full text-xs border transition-colors ${
                  filter === f
                    ? 'bg-[#6c63ff] border-[#6c63ff] text-white'
                    : 'border-[#2e3345] text-gray-500 hover:text-gray-300 hover:border-gray-600'
                }`}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="text-left px-4 py-2.5 text-[11px] text-gray-500 uppercase tracking-wider border-b border-[#2e3345] font-medium">Tool</th>
                <th className="text-left px-4 py-2.5 text-[11px] text-gray-500 uppercase tracking-wider border-b border-[#2e3345] font-medium">Task</th>
                <th className="text-left px-4 py-2.5 text-[11px] text-gray-500 uppercase tracking-wider border-b border-[#2e3345] font-medium">Mode</th>
                <th className="text-left px-4 py-2.5 text-[11px] text-gray-500 uppercase tracking-wider border-b border-[#2e3345] font-medium">Effort</th>
                <th className="text-left px-4 py-2.5 text-[11px] text-gray-500 uppercase tracking-wider border-b border-[#2e3345] font-medium">Started</th>
                <th className="text-left px-4 py-2.5 text-[11px] text-gray-500 uppercase tracking-wider border-b border-[#2e3345] font-medium">Status</th>
                <th className="w-10 border-b border-[#2e3345]"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr><td colSpan={7} className="text-center text-gray-500 py-10">No runs yet. Click + Add Run or import data.</td></tr>
              )}
              {filtered.map(r => {
                const cx = computeComplexity(r);
                return (
                  <tr key={r.id} className="hover:bg-[#1e2130] transition-colors group">
                    <td className="px-4 py-3 text-sm border-b border-[#2e3345]/60">
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        r.tool === 'claude' ? 'bg-[#6c63ff]/15 text-[#9b94ff]' : 'bg-teal-500/15 text-teal-400'
                      }`}>
                        {TOOLS[r.tool] || r.tool}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm border-b border-[#2e3345]/60 max-w-md">
                      <div className="flex items-start gap-1.5">
                        <span className="flex-1 min-w-0">
                          <span className="block truncate">{r.task}</span>
                          {r.subtitle && <span className="block text-[11px] text-gray-600 mt-0.5 truncate">{r.subtitle}</span>}
                        </span>
                        {(r.link || r.workspacePath) && (
                          <a
                            href={r.link || `cursor://file/${r.workspacePath}`}
                            title={r.link ? `Open in ${r.tool === 'claude' ? 'Finder' : 'Cursor'}` : `Open workspace: ${r.workspacePath}`}
                            className="shrink-0 mt-0.5 text-gray-600 hover:text-[#6c63ff] transition-colors"
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                          </a>
                        )}
                      </div>
                      {(r.workspace || r.workspacePath) && (
                        <div className="mt-1">
                          <a
                            href={r.workspacePath ? `cursor://file/${r.workspacePath}` : undefined}
                            className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-[#242834] ${
                              r.workspacePath ? 'text-gray-400 hover:text-[#6c63ff] hover:bg-[#2e3345] cursor-pointer transition-colors' : 'text-gray-600'
                            }`}
                          >
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>
                            {r.workspace}
                          </a>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm border-b border-[#2e3345]/60">
                      {r.mode ? (
                        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${MODE_COLORS[r.mode] || 'bg-gray-500/20 text-gray-400'}`}>
                          {r.mode.charAt(0).toUpperCase() + r.mode.slice(1)}
                        </span>
                      ) : <span className="text-gray-600">--</span>}
                    </td>
                    <td className="px-4 py-3 text-sm border-b border-[#2e3345]/60">
                      <EffortBar value={cx} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 border-b border-[#2e3345]/60 whitespace-nowrap">
                      {r.time ? new Date(r.time).toLocaleString('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '--'}
                    </td>
                    <td className="px-4 py-3 text-sm border-b border-[#2e3345]/60">
                      <div className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full inline-block" style={{
                          background: STATUS_COLORS[r.status] || '#6b7280',
                          boxShadow: r.status === 'running' ? '0 0 6px #2ecc71' : 'none'
                        }} />
                        <select
                          value={r.status}
                          onChange={e => updateStatus(r.id, e.target.value)}
                          className="bg-[#242834] border border-[#2e3345] text-[#e2e4eb] rounded-md px-2 py-1 text-xs cursor-pointer"
                        >
                          {STATUSES.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
                        </select>
                      </div>
                    </td>
                    <td className="px-2 py-3 border-b border-[#2e3345]/60">
                      <button
                        onClick={() => deleteRun(r.id)}
                        className="text-gray-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 text-sm px-1"
                        title="Remove"
                      >x</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Run Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={e => { if (e.target === e.currentTarget) setShowModal(false); }}>
          <div className="bg-[#1a1d27] border border-[#2e3345] rounded-2xl p-7 w-[420px] max-w-[90vw]">
            <h3 className="text-base font-semibold mb-5">Add Agent Run</h3>
            <div className="mb-3.5">
              <label className="block text-xs text-gray-500 mb-1.5">Tool</label>
              <select className="w-full px-3 py-2 rounded-lg border border-[#2e3345] bg-[#242834] text-sm" value={form.tool} onChange={e => setForm(f => ({ ...f, tool: e.target.value }))}>
                <option value="claude">Claude (Cowork)</option>
                <option value="cursor">Cursor</option>
              </select>
            </div>
            <div className="mb-3.5">
              <label className="block text-xs text-gray-500 mb-1.5">Task Name</label>
              <input className="w-full px-3 py-2 rounded-lg border border-[#2e3345] bg-[#242834] text-sm" placeholder="e.g. Refactor auth module" value={form.task} onChange={e => setForm(f => ({ ...f, task: e.target.value }))} autoFocus />
            </div>
            <div className="mb-3.5">
              <label className="block text-xs text-gray-500 mb-1.5">Start Time</label>
              <input type="datetime-local" className="w-full px-3 py-2 rounded-lg border border-[#2e3345] bg-[#242834] text-sm" value={form.time} onChange={e => setForm(f => ({ ...f, time: e.target.value }))} />
            </div>
            <div className="mb-3.5">
              <label className="block text-xs text-gray-500 mb-1.5">Status</label>
              <select className="w-full px-3 py-2 rounded-lg border border-[#2e3345] bg-[#242834] text-sm" value={form.status} onChange={e => setForm(f => ({ ...f, status: e.target.value }))}>
                {STATUSES.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
              </select>
            </div>
            <div className="flex gap-2 justify-end mt-5">
              <button onClick={() => setShowModal(false)} className="px-4 py-2 rounded-lg border border-[#2e3345] bg-[#1a1d27] text-sm hover:bg-[#242834] transition-colors">Cancel</button>
              <button onClick={addRun} className="px-4 py-2 rounded-lg bg-[#6c63ff] text-white text-sm font-medium hover:bg-[#5b54e6] transition-colors">Add Run</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, color, sub }) {
  return (
    <div className="bg-[#1a1d27] border border-[#2e3345] rounded-xl p-5">
      <div className="text-[11px] text-gray-500 uppercase tracking-wider mb-2">{label}</div>
      <div className={`text-3xl font-bold ${color || 'text-[#e2e4eb]'}`}>{value}</div>
      <div className="text-xs text-gray-600 mt-1">{sub}</div>
    </div>
  );
}

function EffortBar({ value }) {
  if (value == null) return <span className="text-gray-600 text-xs">--</span>;
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 h-1.5 bg-[#242834] rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-300 ${effortColor(value)}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-[11px] text-gray-500 w-7 text-right">{value}</span>
    </div>
  );
}

function RadialGauge({ value, label }) {
  const radius = 50;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const color = value < 30 ? '#10b981' : value < 60 ? '#f59e0b' : '#ef4444';

  return (
    <div className="relative flex items-center justify-center">
      <svg width="130" height="130" viewBox="0 0 130 130" className="-rotate-90">
        <circle cx="65" cy="65" r={radius} fill="none" stroke="#242834" strokeWidth="10" />
        <circle
          cx="65" cy="65" r={radius} fill="none"
          stroke={color} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={circumference} strokeDashoffset={offset}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold" style={{ color }}>{value}</span>
        <span className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</span>
      </div>
    </div>
  );
}

// IndexedDB helpers
function getDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('agent-tracker', 1);
    req.onupgradeneeded = () => req.result.createObjectStore('runs');
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function saveToIDB(runs) {
  try {
    const db = await getDB();
    const tx = db.transaction('runs', 'readwrite');
    tx.objectStore('runs').put(runs, 'all');
  } catch {}
}
async function loadFromIDB() {
  try {
    const db = await getDB();
    return new Promise(resolve => {
      const tx = db.transaction('runs', 'readonly');
      const req = tx.objectStore('runs').get('all');
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => resolve([]);
    });
  } catch { return []; }
}
