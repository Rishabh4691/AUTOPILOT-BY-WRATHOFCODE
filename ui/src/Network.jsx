import { useEffect, useMemo, useState } from 'react'
import { geoNaturalEarth1, geoPath } from 'd3-geo'
import { feature } from 'topojson-client'
import countries from 'world-atlas/countries-110m.json'
import { get, money } from './api'
import { useT } from './prefs'

const AIRPORTS = {
  FRA: [8.57, 50.03], MUC: [11.79, 48.35], HAM: [9.99, 53.63], DUS: [6.77, 51.29], CGN: [7.14, 50.87],
  STR: [9.22, 48.69], NUE: [11.08, 49.5], BER: [13.5, 52.37], HAJ: [9.69, 52.46], LEJ: [12.24, 51.42],
  ORD: [-87.9, 41.98], JFK: [-73.78, 40.64], LAX: [-118.41, 33.94], MIA: [-80.29, 25.79], ATL: [-84.43, 33.64],
  DFW: [-97.04, 32.9], YYZ: [-79.63, 43.68], MEX: [-99.07, 19.44], GRU: [-46.47, -23.43], EZE: [-58.54, -34.82],
  BOG: [-74.15, 4.7], LIM: [-77.11, -12.02], SCL: [-70.79, -33.39], ASU: [-57.52, -25.24], DXB: [55.36, 25.25],
  DOH: [51.61, 25.27], RUH: [46.7, 24.96], TLV: [34.89, 32.01], CAI: [31.41, 30.12], JNB: [28.25, -26.14],
  NBO: [36.93, -1.32], LOS: [3.32, 6.58], TNR: [47.48, -18.8], DEL: [77.1, 28.56], BOM: [72.87, 19.09],
  KTM: [85.36, 27.7], SIN: [103.99, 1.36], KUL: [101.71, 2.75], BKK: [100.75, 13.69], SGN: [106.66, 10.82],
  HKG: [113.91, 22.31], PVG: [121.81, 31.14], PEK: [116.58, 40.08], ICN: [126.44, 37.46], NRT: [140.39, 35.77],
  TPE: [121.23, 25.08], MNL: [121.02, 14.51], ULN: [106.82, 47.65], SYD: [151.18, -33.94], MEL: [144.84, -37.67],
  PPT: [-149.61, -17.55],
}

