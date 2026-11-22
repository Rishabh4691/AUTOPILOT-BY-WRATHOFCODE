"""Cargo claims: a customer reports a lost, misplaced or damaged shipment, the bot files it with the airline and confirms."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from core.contracts import Agent, EventStatus, Mail, OutgoingMail
from mail import lang
from mail.text import fresh_text, reply_subject

log = logging.getLogger("core.claims")

CARGO = r"(?:box|boxes|pallet|pallets|piece|pieces|carton|cartons|parcel|parcels|crate|crates|shipment|cargo|goods)"
LOST = re.compile(
    r"\b(?:never arrived|did ?n[o']t arrive|has ?n[o']t arrived|went missing|got lost|was lost|lost in transit|"
    rf"{CARGO} (?:is|are|was|were) (?:missing|lost)|missing {CARGO}|lost {CARGO}|"
    r"nicht angekommen|verloren gegangen|(?:Kolli|Kollo|Karton\w*|Palette\w*|Paket\w*|Sendung) (?:fehl\w*|verloren)|"
    r"n'est pas arrivée?|perdue? en transit|(?:colis|carton|palette)s? (?:perdue?s?|manquante?s?)|"
    r"no ha llegado|no llegó|se perdió|(?:bulto|caja|palé)s? perdid[oa]s?|"
    r"non è arrivat[oa]|è andat[oa] pers[oa]|(?:collo|colli|cartone|bancale) mancant[ei])\b",
    re.I,
)
MISPLACED = re.compile(
    r"\b(?:misplaced|mis-?routed|mis-?delivered|sent to the wrong (?:airport|address|destination|warehouse|city|country)|"
    r"delivered to the wrong (?:address|airport|warehouse|company|place)|ended up in the wrong|wrong destination|"
    r"fehlgeleitet|falsch zugestellt|an die falsche (?:Adresse|Stelle|Firma) geliefert|"
    r"mal acheminée?s?|livrée? à la mauvaise adresse|"
    r"mal dirigid[oa]s?|enviad[oa] al destino equivocado|entregad[oa] en la dirección equivocada|"
    r"instradat[oa] male|consegnat[oa] all'indirizzo sbagliato)\b",
    re.I,
)
DAMAGED = re.compile(
    r"\b(?:(?:arrived|was|were|is|are|came|got)\s+(?:\w+\s+){0,2}(?:damaged|broken|crushed|wet|dented|torn)|"
    rf"damaged {CARGO}|damage claim|"
    r"beschädigt|zerbrochen|endommagée?s?|abîmée?s?|dañad[oa]s?|danneggiat[oaie]|rott[oi])\b",
    re.I,
)
CLAIM_WORD = re.compile(r"\b(?:claim|complaint|reklamation|schaden|réclamation|reclamación|reclamo|reclamo)\b", re.I)
BOOKING_REF = re.compile(r"\bBK-[A-Z0-9]{8}\b")
TEAM_REF = re.compile(r"\bWOC-(\d+)\b")

ACK = {
    "en": "Hi,\n\nI'm sorry to hear that. I have filed claim {claim} for your shipment {team} with {carrier} "
    "and passed on your description. The airline will come back with the next steps, and I'll keep you posted.\n\n"
    "If you have photos or a delivery receipt with remarks, just reply with them.\n\nCheers,\n{agent}\n{company}",
    "de": "Hallo,\n\ndas tut mir leid. Ich habe den Schaden {claim} für Ihre Sendung {team} bei {carrier} gemeldet "
    "und Ihre Beschreibung weitergegeben. Die Airline meldet sich mit den nächsten Schritten, ich halte Sie auf dem Laufenden.\n\n"
    "Fotos oder einen Ablieferschein mit Vermerk schicken Sie einfach als Antwort.\n\nViele Grüße\n{agent}\n{company}",
    "fr": "Bonjour,\n\nje suis désolée. J'ai ouvert la réclamation {claim} pour votre envoi {team} auprès de {carrier} "
    "avec votre description. La compagnie reviendra vers nous avec la suite, je vous tiens informé.\n\n"
    "Si vous avez des photos ou un bon de livraison avec réserves, répondez simplement avec.\n\nBien à vous,\n{agent}\n{company}",
    "es": "Hola,\n\nlo siento mucho. He abierto la reclamación {claim} de tu envío {team} con {carrier} "
    "con tu descripción. La aerolínea nos dirá los siguientes pasos y te mantengo informado.\n\n"
    "Si tienes fotos o un albarán con observaciones, respóndenos con ellos.\n\nUn saludo,\n{agent}\n{company}",
    "it": "Ciao,\n\nmi dispiace molto. Ho aperto il reclamo {claim} per la spedizione {team} con {carrier} "
    "con la tua descrizione. La compagnia ci dirà i prossimi passi e ti tengo aggiornato.\n\n"
    "Se hai foto o una bolla di consegna con riserve, rispondi pure con quelle.\n\nUn saluto,\n{agent}\n{company}",
}


def kind_of(text: str) -> str | None:
    fresh = fresh_text(text or "")
    if LOST.search(fresh):
        return "lost"
    if MISPLACED.search(fresh):
        return "misplaced"
    if DAMAGED.search(fresh) or (CLAIM_WORD.search(fresh) and re.search(r"damag|broken|beschädig|endommag|dañ|dannegg", fresh, re.I)):
        return "damaged"
    return None


def setup(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS claims ("
        "claim_id TEXT PRIMARY KEY, mail_id INTEGER UNIQUE, rfq_id TEXT, booking_reference TEXT, customer TEXT, "
        "carrier TEXT, carrier_email TEXT, kind TEXT, description TEXT, filed_at REAL, status TEXT)"
    )


class ClaimsAgent:
    def __init__(self, directory, outbound=None, agent_name: str = "Lena", company: str = "WRATHOFCODE Air Freight", now=time.time):
        self.directory, self.outbound = directory, outbound
        self.agent_name, self.company, self.now = agent_name, company, now

    def booking_for(self, orch: Any, mail: Mail, text: str) -> dict | None:
        conn = orch.store._conn
        cur = conn.execute("SELECT * FROM bookings LIMIT 0")
        cols = [d[0] for d in cur.description]

        def one(sql: str, *args) -> dict | None:
            row = conn.execute(sql, args).fetchone()
            return dict(zip(cols, row, strict=False)) if row else None

        ref = BOOKING_REF.search(text)
        team = TEAM_REF.search(text)
        return (
            (ref and one("SELECT * FROM bookings WHERE booking_reference=?", ref.group(0)))
            or (team and one("SELECT * FROM bookings WHERE rfq_id=?", team.group(1)))
            or one("SELECT * FROM bookings WHERE thread_id=? ORDER BY booked_at DESC", str(mail.thread_root_id))
        )

    def airline_email(self, carrier: str) -> str | None:
        wanted = (carrier or "").strip().lower()
        for contact in self.directory.airlines():
            if contact.name.lower() == wanted:
                return contact.email
        return None

    async def handle(self, orch: Any, mail: Mail) -> bool:
        text = f"{mail.subject}\n{fresh_text(mail.body)}"
        kind = kind_of(text)
        if kind is None:
            return False
        booking = self.booking_for(orch, mail, text)
        if booking is None:
            return False
        with orch.store._write() as w:
            setup(w)
            if w.execute("SELECT 1 FROM claims WHERE mail_id=?", (mail.id,)).fetchone():
                return False
        claim = f"CLM-{booking['rfq_id']}"
        carrier = booking.get("carrier") or ""
        to_airline = self.airline_email(carrier)
        team = booking.get("team_reference") or f"WOC-{booking['rfq_id']}"
        description = fresh_text(mail.body).strip()[:1200]
        if to_airline and self.outbound is not None:
            body = (
                f"Hello,\n\nwe are filing cargo claim {claim} for a {kind} shipment.\n\n"
                f"Booking reference: {booking.get('booking_reference')}\nOur reference: {team}\n"
                f"Lane: {booking.get('origin')}-{booking.get('destination')}\n"
                + (f"Weight: {booking['weight_kg']} kg\n" if booking.get("weight_kg") else "")
                + (f"Arrival: {booking['eta']}\n" if booking.get("eta") else "")
                + "\n"
                f"The customer reports:\n{description}\n\n"
                f"Please confirm the claim and the documents you need.\n\nKind regards,\n{self.agent_name}\n{self.company}"
            )
            try:
                await self.outbound.send_new(to_airline, f"Cargo claim {claim}: {kind} shipment {booking.get('booking_reference')}", body)
            except Exception:
                log.exception("claim_to_airline_failed", extra={"claim": claim})
                to_airline = None
        else:
            to_airline = None
        language = lang.detect(fresh_text(mail.body)) or "en"
        ack = ACK.get(language, ACK["en"]).format(
            claim=claim, team=team, carrier=carrier or "the airline", agent=self.agent_name, company=self.company
        )
        try:
            await orch.mailbox.send(OutgoingMail(to=mail.sender, subject=reply_subject(mail.subject), body=ack, in_reply_to=mail.id))
        except Exception:
            log.exception("claim_ack_failed", extra={"claim": claim})
        with orch.store._write() as w:
            w.execute(
                "INSERT OR IGNORE INTO claims (claim_id, mail_id, rfq_id, booking_reference, customer, carrier, "
                "carrier_email, kind, description, filed_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"{claim}-{mail.id}", mail.id, booking["rfq_id"], booking.get("booking_reference"), mail.sender,
                 carrier, to_airline, kind, description, self.now(), "filed" if to_airline else "airline unknown"),
            )
        orch.emit(
            Agent.BOOKING, "claim", EventStatus.OK if to_airline else EventStatus.WARN,
            f"Claim {claim} ({kind}) filed with {carrier or 'no airline'} for {booking.get('booking_reference')}.",
            int(booking["rfq_id"]) if str(booking["rfq_id"]).isdigit() else None,
        )
        return True
