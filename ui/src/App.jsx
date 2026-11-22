import { useCallback, useEffect, useRef, useState } from 'react'
import { get, mmss, money, useNow, useOperator, useStream } from './api'
import AgentCard from './AgentCard'
import RfqList from './RfqList'
import RfqDetail from './RfqDetail'
import Claims from './Claims'
import SettingsDock from './SettingsDock'
import Lessons from './Lessons'
import Network from './Network'
import { useLang, useT, useTheme } from './prefs'
import Shipments from './Shipments'
import SiteFooter from './SiteFooter'
import Intro from './Intro'
import Leaderboard from './Leaderboard'
import PageBackdrop from './PageBackdrop'
import { ArrowLeft } from 'lucide-react'

const SUBS = {
  en: {
    network: 'Where customers ship, which airlines deliver, and where our price loses.',
    shipments: 'Every booking, from the yes to the arrival note.',
    claims: 'Lost or damaged cargo, filed with the airline the moment it is reported.',
    agents: 'Five agents, one request at a time. What each is doing right now.',
    rfqs: 'Every request, every mail, every price. Open one to see how it was answered.',
    lessons: 'Every lost round became a fix.',
  },
  de: {
    network: 'Wohin Kunden versenden, welche Airlines liefern und wo unser Preis verliert.',
    shipments: 'Jede Buchung, vom Ja bis zur Ankunftsnachricht.',
    claims: 'Verlorene oder beschädigte Fracht, sofort bei der Airline gemeldet.',
    agents: 'Fünf Agenten, eine Anfrage nach der anderen. Was jeder gerade tut.',
    rfqs: 'Jede Anfrage, jede Mail, jeder Preis. Öffnen, um die Antwort zu sehen.',
    lessons: 'Jede verlorene Runde wurde zu einem Fix.',
  },
}

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
    <dl className="glass lb-rise grid grid-cols-2 gap-y-5 rounded-[28px] px-6 py-6 sm:grid-cols-3 xl:grid-cols-6">
      {items.map(([k, v, bad]) => (
        <div key={k} className="min-w-0 text-center">
          <dt className="text-[11px] tracking-[0.12em] text-muted uppercase">{k}</dt>
          <dd className={`font-display mt-1 truncate text-[clamp(1.1rem,2vw,1.5rem)] ${bad ? 'text-rose-400' : 'text-white'}`}>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function App() {
  const t = useT()
  useTheme()
  const [lang] = useLang()
  const query = new URLSearchParams(window.location.search)
  const [tab, setTab] = useState(query.get('tab') || (query.has('open') ? 'rfqs' : 'overview'))
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
      const [a, r, s] = await Promise.all([get('/agents'), get('/rfqs?limit=1000'), get('/summary')])
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
    ['network', t('network')],
    ['shipments', t('shipments')],
    ['claims', t('claims')],
    ['agents', t('agents')],
    ['rfqs', `${t('rfqs')} (${rfqs.length})`],
    ['lessons', t('lessons')],
  ]

  // Home is just the intro and the footer; the Control Room shows once a screen is picked.
  const home = tab === 'overview'
  const enter = (k) => {
    setTab(k)
    window.scrollTo({ top: 0 })
  }

  return (
    <>
    {home && <Intro onTour={() => enter('network')} onLeaderboard={() => enter('board')} />}
    {tab === 'board' && <Leaderboard onHome={() => enter('overview')} />}
    {!home && tab !== 'board' && (
    <main id="app" className="glass-page relative isolate min-h-screen px-4 pt-2 pb-24 sm:px-6">
      <PageBackdrop />
      <div className="mx-auto max-w-7xl">
      <header className="glass-header sticky top-0 z-40 -mx-4 flex items-center gap-3 px-4 pt-3 pb-6 sm:-mx-6 sm:px-6">
        <button
          type="button"
          onClick={() => enter('overview')}
          className="glass inline-flex min-h-11 shrink-0 cursor-pointer items-center gap-2 rounded-full px-4 text-sm font-semibold text-white transition-transform duration-200 hover:-translate-x-0.5 sm:px-5"
        >
          <ArrowLeft className="size-4" aria-hidden /> <span className="hidden sm:inline">{lang === 'de' ? 'Start' : 'Home'}</span>
        </button>
        <nav className="glass app-tabs flex min-w-0 flex-1 gap-1 overflow-x-auto rounded-full p-1.5 [scrollbar-width:none]">
          {tabs.map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-current={tab === k ? 'page' : undefined}
              onClick={() => enter(k)}
              className={`shrink-0 cursor-pointer rounded-full px-4 py-2 text-[13px] font-semibold transition-colors duration-200 ${tab === k ? 'text-[#0d0d0d]' : 'text-zinc-300 hover:bg-white/[0.08] hover:text-white'}`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      <div className="mt-14 text-center sm:mt-16">
        <span className="glass inline-flex h-[30px] items-center gap-2 rounded-full px-3 text-[13px] text-zinc-300">
          <i className="size-1.5 rounded-full bg-accent shadow-[0_0_10px_var(--color-accent)]" aria-hidden />
          {t('tagline')}
          {fake && <span className="text-accent">· {t('demo')}</span>}
        </span>
        <h1 className="lb-glow font-display mt-6 text-[clamp(2.6rem,9vw,6.5rem)] leading-[0.92]">{tabs.find(([k]) => k === tab)?.[1].replace(/ \(\d+\)$/, '')}</h1>
        <p className="mx-auto mt-4 max-w-2xl font-serif text-lg text-zinc-300 italic sm:text-xl">{(SUBS[lang] ?? SUBS.en)[tab]}</p>
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

      <div className="mt-12"><Summary s={sum} /></div>

      <div className="mb-10" />

      {tab === 'network' ? (
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
    </main>
    )}
    <SiteFooter onOpen={enter} />
    <SettingsDock />
    </>
  )
}