const PERIODS = [['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['year', 'Year'], ['all', 'All']]
const W = 960
const H = 500
const land = feature(countries, countries.objects.countries)
const projection = geoNaturalEarth1().fitSize([W, H], land)
const path = geoPath(projection)

const volume = (l) => Math.max(l.requests, l.booked)
const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)} %`)
const TOP = 15

function tone(rate) {
  if (rate == null) return 'var(--color-accent)'
  if (rate >= 0.6) return '#2fb37a'
  if (rate >= 0.3) return '#e0a030'
  return '#e5484d'
}

function Card({ title, note, children, className = '' }) {
  return (
    <section className={`glass lb-rise rounded-[28px] p-5 sm:p-6 ${className}`}>
      <h3 className="text-[11px] tracking-[0.16em] text-muted uppercase">{title}</h3>
      {note && <p className="mt-1 text-[13px] text-zinc-400">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Bar({ value, max, color = 'var(--color-accent)' }) {
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-[color-mix(in_oklch,var(--color-foreground)_8%,transparent)]">
      <span className="block h-full rounded-full" style={{ width: `${max ? Math.max(4, (value / max) * 100) : 0}%`, background: color }} />
    </span>
  )
}

const calm = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

function WorldMap({ lanes, focus, setFocus }) {
  const drawn = lanes.filter((l) => AIRPORTS[l.origin] && AIRPORTS[l.destination])
  const ranked = [...drawn].sort((a, b) => volume(b) - volume(a))
  const top = new Set(ranked.slice(0, TOP).map((l) => `${l.origin}-${l.destination}`))
  const max = Math.max(1, ...drawn.map(volume))
  const hubs = new Set(drawn.map((l) => l.origin))
  const labelled = new Set(ranked.slice(0, TOP).map((l) => l.destination))
  const order = [...drawn].sort((a, b) => top.has(`${a.origin}-${a.destination}`) - top.has(`${b.origin}-${b.destination}`))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Lanes on a world map">
      <defs>
        <filter id="lane-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="2.2" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <path d={path(land)} fill="color-mix(in oklch, var(--color-foreground) 7%, transparent)" stroke="color-mix(in oklch, var(--color-foreground) 14%, transparent)" strokeWidth="0.4" />
      {order.map((l) => {
        const key = `${l.origin}-${l.destination}`
        const line = { type: 'LineString', coordinates: [AIRPORTS[l.origin], AIRPORTS[l.destination]] }
        const main = top.has(key)
        const on = focus === key
        const dim = focus && !on
        return (
          <path
            key={key}
            d={path(line)}
            fill="none"
            stroke={main || on ? tone(l.win_rate) : 'color-mix(in oklch, var(--color-foreground) 22%, transparent)'}
            strokeOpacity={dim ? 0.12 : main || on ? 0.9 : 0.5}
            strokeWidth={main || on ? 1.4 + (3.2 * volume(l)) / max + (on ? 1.2 : 0) : 0.6}
            strokeLinecap="round"
            filter={main && !dim ? 'url(#lane-glow)' : undefined}
            className="cursor-pointer transition-[stroke-opacity]"
            onMouseEnter={() => setFocus(key)}
            onMouseLeave={() => setFocus(null)}
          />
        )
      })}
      {!calm &&
        ranked.slice(0, TOP).map((l, i) => {
          const key = `${l.origin}-${l.destination}`
          const d = path({ type: 'LineString', coordinates: [AIRPORTS[l.origin], AIRPORTS[l.destination]] })
          const dim = focus && focus !== key
          const dur = 3.2 + (i % 5) * 0.7
          return (
            <g key={`fx-${key}`} pointerEvents="none" opacity={dim ? 0.1 : 1}>
              <path d={d} fill="none" stroke="#fff" strokeOpacity="0.55" strokeWidth="1.1" strokeLinecap="round" strokeDasharray="1.5 9" className="lane-flow" style={{ animationDuration: `${dur * 0.6}s` }} />
              {[0, 0.5].map((offset) => (
                <circle key={offset} r="2.6" fill={tone(l.win_rate)} filter="url(#lane-glow)">
                  <animateMotion dur={`${dur}s`} repeatCount="indefinite" path={d} begin={`${-(offset * dur + i * 0.37).toFixed(2)}s`} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.45 0 0.55 1" />
                </circle>
              ))}
            </g>
          )
        })}
      {[...hubs].map((code) => {
        const [x, y] = projection(AIRPORTS[code])
        return (
          <g key={code}>
            {!calm && (
              <circle cx={x} cy={y} r="4" fill="none" stroke="var(--color-accent)" strokeWidth="1.2">
                <animate attributeName="r" values="4;16" dur="2.4s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.8;0" dur="2.4s" repeatCount="indefinite" />
              </circle>
            )}
            <circle cx={x} cy={y} r="3.6" fill="var(--color-accent)" stroke="var(--color-background)" strokeWidth="1.2" />
          </g>
        )
      })}
      {[...labelled].map((code) => {
        const [x, y] = projection(AIRPORTS[code])
        return (
          <g key={code}>
            <circle cx={x} cy={y} r="2.6" fill="var(--color-foreground)" />
            <text x={x + 5} y={y - 4} className="fill-zinc-300 font-mono text-[9px] font-semibold">{code}</text>
          </g>
        )
      })}
    </svg>
  )
}

export default function Network() {
  const t = useT()
  const [period, setPeriod] = useState('all')
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [focus, setFocus] = useState(null)

  useEffect(() => {
    let alive = true
    setErr(null)
    get(`/insights?period=${period}`)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e.message))
    return () => {
      alive = false
    }
  }, [period])

  const focused = useMemo(() => data?.lanes.find((l) => `${l.origin}-${l.destination}` === focus), [data, focus])
  const sum = data?.totals
  const lanes = [...(data?.lanes ?? [])].sort((a, b) => volume(b) - volume(a))
  const airlines = [...(data?.airlines ?? [])].sort((a, b) => b.booked - a.booked)
  const laneMax = Math.max(1, ...lanes.map(volume))
  const airMax = Math.max(1, ...airlines.map((a) => a.booked))
  const yes = sum?.quoted ? sum.won / sum.quoted : null

  return (
    <div className="space-y-6">
      <div className="flex justify-center">
        <div className="glass flex gap-1 rounded-full p-1.5">
          {PERIODS.map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-pressed={period === k}
              onClick={() => setPeriod(k)}
              className={`min-h-9 cursor-pointer rounded-full px-4 text-[13px] font-semibold transition-colors ${period === k ? 'bg-[linear-gradient(45deg,#ffa15c,var(--color-accent))] text-[#0d0d0d]' : 'text-zinc-300 hover:text-white'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {err && <p className="text-center text-sm text-rose-300">Could not load insights ({err}).</p>}

      <dl className="glass lb-rise grid grid-cols-2 gap-y-5 rounded-[28px] px-6 py-6 sm:grid-cols-3 lg:grid-cols-6">
        {[
          ['Lanes', sum?.lanes],
          ['Requests', sum?.requests],
          ['Quoted', sum?.quoted],
          ['Customer yes', sum?.won],
          ['Booked', sum?.booked],
          ['Yes rate', yes == null ? null : pct(yes)],
        ].map(([k, v]) => (
          <div key={k} className="min-w-0 text-center">
            <dt className="text-[11px] tracking-[0.12em] text-muted uppercase">{k}</dt>
            <dd className={`font-display mt-1 text-[clamp(1.3rem,2.4vw,1.9rem)] ${k === 'Yes rate' ? 'text-accent' : 'text-white'}`}>{v ?? '—'}</dd>
          </div>
        ))}
      </dl>

      <section className="glass lb-rise relative overflow-hidden rounded-[28px] p-3 sm:p-5">
        {data && <WorldMap lanes={data.lanes} focus={focus} setFocus={setFocus} />}
        <div className="pointer-events-none absolute bottom-4 left-5 flex flex-wrap items-center gap-4 text-[11px] text-zinc-400">
          <span className="flex items-center gap-1.5"><i className="h-1 w-5 rounded-full bg-[#2fb37a]" />customers say yes</span>
          <span className="flex items-center gap-1.5"><i className="h-1 w-5 rounded-full bg-[#e0a030]" />mixed</span>
          <span className="flex items-center gap-1.5"><i className="h-1 w-5 rounded-full bg-[#e5484d]" />price loses</span>
          <span className="flex items-center gap-1.5"><i className="size-2 rounded-full bg-accent" />German hub</span>
          <span>top {TOP} lanes bright · hover any lane</span>
        </div>
        {focused && (
          <div className="glass pointer-events-none absolute top-5 right-5 w-64 rounded-2xl p-4 text-xs">
            <div className="font-display text-lg text-white">{focused.origin} → {focused.destination}</div>
            <div className="mt-2 grid grid-cols-2 gap-y-1.5 text-muted">
              <span>Requests</span><span className="text-right font-mono text-zinc-200">{focused.requests}</span>
              <span>Booked</span><span className="text-right font-mono text-zinc-200">{focused.booked}</span>
              <span>Customer yes</span><span className="text-right font-mono" style={{ color: tone(focused.win_rate) }}>{pct(focused.win_rate)}</span>
              <span>Avg quote</span><span className="text-right font-mono text-zinc-200">{focused.avg_total ? money(focused.avg_total, 'EUR') : '—'}</span>
              <span>Top airline</span><span className="truncate text-right text-zinc-200">{focused.top_carrier ?? '—'}</span>
            </div>
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Busiest lanes" note="Where customers buy most often. Hover to light it up on the map.">
          <ol className="space-y-3">
            {lanes.slice(0, 8).map((l, i) => {
              const key = `${l.origin}-${l.destination}`
              return (
                <li key={key} className={`cursor-default rounded-2xl px-3 py-2 transition-colors ${focus === key ? 'bg-[color-mix(in_oklch,var(--color-accent)_12%,transparent)]' : ''}`} onMouseEnter={() => setFocus(key)} onMouseLeave={() => setFocus(null)}>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="flex items-baseline gap-3">
                      <span className="font-display w-5 text-zinc-400">{i + 1}</span>
                      <span className="font-mono font-semibold text-white">{l.origin} → {l.destination}</span>
                    </span>
                    <span className="text-[12px] text-zinc-400">
                      {l.requests} req · {l.booked} booked · <span style={{ color: tone(l.win_rate) }}>{pct(l.win_rate)} yes</span>
                    </span>
                  </div>
                  <div className="mt-1.5 pl-8"><Bar value={volume(l)} max={laneMax} color={tone(l.win_rate)} /></div>
                </li>
              )
            })}
          </ol>
        </Card>

        <Card title="Airline league" note="Bookings per airline and how often its quote turned into a yes.">
          <ol className="space-y-3">
            {airlines.slice(0, 8).map((a, i) => (
              <li key={a.carrier} className="px-3 py-2">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="flex min-w-0 items-baseline gap-3">
                    <span className="font-display w-5 text-zinc-400">{i + 1}</span>
                    <span className="truncate font-semibold text-white">{a.carrier}</span>
                  </span>
                  <span className="shrink-0 text-[12px] text-zinc-400">
                    {a.booked} booked · <span style={{ color: tone(a.acceptance) }}>{pct(a.acceptance)} yes</span>
                    {a.avg_transit_days != null && <> · {a.avg_transit_days} d</>}
                  </span>
                </div>
                <div className="mt-1.5 pl-8"><Bar value={a.booked} max={airMax} /></div>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      <Card title="Talk to the airline" note="Lanes with steady demand where our price was rejected or customers said no. A sharper rate here wins repeat business.">
        {data?.pressure?.length ? (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.pressure.slice(0, 9).map((p) => (
              <li key={`${p.origin}-${p.destination}`} className="rounded-2xl border border-[color-mix(in_oklch,var(--color-foreground)_10%,transparent)] p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-display text-white">{p.origin} → {p.destination}</span>
                  <span className="font-mono text-[12px]" style={{ color: tone(p.win_rate) }}>{pct(p.win_rate)} yes</span>
                </div>
                <p className="mt-1.5 text-[12px] text-zinc-400">
                  {p.requests} requests
                  {p.too_high > 0 && <span className="text-[#e5484d]"> · {p.too_high} rejected as too high</span>}
                </p>
                {p.top_carrier && <p className="mt-2 text-[12px] text-zinc-300">Ask <span className="font-semibold text-white">{p.top_carrier}</span> for a better rate</p>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No lane under price pressure in this period.</p>
        )}
      </Card>
    </div>
  )
}
