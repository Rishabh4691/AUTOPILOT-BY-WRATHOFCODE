"""Shipment updates: one status mail per booking a day, and an arrival note, while the Control Room switch is on."""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any

from core import runtime_settings
from core.contracts import Agent, EventStatus, OutgoingMail
from mail import lang
from mail.text import reply_subject
from mail.writer import place, short_day

log = logging.getLogger("core.updates")

DUE_S = 86_400
PER_TICK = 10
QUIET_AFTER_REQUEST_S = 150

UPDATE = {
    "en": "Hi{first},\n\na quick update on your shipment {team} from {route}: {status}\n"
    "{carrier} has it under booking {ref}, arriving around {eta}.\n\n"
    "I'll write again once it has landed.\n\nCheers,\n{agent}\n{company}",
    "de": "Hallo{first},\n\nkurzes Update zu Ihrer Sendung {team} von {route}: {status}\n"
    "{carrier} fliegt sie unter Buchung {ref}, Ankunft etwa {eta}.\n\n"
    "Ich melde mich wieder, sobald sie gelandet ist.\n\nViele Grüße\n{agent}\n{company}",
    "fr": "Bonjour{first},\n\npetit point sur votre envoi {team} de {route} : {status}\n"
    "{carrier} le transporte sous la réservation {ref}, arrivée vers {eta}.\n\n"
    "Je vous écris dès qu'il a atterri.\n\nBien à vous,\n{agent}\n{company}",
    "es": "Hola{first},\n\nuna actualización rápida de tu envío {team} de {route}: {status}\n"
    "{carrier} lo lleva con la reserva {ref}, llegada sobre el {eta}.\n\n"
    "Te escribo de nuevo cuando haya aterrizado.\n\nUn saludo,\n{agent}\n{company}",
    "it": "Ciao{first},\n\nun breve aggiornamento sulla spedizione {team} da {route}: {status}\n"
    "{carrier} la trasporta con la prenotazione {ref}, arrivo verso {eta}.\n\n"
    "Ti scrivo di nuovo quando sarà atterrata.\n\nUn saluto,\n{agent}\n{company}",
}
ARRIVED = {
    "en": "Hi{first},\n\nyour shipment {team} with {carrier} was due at {dest} on {eta} (booking {ref}).\n\n"
    "If anything is missing or damaged, just reply to this mail and we'll take it up with the airline.\n\n"
    "Cheers,\n{agent}\n{company}",
    "de": "Hallo{first},\n\nIhre Sendung {team} mit {carrier} sollte am {eta} in {dest} angekommen sein (Buchung {ref}).\n\n"
    "Falls etwas fehlt oder beschädigt ist, antworten Sie einfach auf diese Mail, wir klären es mit der Airline.\n\n"
    "Viele Grüße\n{agent}\n{company}",
    "fr": "Bonjour{first},\n\nvotre envoi {team} avec {carrier} devait arriver à {dest} le {eta} (réservation {ref}).\n\n"
    "S'il manque quelque chose ou si la marchandise est abîmée, répondez simplement à ce mail, nous voyons cela avec la compagnie.\n\n"
    "Bien à vous,\n{agent}\n{company}",
    "es": "Hola{first},\n\ntu envío {team} con {carrier} tenía que llegar a {dest} el {eta} (reserva {ref}).\n\n"
    "Si falta algo o llegó dañado, responde a este correo y lo resolvemos con la aerolínea.\n\n"
    "Un saludo,\n{agent}\n{company}",
    "it": "Ciao{first},\n\nla spedizione {team} con {carrier} doveva arrivare a {dest} il {eta} (prenotazione {ref}).\n\n"
    "Se manca qualcosa o è arrivata danneggiata, rispondi a questa mail e ce ne occupiamo con la compagnia.\n\n"
    "Un saluto,\n{agent}\n{company}",
}
STATUS = {
    "en": "booked and ready to ship.",
    "de": "gebucht und bereit zum Versand.",
    "fr": "réservé et prêt à partir.",
    "es": "reservado y listo para salir.",
    "it": "prenotata e pronta a partire.",
}
GREETED = re.compile(r"^\s*\S+\s+([A-ZÀ-Ž][\w'-]+),", re.M)


