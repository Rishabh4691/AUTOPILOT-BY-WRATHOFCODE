import { useCallback, useEffect, useRef, useState } from 'react'
import { get, money, useNow, useStream } from './api'
import AgentCard from './AgentCard'
import RfqList from './RfqList'
import RfqDetail from './RfqDetail'

function Summary({ rfqs, agents }) {
  const quoted = rfqs.filter((r) => r.quoted_at)
  const failed = rfqs.filter((r) => r.status === 'FAILED').length
  const times = quoted.map((r) => r.quoted_at - r.received_at).sort((a, b) => a - b)
  const median = times.length ? Math.round(times[Math.floor(times.length / 2)]) : null
  const cost = agents.reduce((s, a) => s + a.llm_cost_usd, 0)
  const items = [
    ['RFQs', rfqs.length],
    ['Quoted', quoted.length],
    ['Failed', failed],
    ['Median time', median == null ? '—' : `${Math.floor(median / 60)}:${String(median % 60).padStart(2, '0')}`],
    ['LLM / quote', quoted.length ? `$${(cost / quoted.length).toFixed(5)}` : '—'],
    ['Booked value', money(rfqs.filter((r) => r.status === 'BOOKED').reduce((s, r) => s + (r.total ?? 0), 0))],
  ]
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
      {items.map(([k, v]) => (
        <div key={k} className="bg-panel px-4 py-3">
          <div className="text-[11px] uppercase tracking-wider text-muted">{k}</div>
          <div className={`mt-1 font-mono text-lg ${k === 'Failed' && v ? 'text-rose-400' : 'text-white'}`}>{v}</div>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('agents')
  const [agents, setAgents] = useState([])
  const [rfqs, setRfqs] = useState([])
  const [open, setOpen] = useState(null)
  const [tick, setTick] = useState(0)
  const [alarm, setAlarm] = useState(null)
  const [fake, setFake] = useState(false)
  const now = useNow()
  const timer = useRef()

  const load = useCallback(() => {
    get('/agents').then(setAgents)
    get('/rfqs').then(setRfqs)
    setTick((t) => t + 1)
  }, [])

  useEffect(() => {
    load()
    get('/health').then((h) => setFake(h.fake))
  }, [load])

  const live = useStream((e) => {
    if (e.status === 'fail') setAlarm(e)
    clearTimeout(timer.current)
    timer.current = setTimeout(load, 300)
  })

  const show = (id) => {
    setOpen(id)
    setTab('rfqs')
  }

  const tabs = [
    ['agents', 'Agent Control Room'],
    ['rfqs', `RFQs (${rfqs.length})`],
  ]

  return (
    <div className="mx-auto max-w-7xl px-4 pb-16 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-4 py-6">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-sky-500/15 text-sky-300">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor"><path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z" /></svg>
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-white">AUTOPILOT</h1>
            <p className="text-xs text-muted">WRATHOFCODE · digital air forwarder</p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {fake && <span className="rounded-md bg-violet-500/15 px-2 py-1 text-violet-300">Demo data</span>}
          <span className="flex items-center gap-1.5 text-muted">
            <span className={`h-2 w-2 rounded-full ${live ? 'bg-emerald-400 blip' : 'bg-zinc-600'}`} />
            {live ? 'Live' : 'Reconnecting'}
          </span>
        </div>
      </header>

      {alarm && (
        <div className="mb-5 flex items-center justify-between gap-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm">
          <div>
            <span className="font-semibold text-rose-300">Failure · {alarm.agent}</span>
            <span className="ml-2 text-zinc-200">{alarm.message}</span>
            <span className="ml-2 text-xs text-muted">Something in the setup may have changed.</span>
          </div>
          <div className="flex shrink-0 gap-2">
            {alarm.rfq_id && (
              <button onClick={() => show(alarm.rfq_id)} className="rounded-md bg-rose-500 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-400">
                Open
              </button>
            )}
            <button onClick={() => setAlarm(null)} className="rounded-md px-3 py-1 text-xs text-muted hover:text-white">Dismiss</button>
          </div>
        </div>
      )}

      <Summary rfqs={rfqs} agents={agents} />

      <nav className="mt-8 mb-5 flex gap-1 border-b border-line">
        {tabs.map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${tab === k ? 'border-sky-400 text-white' : 'border-transparent text-muted hover:text-zinc-200'}`}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === 'agents' ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          {agents.map((a) => <AgentCard key={a.agent} a={a} now={now} onOpen={show} />)}
        </div>
      ) : (
        <RfqList rfqs={rfqs} now={now} selected={open} onOpen={setOpen} />
      )}

      {open && <RfqDetail id={open} tick={tick} now={now} onClose={() => setOpen(null)} />}
    </div>
  )
}
