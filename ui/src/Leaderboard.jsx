import { useEffect, useState } from 'react'
import { ArrowLeft, Crown, Medal } from 'lucide-react'
import { clock, get } from './api'
import PageBackdrop from './PageBackdrop'
import { useLang } from './prefs'

const COPY = {
  en: {
    home: 'Home',
    live: 'Live',
    updated: 'updated',
    eyebrow: 'START Hack Munich 2026 · 5U AI challenge',
    title: 'Leaderboard',
    sub: 'Every team, every point, live.',
    stats: ['Our rank', 'Points', 'Gap to #3', 'Accepted', 'Booked', 'Median answer'],
    podium: 'Top three',
    all: 'All teams',
    you: 'You',
    accepted: 'accepted',
    booked: 'booked',
    pts: 'pts',
    loading: 'Loading the live board…',
    down: 'Board unavailable',
  },
  de: {
    home: 'Start',
    live: 'Live',
    updated: 'aktualisiert',
    eyebrow: 'START Hack München 2026 · 5U AI Challenge',
    title: 'Rangliste',
    sub: 'Jedes Team, jeder Punkt, live.',
    stats: ['Unser Rang', 'Punkte', 'Abstand zu #3', 'Angenommen', 'Gebucht', 'Median-Antwort'],
    podium: 'Die ersten drei',
    all: 'Alle Teams',
    you: 'Wir',
    accepted: 'angenommen',
    booked: 'gebucht',
    pts: 'Pkt.',
    loading: 'Lade die Live-Rangliste…',
    down: 'Rangliste nicht erreichbar',
  },
}

const fmt = (n, d = 0) => (n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }))

function Podium({ team, place, us, c }) {
  const tall = place === 1 ? 'sm:pt-10 sm:pb-9' : place === 2 ? 'sm:pt-7 sm:pb-6' : 'sm:pt-5 sm:pb-5'
  const order = place === 1 ? 'sm:order-2' : place === 2 ? 'sm:order-1' : 'sm:order-3'
  return (
    <li
      className={`glass lb-rise relative flex flex-col items-center gap-2 rounded-[28px] px-5 py-6 text-center ${tall} ${order} ${us ? 'lb-us' : ''}`}
      style={{ animationDelay: `${place * 90}ms` }}
    >
      <span className={place === 1 ? 'text-accent' : 'text-zinc-400'}>
        {place === 1 ? <Crown className="size-7" aria-hidden /> : <Medal className="size-6" aria-hidden />}
      </span>
      <span className={`font-display leading-none ${place === 1 ? 'lb-gold text-[64px]' : 'text-white text-[48px]'}`}>{place}</span>
      <span className="mt-1 max-w-full truncate text-lg font-semibold text-white">{team.team}</span>
      <span className="font-mono text-sm text-zinc-300">
        {fmt(team.total, 2)} {c.pts}
      </span>
      <span className="text-[12px] text-muted">
        {team.accepted}/{team.answered} {c.accepted} · {team.bookings} {c.booked}
      </span>
      {us && <span className="absolute top-3 right-3 rounded-full bg-accent px-2 py-0.5 text-[10px] font-bold uppercase text-[#0d0d0d]">{c.you}</span>}
    </li>
  )
}

