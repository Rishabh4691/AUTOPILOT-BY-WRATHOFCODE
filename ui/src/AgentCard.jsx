import { ago, secs } from './api'

const LIGHTS = {
  green: ['bg-emerald-400', 'Running'],
  busy: ['bg-sky-400 blip', 'Working'],
  red: ['bg-rose-500 blip', 'Failing'],
  idle: ['bg-amber-400', 'Idle'],
  off: ['bg-zinc-600', 'Not started'],
}

function Stat({ label, value }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-0.5 font-mono text-sm text-zinc-100">{value}</div>
    </div>
  )
}

function Score({ value }) {
  const pct = value ?? 0
  const color = pct >= 80 ? 'bg-emerald-400' : pct >= 50 ? 'bg-amber-400' : 'bg-rose-500'
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-wider text-muted">Productivity</span>
        <span className="font-mono text-lg font-semibold text-white">{value ?? '—'}</span>
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-line">
        <div className={`h-full rounded-full ${color} transition-all duration-700`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function AgentCard({ a, now, onOpen }) {
  const [dot, label] = LIGHTS[a.light] ?? LIGHTS.off
  const red = a.light === 'red'

  return (
    <div className={`flex flex-col gap-4 rounded-xl border bg-panel p-5 ${red ? 'border-rose-500/50' : 'border-line'}`}>
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">{a.label}</h3>
          <p className="text-xs text-muted">{a.role}</p>
        </div>
        <span className="flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-[11px] text-zinc-300">
          <span className={`h-2 w-2 rounded-full ${dot}`} />
          {label}
        </span>
      </div>

      <button
        onClick={() => a.now_rfq && onOpen(a.now_rfq)}
        className={`min-h-12 rounded-lg bg-ink/60 px-3 py-2 text-left text-sm ${a.now_rfq ? 'hover:bg-ink cursor-pointer' : 'cursor-default'}`}
      >
        <div className="truncate text-zinc-200">{a.now}</div>
        <div className="mt-0.5 font-mono text-[11px] text-muted">
          {a.now_rfq ?? ''} {a.last_ts ? `· ${ago(a.last_ts, now)}` : ''}
        </div>
      </button>

      <div className="grid grid-cols-2 gap-3">
        <Stat label="Tasks done" value={a.tasks_done} />
        <Stat label="Success" value={a.tasks_done ? `${Math.round(a.success_rate * 100)}%` : '—'} />
        <Stat label="Avg time" value={secs(a.avg_ms)} />
        <Stat label="Model cost" value={`$${a.llm_cost_usd.toFixed(4)}`} />
      </div>

      <Score value={a.productivity} />
    </div>
  )
}
