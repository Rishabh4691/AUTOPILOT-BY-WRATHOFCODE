import { useCallback, useEffect, useRef, useState } from 'react'
import { get, mmss, money, useNow, useOperator, useStream } from './api'
import AgentCard from './AgentCard'
import RfqList from './RfqList'
import RfqDetail from './RfqDetail'
import Claims from './Claims'
import Controls from './Controls'
import Lessons from './Lessons'
import Network from './Network'
import Overview from './Overview'
import { useT, useTheme } from './prefs'
import Shipments from './Shipments'
import SiteFooter from './SiteFooter'
import Intro from './Intro'
import Features from './Features'
import Scoreboard from './Scoreboard'

function Summary({ s }) {
  const booked = s?.booked?.length ? s.booked.map((b) => money(b.total, b.currency)).join(' + ') : '—'
  const items = [
    ['RFQs', s?.rfqs ?? '—'],
    ['Quoted', s ? `${s.quoted}${s.quoted ? ` (${s.under_2min} < 2 min)` : ''}` : '—'],
    ['Failed', s?.failed ?? '—', s?.failed > 0],
    ['Median time', mmss(s?.median_s)],
    ['Model / quote', s?.llm_per_quote != null ? `$${s.llm_per_quote.toFixed(5)}` : '—'],
    ['Booked value', booked],
  ]
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 xl:grid-cols-6">
      {items.map(([k, v, bad]) => (
        <div key={k} className="min-w-0 border-l border-line pl-4">
          <div className={`truncate text-xl font-light tracking-tight sm:text-2xl ${bad ? 'text-rose-400' : 'text-white'}`}>{v}</div>
          <div className="mt-1 text-[12px] text-muted">{k}</div>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const t = useT()
  useTheme()
  const query = new URLSearchParams(window.location.search)
  const deepLink = query.has('tab') || query.has('open')
  const [tab, setTab] = useState(query.get('tab') || 'overview')
  const [agents, setAgents] = useState([])
  const [rfqs, setRfqs] = useState([])
  const [sum, setSum] = useState(null)
  const [open, setOpen] = useState(query.get('open'))
  const [tick, setTick] = useState(0)
  const [alarm, setAlarm] = useState(null)
  const [fake, setFake] = useState(false)
  const [down, setDown] = useState(false)
  const [operator] = useOperator()
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

  useStream(
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
    ['overview', t('overview')],
    ['board', t('board')],
    ['network', t('network')],
    ['shipments', t('shipments')],
    ['claims', t('claims')],
    ['agents', t('agents')],
    ['rfqs', `${t('rfqs')} (${rfqs.length})`],
    ['lessons', t('lessons')],
  ]

  const enter = (k) => {
    if (k) setTab(k)
    document.getElementById('app')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <>
    {!deepLink && (
      <>
        <Intro onTour={() => document.getElementById('features')?.scrollIntoView({ behavior: 'smooth', block: 'start' })} onLeaderboard={() => enter('board')} />
        <Features />
      </>
    )}
    <div id="app" className="mx-auto max-w-7xl scroll-mt-4 px-4 pb-16 sm:px-6">
      <header className="app-header sticky top-3 z-40 mt-4 flex items-center gap-4 rounded-full border border-line bg-panel/90 py-2 pr-2 pl-5 backdrop-blur pill-shadow">
        <div className="flex shrink-0 items-center gap-2.5">
          <span className="font-display text-[16px] text-white">AUTOPILOT</span>
        </div>
        <nav className="app-tabs flex min-w-0 flex-1 gap-0.5 overflow-x-auto [scrollbar-width:none]">
          {tabs.map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-current={tab === k ? 'page' : undefined}
              onClick={() => setTab(k)}
              className={`shrink-0 cursor-pointer rounded-full px-3.5 py-2 text-[12.5px] font-medium uppercase tracking-[0.02em] transition-colors duration-200 ${tab === k ? 'bg-sky-500/15 text-sky-300' : 'text-zinc-300 hover:bg-sky-500/8 hover:text-white'}`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 text-xs">
        <p className="text-muted">{t('tagline')}</p>
        <div className="flex flex-wrap items-center gap-3">
          <Controls />
          {fake && <span className="rounded-full bg-sky-500/10 px-2.5 py-1 text-sky-300">{t('demo')}</span>}
        </div>
      </div>

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

      {tab !== 'overview' && <div className="mt-8"><Summary s={sum} /></div>}

      <div className="mb-8" />

      {tab === 'overview' ? (
        <Overview sum={sum} onOpen={(k) => { setTab(k); window.scrollTo({ top: 0 }) }} />
      ) : tab === 'board' ? (
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
    <SiteFooter onOpen={setTab} />
    </>
  )
}
