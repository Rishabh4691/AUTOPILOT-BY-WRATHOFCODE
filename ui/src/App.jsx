import { useCallback, useEffect, useRef, useState } from 'react'
import { get, mmss, money, useNow, useOperator, useStream } from './api'
import AgentCard from './AgentCard'
import RfqList from './RfqList'
import RfqDetail from './RfqDetail'
import Claims from './Claims'
import Controls from './Controls'
import Lessons from './Lessons'
import Network from './Network'
import { useT, useTheme } from './prefs'
import Shipments from './Shipments'
import Scoreboard from './Scoreboard'

function Summary({ s }) {
  const booked = s?.booked?.length ? s.booked.map((b) => money(b.total, b.currency)).join(' + ') : '—'
  const items = [
    ['RFQs', s?.rfqs ?? '—'],
    ['Quoted', s ? `${s.quoted}${s.quoted ? ` (${s.under_2min} < 2 min)` : ''}` : '—'],
    ['Failed', s?.failed ?? '—', s?.failed > 0],
    ['Median time', mmss(s?.median_s)],
    ['LLM / quote', s?.llm_per_quote != null ? `$${s.llm_per_quote.toFixed(5)}` : '—'],
    ['Booked value', booked],
  ]
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
      {items.map(([k, v, bad]) => (
        <div key={k} className="min-w-0 bg-panel px-4 py-3">
          <div className="text-[11px] uppercase tracking-wider text-muted">{k}</div>
          <div className={`mt-1 truncate font-mono text-lg ${bad ? 'text-rose-400' : 'text-white'}`}>{v}</div>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const t = useT()
  useTheme()
  const [tab, setTab] = useState('board')
  const [agents, setAgents] = useState([])
  const [rfqs, setRfqs] = useState([])
  const [sum, setSum] = useState(null)
  const [open, setOpen] = useState(null)
  const [tick, setTick] = useState(0)
  const [alarm, setAlarm] = useState(null)
  const [fake, setFake] = useState(false)
  const [down, setDown] = useState(false)
  const [operator, setOperator] = useOperator()
  const now = useNow()
  const timer = useRef()

  const load = useCallback(async () => {
    try {
      const [a, r, s] = await Promise.all([get('/agents'), get('/rfqs'), get('/summary')])
      setAgents(a)
      setRfqs(r)
      setSum(s)
      setDown(false)
      setTick((t) => t + 1)
    } catch {
      setDown(true)
    }
  }, [])

  useEffect(() => {
    load()
    get('/health').then((h) => setFake(h.fake)).catch(() => setDown(true))
    const slow = setInterval(load, 15000)
    return () => clearInterval(slow)
  }, [load])

  const live = useStream(
    (e) => {
      if (['fail', 'failed', 'error', 'hold'].includes(String(e.status).toLowerCase())) setAlarm(e)
      clearTimeout(timer.current)
      timer.current = setTimeout(load, 300)
    },
    load,
  )

  const show = (id) => {
    setOpen(id)
    setTab('rfqs')
  }

  const tabs = [
    ['board', t('board')],
    ['network', t('network')],
    ['shipments', t('shipments')],
    ['claims', t('claims')],
    ['agents', t('agents')],
    ['rfqs', `${t('rfqs')} (${rfqs.length})`],
    ['lessons', t('lessons')],
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
            <p className="text-xs text-muted">{t('tagline')}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <Controls />
          {fake && <span className="rounded-md bg-violet-500/15 px-2 py-1 text-violet-300">{t('demo')}</span>}
          <input
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            placeholder="Your name"
            maxLength={40}
            className="w-28 rounded-md border border-line bg-panel px-2 py-1 text-zinc-200 placeholder:text-muted focus:border-sky-500 focus:outline-none"
          />
          <span className="flex items-center gap-1.5 text-muted">
            <span className={`h-2 w-2 rounded-full ${down ? 'bg-rose-500' : live ? 'bg-emerald-400 blip' : 'bg-zinc-600'}`} />
            {down ? t('apiDown') : live ? t('live') : t('reconnecting')}
          </span>
        </div>
      </header>

      {down && (
        <div className="mb-5 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          Can't reach the API. Start it with <code className="font-mono">uvicorn api.main:app --port 8000</code> from the repo root.
        </div>
      )}

      {alarm && (
        <div className="mb-5 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm">
          <div className="min-w-0">
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

      <Summary s={sum} />

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

      {tab === 'board' ? (
        <Scoreboard />
      ) : tab === 'network' ? (
        <Network />
      ) : tab === 'shipments' ? (
        <Shipments />
      ) : tab === 'claims' ? (
        <Claims />
      ) : tab === 'lessons' ? (
        <Lessons />
      ) : tab === 'agents' ? (
        <>
        {agents.every((a) => !a.tasks_done) && (
          <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            No bot activity in this database. The bot writes to <code className="font-mono">data/app.db</code> on the laptop that runs it.
            Run the API there, or start this UI with <code className="font-mono">API_TARGET=http://&lt;bot-laptop-ip&gt;:8000 npm run dev</code>.
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          {agents.map((a) => <AgentCard key={a.agent} a={a} now={now} onOpen={show} />)}
        </div>
        </>
      ) : (
        <RfqList rfqs={rfqs} now={now} selected={open} onOpen={setOpen} />
      )}

      {open && <RfqDetail id={open} tick={tick} now={now} operator={operator} onClose={() => setOpen(null)} />}
    </div>
  )
}
