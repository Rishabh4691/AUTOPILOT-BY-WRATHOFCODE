import { useEffect, useState } from 'react'

const WORDS = {
  en: {
    tagline: 'WRATHOFCODE · digital air forwarder',
    overview: 'Overview', board: 'Live scoreboard', network: 'Network', agents: 'Agent Control Room', rfqs: 'RFQs',
    shipments: 'Shipments', claims: 'Claims', lessons: 'Missed leads',
    live: 'Live', reconnecting: 'Reconnecting', apiDown: 'API down', demo: 'Demo data',
    dark: 'Dark', light: 'Light', model: 'Writer model', updates: 'Daily updates', on: 'On', off: 'Off',
    booked: 'Booked', delivered: 'Delivered', lane: 'Lane', airline: 'Airline', arrival: 'Arrival',
    reference: 'Reference', customer: 'Customer', updatesSent: 'Updates', status: 'Status', price: 'Price',
    noShipments: 'No shipments here yet.', noClaims: 'No claims filed. The bot files one with the airline as soon as a customer reports a lost or damaged shipment.',
    claim: 'Claim', kind: 'Type', filedWith: 'Filed with', filed: 'Filed', description: 'Customer report',
    lost: 'Lost', damaged: 'Damaged',
    updatesNote: 'When on, every booked customer gets one status mail a day and an arrival note, at most 10 mails a minute.',
    modelNote: 'Model the quote writer uses. Mini scores more cost points.',
    networkTitle: 'Network', networkNote: 'Where customers ship, which airlines deliver, and where our price loses.',
    lessonsTitle: 'Every lost round became a fix',
  },
  de: {
    tagline: 'WRATHOFCODE · digitaler Luftfracht-Spediteur',
    overview: 'Überblick', board: 'Live-Rangliste', network: 'Netzwerk', agents: 'Agenten-Leitstand', rfqs: 'Anfragen',
    shipments: 'Sendungen', claims: 'Schäden', lessons: 'Verpasste Leads',
    live: 'Live', reconnecting: 'Verbinde neu', apiDown: 'API nicht erreichbar', demo: 'Demodaten',
    dark: 'Dunkel', light: 'Hell', model: 'Schreib-Modell', updates: 'Tägliche Updates', on: 'An', off: 'Aus',
    booked: 'Gebucht', delivered: 'Zugestellt', lane: 'Strecke', airline: 'Airline', arrival: 'Ankunft',
    reference: 'Referenz', customer: 'Kunde', updatesSent: 'Updates', status: 'Status', price: 'Preis',
    noShipments: 'Noch keine Sendungen.', noClaims: 'Keine Schäden gemeldet. Der Bot meldet einen Schaden sofort bei der Airline, wenn ein Kunde Verlust oder Beschädigung meldet.',
    claim: 'Schaden', kind: 'Art', filedWith: 'Gemeldet bei', filed: 'Gemeldet', description: 'Meldung des Kunden',
    lost: 'Verloren', damaged: 'Beschädigt',
    updatesNote: 'Wenn an, bekommt jeder gebuchte Kunde einmal am Tag ein Status-Update und eine Ankunftsnachricht, höchstens 10 Mails pro Minute.',
    modelNote: 'Modell für die Angebotsmails. Mini bringt mehr Kostenpunkte.',
    networkTitle: 'Netzwerk', networkNote: 'Wohin Kunden versenden, welche Airlines liefern und wo unser Preis verliert.',
    lessonsTitle: 'Jede verlorene Runde wurde zu einem Fix',
  },
}

function stored(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback
  } catch {
    return fallback
  }
}

function usePref(key, fallback, apply) {
  const [value, setValue] = useState(() => stored(key, fallback))
  useEffect(() => {
    apply?.(value)
    try {
      localStorage.setItem(key, value)
    } catch {}
    window.dispatchEvent(new CustomEvent(`pref:${key}`, { detail: value }))
  }, [key, value, apply])
  useEffect(() => {
    const on = (e) => setValue(e.detail)
    window.addEventListener(`pref:${key}`, on)
    return () => window.removeEventListener(`pref:${key}`, on)
  }, [key])
  return [value, setValue]
}

const applyTheme = (v) => document.documentElement.setAttribute('data-theme', v)

export const useTheme = () => usePref('theme', 'light', applyTheme)
export const useLang = () => usePref('lang', 'en')

export function useT() {
  const [lang] = useLang()
  return (key) => WORDS[lang]?.[key] ?? WORDS.en[key] ?? key
}
