import { Globe2 } from 'lucide-react'
import { CinematicFooter } from './components/ui/motion-footer'
import { useLang } from './prefs'

const REPO = 'https://github.com/Rishabh4691/WRATHOFCODE'

const COPY = {
  en: {
    marquee: ['Reads every request', 'Prices in code', 'Best airline on price and deadline', 'Trucks the road legs', 'Replies in your language', 'Books on a yes', 'Learns every round'],
    heading: (
      <>
        Ready for <span className="font-serif italic font-normal">take-off?</span>
      </>
    ),
    primary: [['See the network', 'network', <Globe2 key="g" />]],
    secondary: [['Shipments', 'shipments'], ['Missed leads', 'lessons'], ['Requests', 'rfqs'], ['Features', `${REPO}/blob/main/docs/FEATURES.md`], ['GitHub', REPO]],
    copyright: '© 2026 WRATHOFCODE · START Hack Munich',
    top: 'Back to top',
  },
  de: {
    marquee: ['Liest jede Anfrage', 'Preis im Code', 'Beste Airline nach Preis und Frist', 'Lkw für die Straße', 'Antwortet in Ihrer Sprache', 'Bucht beim Ja', 'Lernt jede Runde'],
    heading: (
      <>
        Bereit zum <span className="font-serif italic font-normal">Abheben?</span>
      </>
    ),
    primary: [['Netzwerk ansehen', 'network', <Globe2 key="g" />]],
    secondary: [['Sendungen', 'shipments'], ['Verpasste Leads', 'lessons'], ['Anfragen', 'rfqs'], ['Funktionen', `${REPO}/blob/main/docs/FEATURES.md`], ['GitHub', REPO]],
    copyright: '© 2026 WRATHOFCODE · START Hack München',
    top: 'Nach oben',
  },
}

const isTab = (target) => !target.startsWith('http')

/** The closing screen: revealed from under the page as you scroll to the end. */
export default function SiteFooter({ onOpen }) {
  const [lang] = useLang()
  const c = COPY[lang] ?? COPY.en

  const link = ([label, target, icon]) =>
    isTab(target)
      ? {
          label,
          icon,
          href: `?tab=${target}`,
          onClick: (e) => {
            e.preventDefault()
            onOpen?.(target)
          },
        }
      : { label, icon, href: target, external: true }

  return (
    <CinematicFooter
      marquee={c.marquee}
      giantText="AUTOPILOT"
      giantClassName="font-display !text-[15.5vw]"
      heading={c.heading}
      headingClassName="font-display !font-normal"
      primaryLinks={c.primary.map(link)}
      secondaryLinks={c.secondary.map(link)}
      copyright={c.copyright}
      topLabel={c.top}
    />
  )
}
