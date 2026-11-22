import { ArrowRight, Bot, BookOpenCheck, Globe2, Inbox, MailCheck, PackageCheck, Plane, Radar, Scale, ShieldAlert, ShieldCheck, Trophy } from 'lucide-react'
import { mmss, money } from './api'
import { useLang } from './prefs'

const COPY = {
  en: {
    eyebrow: 'From inbox to booking',
    title: 'Every air freight request answered.',
    sub: 'No human in the loop.',
    lead: 'AUTOPILOT reads every mail, prices it in code, replies in the customer’s language, books on a yes and keeps the customer posted. Around the clock.',
    stats: ['Requests', 'Quoted', 'Median answer', 'Booked value'],
    howEyebrow: 'How it works',
    howTitle: ['One request,', 'seven steps, no hands.'],
    steps: [
      ['Read', 'Mail, attachments and voice notes in any language.'],
      ['Guard', 'Dangerous goods, limits, exclusions and phishing.'],
      ['Source', 'Rate sheets, portal, airline and trucker offers in parallel.'],
      ['Price', 'Chargeable weight, weight break, pickup and surcharges.'],
      ['Write', 'One model call; code sets every number.'],
      ['Book', 'A yes books by rate reference and confirms.'],
      ['Follow up', 'Tracking answers, daily updates and claims.'],
    ],
    roomEyebrow: 'Control Room',
    roomTitle: ['Everything the bot does,', 'in one place.'],
    open: 'Open',
    screens: {
      board: ['Scoreboard', 'Every round, its verdict and points, live from the 5U board.'],
      network: ['Network', 'Lanes on a world map, the airline league and price pressure.'],
      rfqs: ['Requests', 'Pipeline, price breakdown and the sent email per request.'],
      shipments: ['Shipments', 'Booked and delivered, with the updates sent.'],
      claims: ['Claims', 'Lost or damaged cargo, filed with the airline.'],
      agents: ['Agents', 'Current task, success, speed and model cost per agent.'],
      lessons: ['Lessons', 'Every lost round with its cause, fix and commit.'],
    },
  },
  de: {
    eyebrow: 'Vom Posteingang zur Buchung',
    title: 'Jede Luftfracht-Anfrage beantwortet.',
    sub: 'Ohne Menschen dazwischen.',
    lead: 'AUTOPILOT liest jede Mail, rechnet den Preis im Code, antwortet in der Sprache des Kunden, bucht bei einem Ja und hält den Kunden auf dem Laufenden. Rund um die Uhr.',
    stats: ['Anfragen', 'Angeboten', 'Mittlere Antwort', 'Gebuchter Wert'],
    howEyebrow: 'So funktioniert es',
    howTitle: ['Eine Anfrage,', 'sieben Schritte, keine Hände.'],
    steps: [
      ['Lesen', 'Mail, Anhänge und Sprachnachrichten in jeder Sprache.'],
      ['Prüfen', 'Gefahrgut, Limits, Ausschlüsse und Phishing.'],
      ['Beschaffen', 'Ratenblätter, Portal, Airline- und Trucker-Angebote parallel.'],
      ['Rechnen', 'Frachtgewicht, Gewichtsstufe, Abholung und Zuschläge.'],
      ['Schreiben', 'Ein Modellaufruf; jede Zahl setzt der Code.'],
      ['Buchen', 'Ein Ja bucht per Ratenreferenz und bestätigt.'],
      ['Begleiten', 'Tracking-Antworten, tägliche Updates und Schäden.'],
    ],
    roomEyebrow: 'Leitstand',
    roomTitle: ['Alles, was der Bot tut,', 'an einem Ort.'],
    open: 'Öffnen',
    screens: {
      board: ['Rangliste', 'Jede Runde mit Urteil und Punkten, live von der 5U-Rangliste.'],
      network: ['Netzwerk', 'Strecken auf der Weltkarte, Airline-Tabelle und Preisdruck.'],
      rfqs: ['Anfragen', 'Ablauf, Preisaufschlüsselung und gesendete Mail je Anfrage.'],
      shipments: ['Sendungen', 'Gebucht und zugestellt, mit den gesendeten Updates.'],
      claims: ['Schäden', 'Verlorene oder beschädigte Fracht, bei der Airline gemeldet.'],
      agents: ['Agenten', 'Aktuelle Aufgabe, Erfolg, Tempo und Modellkosten je Agent.'],
      lessons: ['Lektionen', 'Jede verlorene Runde mit Ursache, Fix und Commit.'],
    },
  },
}

