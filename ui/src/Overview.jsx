import { ProjectDeck } from '@/components/ui/scroll-stacking-cards'
import { useLang, useTheme } from './prefs'

const CARDS = [
  { tab: 'board', accent: '#de5531', image: '/overview/board.webp',
    en: ['Live scoreboard', 'Every round, its verdict and points', 'Our rank, every round\'s verdict and points, and the mails of each round, live from the 5U board.'],
    de: ['Live-Rangliste', 'Jede Runde, Urteil und Punkte', 'Unser Rang, Urteil und Punkte jeder Runde und ihre Mails, live von der 5U-Rangliste.'] },
  { tab: 'network', accent: '#3f4e73', image: '/overview/network.webp',
    en: ['Network', 'Lanes, airlines and price pressure', 'Every lane on a world map, the airline league, and the lanes where a better rate would win more business.'],
    de: ['Netzwerk', 'Strecken, Airlines und Preisdruck', 'Jede Strecke auf der Weltkarte, die Airline-Tabelle und die Strecken, auf denen ein besserer Preis mehr Geschäft bringt.'] },
  { tab: 'rfqs', accent: '#de5531', image: '/overview/rfqs.webp',
    en: ['Requests', 'From mail to quote in seconds', 'Each request with its pipeline, price breakdown and the sent email, every number in it set by code.'],
    de: ['Anfragen', 'Von der Mail zum Angebot in Sekunden', 'Jede Anfrage mit Ablauf, Preisaufschlüsselung und gesendeter Mail, jede Zahl darin vom Code gesetzt.'] },
  { tab: 'shipments', accent: '#3f4e73', image: '/overview/shipments.webp',
    en: ['Shipments', 'Booked and delivered', 'Every booking with airline, arrival and the updates sent to the customer.'],
    de: ['Sendungen', 'Gebucht und zugestellt', 'Jede Buchung mit Airline, Ankunft und den Updates an den Kunden.'] },
  { tab: 'agents', accent: '#de5531', image: '/overview/agents.webp',
    en: ['Agents', 'Who is doing what, right now', 'One card per agent: the current task, success rate, speed and model cost.'],
    de: ['Agenten', 'Wer gerade was macht', 'Eine Karte pro Agent: aktuelle Aufgabe, Erfolgsquote, Tempo und Modellkosten.'] },
  { tab: 'lessons', accent: '#3f4e73', image: '/overview/lessons.webp',
    en: ['Lessons', 'Every lost round became a fix', 'Each lost round with its root cause, the fix and the commit that shipped it.'],
    de: ['Lektionen', 'Jede verlorene Runde wurde zum Fix', 'Jede verlorene Runde mit Ursache, Fix und dem Commit, der ihn ausgeliefert hat.'] },
]

export default function Overview({ onOpen }) {
  const [lang] = useLang()
  const [theme] = useTheme()
  const dark = theme !== 'light'
  const projects = CARDS.map((c) => {
    const [name, display, summary] = c[lang] ?? c.en
    return { name, display, summary, image: c.image, accent: c.accent, onOpen: () => onOpen(c.tab) }
  })
  const hero = lang === 'de'
    ? ['Von der Anfrage zur Buchung', 'Jede Luftfracht-Anfrage beantwortet.', 'Ohne Menschen dazwischen.', 'AUTOPILOT liest jede Mail, rechnet den Preis im Code, antwortet in der Sprache des Kunden, bucht bei einem Ja und hält den Kunden auf dem Laufenden. Rund um die Uhr.']
    : ['From inbox to booking', 'Every air freight request answered.', 'No human in the loop.', 'AUTOPILOT reads every mail, prices it in code, replies in the customer\'s language, books on a yes and keeps the customer posted. Around the clock.']
  return (
    <>
    <section className="mb-10 max-w-3xl">
      <span className="eyebrow">{hero[0]}</span>
      <h2 className="mt-5 text-4xl leading-[1.08] font-medium tracking-[-0.02em] text-white sm:text-5xl">
        {hero[1]}<br /><span className="font-light">{hero[2]}</span>
      </h2>
      <p className="mt-5 max-w-xl text-[15px] leading-relaxed text-zinc-300">{hero[3]}</p>
    </section>
    <ProjectDeck
      projects={projects}
      ground={dark ? '#34405f' : '#ffffff'}
      ink={dark ? '#ffffff' : '#14161c'}
      muted={dark ? '#a9b3cc' : '#6e7280'}
    />
    </>
  )
}