/** The standalone leaderboard, opened from the home page. Refreshes every 10 s. */
export default function Leaderboard({ onHome }) {
  const [lang] = useLang()
  const c = COPY[lang] ?? COPY.en
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      get('/board')
        .then((x) => alive && (setD(x), setErr(null)))
        .catch((e) => alive && setErr(e.message))
    load()
    const t = setInterval(load, 10000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const ranking = d?.ranking ?? []
  const rounds = d?.rounds ?? []
  const top = ranking[0]?.total ?? 0
  const low = ranking.length ? Math.min(...ranking.map((r) => r.total)) : 0
  // Bars run from the lowest score to the leader, so close scores still look different.
  const bar = (v) => (top > low ? 8 + 92 * ((v - low) / (top - low)) : 100)
  const third = ranking.find((r) => r.rank === 3)
  const answered = rounds.filter((r) => r.seconds != null).map((r) => r.seconds).sort((a, b) => a - b)
  const median = answered.length ? answered[Math.floor(answered.length / 2)] : null
  const accepted = rounds.filter((r) => r.verdict === 'accepted').length
  const booked = rounds.filter((r) => r.booked === true).length
  const isUs = (t) => t.name === d?.team

  const stats = d
    ? [
        [`#${d.rank}`, d.rank <= 3],
        [fmt(d.total, 2)],
        [third && d.rank > 3 ? fmt(third.total - d.total, 1) : '—'],
        [`${accepted}/${rounds.length}`],
        [fmt(booked)],
        [median == null ? '—' : `${Math.round(median)} s`],
      ]
    : []

  return (
    <main className="relative isolate min-h-screen overflow-hidden px-4 pt-5 pb-24 sm:px-6">
      <PageBackdrop />

      <div className="mx-auto max-w-5xl">
        <div className="flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onHome}
            className="glass inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full px-5 text-sm font-semibold text-white transition-transform duration-200 hover:-translate-x-0.5"
          >
            <ArrowLeft className="size-4" aria-hidden /> {c.home}
          </button>
          <span className="glass inline-flex min-h-9 items-center gap-2 rounded-full px-4 text-[12px] text-zinc-300">
            <i className={`size-2 rounded-full ${err ? 'bg-rose-400' : 'blip bg-emerald-400'}`} aria-hidden />
            {err ? c.down : `${c.live}${d?.fetched_at ? ` · ${c.updated} ${clock(new Date(d.fetched_at).getTime() / 1000)}` : ''}`}
          </span>
        </div>

        <header className="mt-14 text-center sm:mt-20">
          <span className="glass inline-flex h-[30px] items-center gap-2 rounded-full px-3 text-[13px] text-zinc-300">
            <i className="size-1.5 rounded-full bg-accent shadow-[0_0_10px_var(--color-accent)]" aria-hidden />
            {c.eyebrow}
          </span>
          <h1 className="lb-glow font-display mt-6 text-[clamp(3rem,11vw,7.5rem)] leading-[0.9]">{c.title}</h1>
          <p className="mt-4 font-serif text-xl text-zinc-300 italic">{c.sub}</p>
        </header>

        {!d ? (
          <p className="glass mx-auto mt-14 max-w-md rounded-3xl p-8 text-center text-zinc-300">{err ? `${c.down}: ${err}` : c.loading}</p>
        ) : (
          <>
            <dl className="glass lb-rise mt-12 grid grid-cols-2 gap-y-5 rounded-[28px] px-6 py-6 sm:grid-cols-3 lg:grid-cols-6">
              {stats.map(([value, good], i) => (
                <div key={c.stats[i]} className="min-w-0 text-center">
                  <dt className="text-[11px] tracking-[0.12em] text-muted uppercase">{c.stats[i]}</dt>
                  <dd className={`font-display mt-1 truncate text-[clamp(1.25rem,2.4vw,1.75rem)] ${i === 0 ? (good ? 'text-emerald-300' : 'text-accent') : 'text-white'}`}>{value}</dd>
                </div>
              ))}
            </dl>

            <section className="mt-14" aria-label={c.podium}>
              <h2 className="mb-5 text-center text-[11px] tracking-[0.18em] text-muted uppercase">{c.podium}</h2>
              <ol className="grid items-end gap-4 sm:grid-cols-3">
                {ranking.slice(0, 3).map((t) => (
                  <Podium key={t.name} team={t} place={t.rank} us={isUs(t)} c={c} />
                ))}
              </ol>
            </section>

            <section className="mt-14" aria-label={c.all}>
              <h2 className="mb-5 text-center text-[11px] tracking-[0.18em] text-muted uppercase">{c.all}</h2>
              <ol className="space-y-2.5">
                {ranking.map((t, i) => (
                  <li
                    key={t.name}
                    className={`glass lb-rise relative flex items-center gap-4 overflow-hidden rounded-2xl px-4 py-3 sm:px-5 ${isUs(t) ? 'lb-us' : ''}`}
                    style={{ animationDelay: `${Math.min(i, 14) * 40}ms` }}
                  >
                    <span
                      aria-hidden="true"
                      className={`absolute inset-y-0 left-0 -z-10 ${isUs(t) ? 'bg-accent/25' : 'bg-white/[0.06]'}`}
                      style={{ width: `${bar(t.total)}%` }}
                    />
                    <span className={`font-display w-8 shrink-0 text-center text-xl ${t.rank <= 3 ? 'text-accent' : 'text-zinc-400'}`}>{t.rank}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate font-semibold text-white">{t.team}</span>
                        {isUs(t) && <span className="shrink-0 rounded-full bg-accent px-2 py-0.5 text-[10px] font-bold uppercase text-[#0d0d0d]">{c.you}</span>}
                      </span>
                      <span className="block text-[12px] text-muted">
                        {t.accepted}/{t.answered} {c.accepted} · {t.bookings} {c.booked}
                      </span>
                    </span>
                    <span className="shrink-0 text-right font-mono text-sm text-white tabular-nums sm:text-base">{fmt(t.total, 2)}</span>
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </div>
    </main>
  )
}
