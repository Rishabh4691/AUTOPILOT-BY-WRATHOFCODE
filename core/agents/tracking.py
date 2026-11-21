from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, timedelta
from typing import Any

from core.contracts import Agent, EventStatus, Mail, OutgoingMail, Stage
from mail import lang
from mail.text import fresh_text, reply_subject

log = logging.getLogger("core.tracking")

BOOKING_REF = re.compile(r"\bBK-[A-Za-z0-9]{6,12}\b", re.I)
TEAM_REF = re.compile(r"\bWOC-(\d+)\b", re.I)
LANE = re.compile(r"\b([A-Z]{3})\s*(?:-|–|→|to|>)\s*([A-Z]{3})\b")

STATUS = {
    "booked": {
        "en": "booked with {carrier} and waiting for the airline's confirmation",
        "de": "bei {carrier} gebucht, die Bestätigung der Airline steht noch aus",
    },
    "confirmed": {
        "en": "booked and confirmed by {carrier}, ready to fly",
        "de": "bei {carrier} gebucht und bestätigt, bereit für den Abflug",
    },
    "requested": {
        "en": "requested with {carrier}, we are waiting for their booking reference",
        "de": "bei {carrier} angefragt, die Buchungsnummer folgt",
    },
}
ANSWER = {
    "en": "Hi,\n\nhere's the latest on {who}.\n"
    "Status: {status}.\n"
    "Booking reference {ref}, our reference {team}, route {route}.\n"
    "Planned departure {depart}, expected arrival {eta}.\n\n"
    "Cheers,\n{agent}\n{company}",
    "de": "Hallo,\n\nhier der aktuelle Stand zu {who}.\n"
    "Status: {status}.\n"
    "Buchungsnummer {ref}, unsere Referenz {team}, Strecke {route}.\n"
    "Geplanter Abflug {depart}, erwartete Ankunft {eta}.\n\n"
    "Viele Grüße\n{agent}\n{company}",
}


def bookings(store: Any) -> list[dict]:
    try:
        cur = store._conn.execute("SELECT * FROM bookings ORDER BY booked_at DESC")
    except sqlite3.Error:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def match(question: str, rows: list[dict]) -> dict | None:
    if not rows:
        return None
    ref = BOOKING_REF.search(question)
    if ref:
        hit = [
            r for r in rows if (r.get("booking_reference") or "").upper() == ref.group(0).upper()
        ]
        if hit:
            return hit[0]
    team = TEAM_REF.search(question)
    if team:
        hit = [r for r in rows if r.get("rfq_id") == team.group(1)]
        if hit:
            return hit[0]
    low = question.lower()
    scored = []
    for r in rows:
        score = 0
        customer = (r.get("customer") or "").lower()
        local = customer.split("@")[0]
        parts = [p for p in re.split(r"[^a-zà-ÿ]+", local) if len(p) >= 4]
        score += sum(3 for p in parts if p in low)
        if r.get("rfq_id") and re.search(rf"\b{re.escape(str(r['rfq_id']))}\b", question):
            score += 4
        lane = LANE.search(question)
        if lane and (lane.group(1), lane.group(2)) == (r.get("origin"), r.get("destination")):
            score += 2
        elif r.get("destination") and re.search(rf"\b{r['destination']}\b", question):
            score += 1
        if r.get("carrier") and r["carrier"].lower() in low:
            score += 2
        if r.get("origin") and r.get("destination"):
            lane_re = rf"\b{r['origin']}\b.{{0,12}}\b{r['destination']}\b"
            if re.search(lane_re, question):
                score += 2
        weight = r.get("weight_kg")
        for w in re.findall(r"(\d[\d.,]*)\s*kg", question, re.I):
            digits = re.sub(r"[.,](?=\d{3}\b)", "", w).replace(",", ".")
            try:
                v = float(digits)
            except ValueError:
                continue
            if weight and abs(v - float(weight)) <= max(1.0, 0.01 * float(weight)):
                score += 3
        if r.get("ready_date") and str(r["ready_date"]) in question:
            score += 2
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]
    if best_score < 2:
        return None
    if len(scored) > 1 and scored[1][0] == best_score:
        return None
    return best


def day(value: str | None, language: str) -> str:
    if not value:
        return "to be confirmed" if language == "en" else "folgt"
    d = date.fromisoformat(value[:10])
    return d.strftime("%a %d %b %Y") if language == "en" else d.strftime("%d.%m.%Y")


class TrackingAgent:
    def __init__(self, agent_name: str = "Lena", company: str = "WRATHOFCODE Air Freight") -> None:
        self.agent_name = agent_name
        self.company = company

    def answer(self, booking: dict, language: str) -> str:
        language = language if language in ANSWER else "en"
        status_key = booking.get("status") if booking.get("status") in STATUS else "booked"
        airline_said = (booking.get("note") or "").strip().rstrip(".")
        carrier = booking.get("carrier") or "the airline"
        status_text = (
            f"{airline_said} ({carrier} confirmed it)"
            if airline_said and language == "en"
            else f"{airline_said} (von {carrier} bestätigt)"
            if airline_said
            else STATUS[status_key][language].format(carrier=carrier)
        )
        transit = int(booking.get("transit_days") or 0)
        eta = booking.get("eta")
        depart = None
        if eta:
            depart = (date.fromisoformat(eta[:10]) - timedelta(days=transit)).isoformat()
        customer = (booking.get("customer") or "").split("@")[0].replace("-", " ").title()
        return ANSWER[language].format(
            who=f"the shipment for {customer}"
            if language == "en"
            else f"der Sendung für {customer}",
            status=status_text,
            ref=booking.get("booking_reference") or "pending",
            team=booking.get("team_reference"),
            route=f"{booking.get('origin')} → {booking.get('destination')}",
            depart=day(depart, language),
            eta=day(eta, language),
            agent=self.agent_name,
            company=self.company,
        )

    async def handle(self, orch: Any, mail: Mail) -> None:
        question = f"{mail.subject}\n{fresh_text(mail.body)}"
        booking = match(question, bookings(orch.store))
        if booking is None:
            orch.emit(
                Agent.TRACKING,
                "answer",
                EventStatus.HOLD,
                f"Tracking question {mail.id} matches no booking. A person should answer: "
                f"{question[:140]}",
            )
            return
        if not orch.store.claim_outbox(mail.thread_root_id, Stage.TRACKING, mail.id, orch.clock()):
            return
        language = lang.detect(fresh_text(mail.body) or mail.subject)
        body = self.answer(booking, language)
        try:
            sent = await orch.mailbox.send(
                OutgoingMail(
                    to=mail.sender,
                    subject=reply_subject(mail.subject),
                    body=body,
                    in_reply_to=mail.id,
                )
            )
        except Exception as error:
            orch.store.mark_outbox_failed(mail.thread_root_id, Stage.TRACKING, type(error).__name__)
            orch.emit(
                Agent.TRACKING, "answer", EventStatus.ERROR, f"Tracking reply failed: {error}"
            )
            return
        orch.store.mark_outbox_sent(mail.thread_root_id, Stage.TRACKING, sent.id)
        orch.emit(
            Agent.TRACKING,
            "answer",
            EventStatus.OK,
            f"Answered tracking question {mail.id} for {booking.get('booking_reference')}.",
            int(booking["rfq_id"]) if str(booking.get("rfq_id", "")).isdigit() else None,
        )
