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

function tone(rate) {
  if (rate == null) return '#df5733'
  if (rate >= 0.6) return '#4b8d6b'
  if (rate >= 0.3) return '#c08a2e'
  return '#c14f55'
}

function Panel({ title, note, children }) {
  return (
    <section className="rounded-xl border border-line bg-panel">
      <header className="border-b border-line px-4 py-3">
        <h3 className="text-[11px] font-medium uppercase tracking-wider text-muted">{title}</h3>
        {note && <p className="mt-1 text-xs text-muted">{note}</p>}
      </header>
      <div className="overflow-x-auto px-4 py-3">{children}</div>
    </section>
  )
}

function WorldMap({ lanes, focus, setFocus }) {
  const max = Math.max(1, ...lanes.map(volume))
  const drawn = lanes.filter((l) => AIRPORTS[l.origin] && AIRPORTS[l.destination])
  const ports = new Set(drawn.flatMap((l) => [l.origin, l.destination]))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Lanes on a world map">
      <path d={path({ type: 'Sphere' })} className="map-sea" fill="#f1efeb" />
      <path d={path(land)} className="map-land" fill="#e3e0db" stroke="#d6d2cc" strokeWidth="0.5" />
      {drawn.map((l) => {
        const key = `${l.origin}-${l.destination}`
        const line = { type: 'LineString', coordinates: [AIRPORTS[l.origin], AIRPORTS[l.destination]] }
        const on = focus === key
        return (
          <path
            key={key}
            d={path(line)}
            fill="none"
            stroke={tone(l.win_rate)}
            strokeOpacity={focus && !on ? 0.15 : 0.85}
            strokeWidth={1 + (5 * volume(l)) / max + (on ? 1.5 : 0)}
            strokeLinecap="round"
            className="cursor-pointer transition-[stroke-opacity]"
            onMouseEnter={() => setFocus(key)}
            onMouseLeave={() => setFocus(null)}
          />
        )
      })}
      {[...ports].map((code) => {
        const [x, y] = projection(AIRPORTS[code])
        const german = AIRPORTS[code][0] > 5 && AIRPORTS[code][0] < 15 && AIRPORTS[code][1] > 47
        return (
          <g key={code}>
            <circle cx={x} cy={y} r={german ? 2.5 : 3} fill={german ? '#817c74' : '#df5733'} />
            {!german && <text x={x + 5} y={y - 4} className="fill-zinc-400 font-mono text-[9px]">{code}</text>}
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

  const focused = useMemo(
    () => data?.lanes.find((l) => `${l.origin}-${l.destination}` === focus),
    [data, focus],
  )
  const sum = data?.totals

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div />
        <div className="flex overflow-hidden rounded-lg border border-line text-xs">
          {PERIODS.map(([k, label]) => (
            <button
              key={k}
              onClick={() => setPeriod(k)}
              className={`px-3 py-1.5 ${period === k ? 'bg-sky-500/15 text-sky-300' : 'text-muted hover:text-zinc-200'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {err && <p className="text-sm text-rose-300">Could not load insights ({err}).</p>}

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
        {[
          ['Lanes', sum?.lanes],
          ['Requests', sum?.requests],
          ['Quoted', sum?.quoted],
          ['Customer yes', sum?.won],
          ['Booked', sum?.booked],
          ['Delays reported', sum?.delays],
        ].map(([k, v]) => (
          <div key={k} className="min-w-0 bg-panel px-4 py-3">
            <div className="text-[11px] uppercase tracking-wider text-muted">{k}</div>
            <div className="mt-1 font-mono text-lg text-white">{v ?? '—'}</div>
          </div>
        ))}
      </div>

      <section className="relative overflow-hidden rounded-xl border border-line bg-panel p-2">
        {data && <WorldMap lanes={data.lanes} focus={focus} setFocus={setFocus} />}
        <div className="pointer-events-none absolute bottom-3 left-4 flex flex-wrap gap-4 text-[11px] text-muted">
          <span className="flex items-center gap-1.5"><span className="h-1 w-4 rounded bg-emerald-400" />customers say yes</span>
          <span className="flex items-center gap-1.5"><span className="h-1 w-4 rounded bg-amber-400" />mixed</span>
          <span className="flex items-center gap-1.5"><span className="h-1 w-4 rounded bg-rose-400" />price loses</span>
          <span>line width = volume</span>
        </div>
        {focused && (
          <div className="pointer-events-none absolute right-4 top-4 w-60 rounded-lg border border-line bg-ink/90 p-3 text-xs">
            <div className="font-mono text-sm text-white">{focused.origin} → {focused.destination}</div>
            <div className="mt-2 grid grid-cols-2 gap-y-1 text-muted">
              <span>Requests</span><span className="text-right font-mono text-zinc-200">{focused.requests}</span>
              <span>Booked</span><span className="text-right font-mono text-zinc-200">{focused.booked}</span>
              <span>Customer yes</span><span className="text-right font-mono text-zinc-200">{pct(focused.win_rate)}</span>
              <span>Avg quote</span><span className="text-right font-mono text-zinc-200">{focused.avg_total ? money(focused.avg_total, 'EUR') : '—'}</span>
              <span>Top airline</span><span className="truncate text-right text-zinc-200">{focused.top_carrier ?? '—'}</span>
            </div>
          </div>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Busiest lanes" note="Where customers buy most often.">
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
              <tr><th className="pb-2">Lane</th><th className="pb-2 text-right">Requests</th><th className="pb-2 text-right">Booked</th><th className="pb-2 text-right">Yes</th><th className="pb-2 text-right">Reply</th></tr>
            </thead>
            <tbody>
              {(data?.lanes ?? []).slice(0, 8).map((l) => (
                <tr key={`${l.origin}-${l.destination}`} className="border-t border-line" onMouseEnter={() => setFocus(`${l.origin}-${l.destination}`)} onMouseLeave={() => setFocus(null)}>
                  <td className="py-1.5 font-mono text-zinc-200">{l.origin} → {l.destination}</td>
                  <td className="py-1.5 text-right font-mono">{l.requests}</td>
                  <td className="py-1.5 text-right font-mono">{l.booked}</td>
                  <td className="py-1.5 text-right font-mono">{pct(l.win_rate)}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{l.avg_response_s != null ? `${Math.round(l.avg_response_s)} s` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Airline league" note="Bookings, how often a quote turned into a yes, transit and delays.">
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
              <tr><th className="pb-2">Airline</th><th className="pb-2 text-right">Booked</th><th className="pb-2 text-right">Yes rate</th><th className="pb-2 text-right">Transit</th><th className="pb-2 text-right">Delays</th></tr>
            </thead>
            <tbody>
              {(data?.airlines ?? []).slice(0, 8).map((a) => (
                <tr key={a.carrier} className="border-t border-line">
                  <td className="py-1.5 text-zinc-200">{a.carrier}</td>
                  <td className="py-1.5 text-right font-mono">{a.booked}</td>
                  <td className="py-1.5 text-right font-mono">{pct(a.acceptance)}</td>
                  <td className="py-1.5 text-right font-mono">{a.avg_transit_days != null ? `${a.avg_transit_days} d` : '—'}</td>
                  <td className={`py-1.5 text-right font-mono ${a.delays ? 'text-rose-300' : 'text-muted'}`}>{a.delays}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <Panel title="Talk to the airline" note="Lanes with steady demand where our price was rejected or customers said no. A sharper rate here wins repeat business.">
        {data?.pressure?.length ? (
          <ul className="space-y-2 text-sm">
            {data.pressure.map((p) => (
              <li key={`${p.origin}-${p.destination}`} className="flex flex-wrap items-baseline justify-between gap-2 border-t border-line pt-2 first:border-0 first:pt-0">
                <span className="font-mono text-zinc-200">{p.origin} → {p.destination}</span>
                <span className="text-muted">
                  {p.requests} requests · yes {pct(p.win_rate)}
                  {p.too_high > 0 && <span className="text-rose-300"> · {p.too_high} rejected as too high</span>}
                  {p.top_carrier && <> · ask <span className="text-zinc-200">{p.top_carrier}</span> for a better rate</>}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No lane under price pressure in this period.</p>
        )}
      </Panel>
    </div>
  )
}
