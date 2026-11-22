import DoodleCrewFooter from './components/ui/doodle-crew-footer'
import { useLang, useTheme } from './prefs'

const REPO = 'https://github.com/Rishabh4691/WRATHOFCODE'

const COPY = {
  en: {
    blurb: 'An air freight forwarder that runs itself. Every request read, priced, answered and booked, with no human in the loop.',
    tagline: 'Quotes in seconds, in the customer’s language, around the clock.',
    cols: [
      ['Control Room', [['Overview', 'overview'], ['Scoreboard', 'board'], ['Network', 'network'], ['Requests', 'rfqs']]],
      ['Operations', [['Shipments', 'shipments'], ['Claims', 'claims'], ['Agents', 'agents'], ['Lessons', 'lessons']]],
      ['Docs', [['Features', `${REPO}/blob/main/docs/FEATURES.md`], ['Security', `${REPO}/blob/main/docs/SECURITY.md`], ['README', `${REPO}#readme`]]],
      ['Team', [['WRATHOFCODE', REPO], ['START Hack 2026', REPO]]],
    ],
    actions: [['See the network', 'network', 'plane', 'outline'], ['Open the scoreboard', 'board', 'bolt', 'solid']],
    crew: [
      ['Bruno', 'Quoted in 10 seconds. Snack break?'],
      ['Pip', 'Tweet! Your cargo just landed.'],
      ['Morel', 'I only grow on chargeable weight.'],
      ['Juno', 'Up here I can see every lane.'],
      ['Boo', 'Boo! No human in the loop. Just me.'],
      ['Patch', 'Booked. Purr.'],
    ],
    copyright: '© 2026 WRATHOFCODE · drawn at START Hack Munich',
    top: 'Back to top',
  },
  de: {
    blurb: 'Ein Luftfracht-Spediteur, der sich selbst steuert. Jede Anfrage gelesen, berechnet, beantwortet und gebucht, ohne Menschen dazwischen.',
    tagline: 'Angebote in Sekunden, in der Sprache des Kunden, rund um die Uhr.',
    cols: [
      ['Leitstand', [['Überblick', 'overview'], ['Rangliste', 'board'], ['Netzwerk', 'network'], ['Anfragen', 'rfqs']]],
      ['Betrieb', [['Sendungen', 'shipments'], ['Schäden', 'claims'], ['Agenten', 'agents'], ['Lektionen', 'lessons']]],
      ['Doku', [['Funktionen', `${REPO}/blob/main/docs/FEATURES.md`], ['Sicherheit', `${REPO}/blob/main/docs/SECURITY.md`], ['README', `${REPO}#readme`]]],
      ['Team', [['WRATHOFCODE', REPO], ['START Hack 2026', REPO]]],
    ],
    actions: [['Netzwerk ansehen', 'network', 'plane', 'outline'], ['Rangliste öffnen', 'board', 'bolt', 'solid']],
    crew: [
      ['Bruno', 'In 10 Sekunden angeboten. Snackpause?'],
      ['Pip', 'Piep! Deine Fracht ist gelandet.'],
      ['Morel', 'Ich wachse nur auf Frachtgewicht.'],
      ['Juno', 'Von hier oben sehe ich jede Strecke.'],
      ['Boo', 'Buh! Kein Mensch dazwischen. Nur ich.'],
      ['Patch', 'Gebucht. Schnurr.'],
    ],
    copyright: '© 2026 WRATHOFCODE · gezeichnet beim START Hack München',
    top: 'Nach oben',
  },
}

// Where each character lives on A-U-T-O-P-I-L-O-T.
const SEATS = [
  { kind: 'yeti', letter: 0, seat: 'front', offset: -0.32 },
  { kind: 'bird', letter: 1, seat: 'top', offset: 0.02 },
  { kind: 'mushroom', letter: 2, seat: 'front', offset: 0.12, scale: 0.95 },
  { kind: 'kid', letter: 4, seat: 'top', offset: -0.05 },
  { kind: 'ghost', letter: 6, seat: 'behind', offset: 0 },
  { kind: 'cat', letter: 8, seat: 'front', offset: 0.42, flip: true },
]

const isTab = (target) => !target.startsWith('http')

export default function SiteFooter({ onOpen }) {
  const [lang] = useLang()
  const [theme] = useTheme()
  const c = COPY[lang] ?? COPY.en
  const dark = theme === 'dark'

  return (
    <DoodleCrewFooter
      wordmark="AUTOPILOT"
      brand="autopilot"
      blurb={c.blurb}
      tagline={c.tagline}
      columns={c.cols.map(([title, links]) => ({
        title,
        links: links.map(([label, target]) => ({ label, href: isTab(target) ? `?tab=${target}` : target })),
      }))}
      actions={c.actions.map(([label, tab, icon, variant]) => ({
        label,
        icon,
        variant,
        onClick: () => {
          onOpen(tab)
          window.scrollTo({ top: 0, behavior: 'smooth' })
        },
      }))}
      crew={SEATS.map((s, i) => ({ ...s, name: c.crew[i][0], says: c.crew[i][1] }))}
      doodles={['plane', 'star', 'bolt', 'sparkle', 'plane', 'heart', 'flame', 'star']}
      doodleCount={12}
      copyright={c.copyright}
      legal={[]}
      socials={[{ label: 'GitHub', href: REPO }]}
      preset={dark ? 'night' : 'paper'}
      palette={dark ? { background: '#0e0e10', ink: '#f4f1ea', accent: '#ff8a3d' } : { background: '#fffdf8', ink: '#0d0d0d', accent: '#ff6b2c' }}
      fontFamily='"Archivo Black", "Arial Black", Helvetica, sans-serif'
      height="720px"
    />
  )
}