def setup(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS shipment_updates ("
        "rfq_id TEXT PRIMARY KEY, last_update_at REAL, updates INTEGER NOT NULL DEFAULT 0, delivered_at REAL)"
    )


def first_name(quote_body: str) -> str:
    found = GREETED.match(quote_body or "")
    return f" {found.group(1)}" if found and found.group(1).lower() not in ("there", "zusammen") else ""


def compose(row: dict, arrived: bool, agent: str, company: str) -> str:
    language = lang.detect(row.get("email_body") or "") or "en"
    language = language if language in UPDATE else "en"
    note = (row.get("note") or "").strip()
    status = note if note else STATUS[language]
    if status[-1:] not in ".!?":
        status += "."
    template = ARRIVED[language] if arrived else UPDATE[language]
    return template.format(
        first=first_name(row.get("email_body") or ""),
        team=row.get("team_reference") or f"WOC-{row['rfq_id']}",
        route=f"{place(row.get('origin') or '')} to {place(row.get('destination') or '')}"
        if language == "en"
        else f"{place(row.get('origin') or '')} - {place(row.get('destination') or '')}",
        dest=place(row.get("destination") or ""),
        status=status,
        carrier=row.get("carrier") or "the airline",
        ref=row.get("booking_reference"),
        eta=short_day(row.get("eta"), language) or "soon",
        agent=agent,
        company=company,
    )


class ShipmentUpdates:
    def __init__(self, agent_name: str = "Lena", company: str = "WRATHOFCODE Air Freight", now=time.time, today=date.today):
        self.agent_name, self.company, self.now, self.today = agent_name, company, now, today

    def due(self, orch: Any) -> list[dict]:
        conn = orch.store._conn
        with orch.store._write() as w:
            setup(w)
        cur = conn.execute(
            "SELECT b.rfq_id, b.thread_id, b.booking_reference, b.team_reference, b.carrier, b.origin, b.destination, "
            "b.eta, b.note, b.status, r.customer, r.subject, r.email_body, u.last_update_at, u.updates "
            "FROM bookings b JOIN rfqs r ON r.id = b.rfq_id LEFT JOIN shipment_updates u ON u.rfq_id = b.rfq_id "
            "WHERE b.booking_reference IS NOT NULL AND u.delivered_at IS NULL ORDER BY b.booked_at"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    async def tick(self, orch: Any) -> int:
        if not runtime_settings.daily_updates():
            return 0
        latest = orch.store._conn.execute("SELECT MAX(received_at) FROM rfqs").fetchone()[0]
        now = self.now()
        if latest and now - float(latest) < QUIET_AFTER_REQUEST_S:
            return 0
        sent = 0
        for row in self.due(orch):
            if sent >= PER_TICK:
                break
            eta = str(row.get("eta") or "")[:10]
            arrived = bool(eta) and date.fromisoformat(eta) <= self.today()
            if not arrived and row.get("last_update_at") and now - float(row["last_update_at"]) < DUE_S:
                continue
            if not row.get("customer") or not str(row.get("thread_id") or "").isdigit():
                continue
            body = compose(row, arrived, self.agent_name, self.company)
            try:
                await orch.mailbox.send(
                    OutgoingMail(
                        to=row["customer"],
                        subject=reply_subject(row.get("subject") or "Your shipment"),
                        body=body,
                        in_reply_to=int(row["thread_id"]),
                    )
                )
            except Exception:
                log.exception("shipment_update_failed", extra={"rfq": row["rfq_id"]})
                continue
            with orch.store._write() as w:
                w.execute(
                    "INSERT INTO shipment_updates (rfq_id, last_update_at, updates, delivered_at) VALUES (?,?,1,?) "
                    "ON CONFLICT(rfq_id) DO UPDATE SET last_update_at=excluded.last_update_at, "
                    "updates=shipment_updates.updates+1, delivered_at=excluded.delivered_at",
                    (row["rfq_id"], now, now if arrived else None),
                )
            orch.emit(
                Agent.TRACKING,
                "arrival_note" if arrived else "daily_update",
                EventStatus.OK,
                f"{'Arrival note' if arrived else 'Daily update'} sent for {row['booking_reference']}.",
                int(row["rfq_id"]) if str(row["rfq_id"]).isdigit() else None,
            )
            sent += 1
        return sent
