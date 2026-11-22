import FeaturesWithPanel from './components/ui/features-with-panel'
import { useLang } from './prefs'

const img = (id) => `https://images.unsplash.com/${id}?auto=format&fit=crop&w=1200&h=900&q=75`

const PHOTOS = [
  img('photo-1596526131083-e8c633c948d2'), // mail app
  img('photo-1488590528505-98d2b5aba04b'), // code on screen
  img('photo-1542296332-2e4473faf563'), // plane at the gate
  img('photo-1601584115197-04ecc0da31d7'), // truck on the road
  img('photo-1563986768609-322da13575f3'), // laptop and phone
  img('photo-1520437358207-323b43b50729'), // plane landing at dusk
  img('photo-1460925895917-afdab827c52f'), // dashboard on a laptop
]

const COPY = {
  en: {
    eyebrow: 'What it does',
    heading: (
      <>
        Seven jobs, <span className="squiggle font-serif italic font-normal whitespace-nowrap">one bot.</span>
      </>
    ),
    items: [
      ['Reads every request the moment it lands.', 'An inbox notification for a new freight request'],
      ['Prices it in code, never by guesswork.', 'Pricing code on a laptop screen'],
      ['Picks the airline that wins on price and deadline.', 'A cargo plane at the gate'],
      ['Books the trucker for the road legs.', 'A truck on the road to the airport'],
      ['Replies in the customer’s own language.', 'Writing a reply on laptop and phone'],
      ['Books on a yes and keeps the customer posted.', 'A plane landing at dusk'],
      ['Learns from every round it wins or loses.', 'Results on an analytics dashboard'],
    ],
  },
  de: {
    eyebrow: 'Was er macht',
    heading: (
      <>
        Sieben Aufgaben, <span className="squiggle font-serif italic font-normal whitespace-nowrap">ein Bot.</span>
      </>
    ),
    items: [
      ['Liest jede Anfrage, sobald sie eintrifft.', 'Eine Benachrichtigung über eine neue Frachtanfrage'],
      ['Berechnet den Preis im Code, nie geschätzt.', 'Preiscode auf einem Laptop'],
      ['Wählt die Airline, die bei Preis und Frist gewinnt.', 'Ein Frachtflugzeug am Gate'],
      ['Bucht den Lkw für die Straßenstrecken.', 'Ein Lkw auf dem Weg zum Flughafen'],
      ['Antwortet in der Sprache des Kunden.', 'Eine Antwort auf Laptop und Handy'],
      ['Bucht beim Ja und hält den Kunden auf dem Laufenden.', 'Ein Flugzeug landet in der Dämmerung'],
      ['Lernt aus jeder gewonnenen und verlorenen Runde.', 'Ergebnisse auf einem Dashboard'],
    ],
  },
}

/** After the intro: AUTOPILOT's jobs one by one, each with its own photo. */
export default function Features() {
  const [lang] = useLang()
  const c = COPY[lang] ?? COPY.en
  return (
    <div id="features" className="shadcn-scope scroll-mt-4">
      <FeaturesWithPanel
        eyebrow={<p className="eyebrow mb-4">{c.eyebrow}</p>}
        heading={<span className="font-display font-normal">{c.heading}</span>}
        items={c.items.map(([title, alt], i) => ({ title, alt, content: PHOTOS[i] }))}
        autoAdvanceMs={4500}
        cardClassName="sketch-card rounded-2xl shadow-none"
      />
    </div>
  )
}