const STEP_ICONS = [Inbox, ShieldCheck, Radar, Scale, MailCheck, PackageCheck, Plane]
const SCREENS = [
  ['board', Trophy],
  ['network', Globe2],
  ['rfqs', Inbox],
  ['shipments', PackageCheck],
  ['claims', ShieldAlert],
  ['agents', Bot],
  ['lessons', BookOpenCheck],
]

function Heading({ eyebrow, lines, light }) {
  return (
    <div>
      <span className={light ? 'eyebrow eyebrow-on-navy' : 'eyebrow'}>{eyebrow}</span>
      <h3 className={`mt-4 text-3xl leading-[1.1] font-medium tracking-[-0.02em] sm:text-4xl ${light ? 'text-[#f5f4f2]' : 'text-white'}`}>
        {lines[0]}
        <br />
        <span className="font-light">{lines[1]}</span>
      </h3>
    </div>
  )
}

export default function Overview({ sum, onOpen }) {
  const [lang] = useLang()
  const c = COPY[lang] ?? COPY.en
  const booked = sum?.booked?.length ? sum.booked.map((b) => money(b.total, b.currency)).join(' + ') : '—'
  const stats = [sum?.rfqs ?? '—', sum?.quoted ?? '—', mmss(sum?.median_s), booked]

  return (
    <div className="space-y-20 pb-8">
      <section className="grid gap-12 pt-6 lg:grid-cols-[1.25fr_1fr] lg:items-end">
        <div>
          <span className="eyebrow">{c.eyebrow}</span>
          <h2 className="mt-5 text-4xl leading-[1.06] font-medium tracking-[-0.025em] text-white sm:text-[56px]">
            {c.title}
            <br />
            <span className="font-light">{c.sub}</span>
          </h2>
          <p className="mt-6 max-w-xl text-base leading-relaxed text-zinc-300">{c.lead}</p>
          <button
            type="button"
            onClick={() => onOpen('board')}
            className="mt-8 inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full bg-accent px-6 text-[13px] font-medium tracking-[0.04em] text-[#fff] uppercase transition-colors duration-200 hover:bg-sky-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {c.screens.board[0]} <ArrowRight className="size-4" aria-hidden />
          </button>
        </div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-8">
          {c.stats.map((label, i) => (
            <div key={label} className="flex min-w-0 flex-col-reverse border-l border-line pl-5">
              <dt className="mt-2 text-[13px] text-muted">{label}</dt>
              <dd className="truncate text-3xl font-light tracking-tight text-white sm:text-4xl">{stats[i]}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section>
        <Heading eyebrow={c.howEyebrow} lines={c.howTitle} />
        <ol className="mt-10 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-7">
          {c.steps.map(([name, text], i) => {
            const Icon = STEP_ICONS[i]
            return (
              <li key={name} className="bg-panel p-5">
                <div className="flex items-center justify-between">
                  <span className="grid size-9 place-items-center rounded-lg bg-sky-500/12 text-sky-300">
                    <Icon className="size-[18px]" aria-hidden />
                  </span>
                  <span className="font-mono text-[11px] text-muted">0{i + 1}</span>
                </div>
                <div className="mt-4 text-[15px] font-medium text-white">{name}</div>
                <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{text}</p>
              </li>
            )
          })}
        </ol>
      </section>

      <section className="navy-band -mx-4 rounded-[28px] px-6 py-14 sm:-mx-6 sm:px-12">
        <Heading eyebrow={c.roomEyebrow} lines={c.roomTitle} light />
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {SCREENS.map(([key, Icon]) => {
            const [name, text] = c.screens[key]
            return (
              <button
                key={key}
                type="button"
                onClick={() => onOpen(key)}
                className={`${key === 'board' ? 'sm:col-span-2' : ''} group flex cursor-pointer flex-col rounded-2xl border border-[#ffffff1a] bg-[#ffffff0f] p-6 text-left transition-colors duration-200 hover:border-[#ffffff40] hover:bg-[#ffffff1a] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f08a66]`}
              >
                <span className="grid size-10 place-items-center rounded-xl bg-[#ffffff1a] text-[#f5f4f2]">
                  <Icon className="size-5" aria-hidden />
                </span>
                <span className="mt-5 text-lg font-medium text-[#f5f4f2]">{name}</span>
                <span className="mt-1.5 text-[14px] leading-relaxed text-[#c9cfdd]">{text}</span>
                <span className="mt-6 inline-flex items-center gap-1.5 text-[12px] font-medium tracking-[0.06em] text-[#f08a66] uppercase">
                  {c.open}
                  <ArrowRight className="size-3.5 transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
                </span>
              </button>
            )
          })}
        </div>
      </section>
    </div>
  )
}
