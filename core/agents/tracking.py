from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, timedelta
from typing import Any

from core.agents.human_writer import carrier_name
from core.contracts import Agent, EventStatus, Mail, OutgoingMail, Stage
from mail import lang
from mail.extract import find_first_name
from mail.text import fresh_text, reply_subject
from mail.writer import capitalize_sentences, money, place, short_day

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
    "en": "Hi{first},\n\nhere's the latest on our reference {team} (airline booking {ref}).\n"
    "{status}\n"
    "{carrier} flies it from {route}{depart}, arriving around {eta}.{price}\n\n"
    "Cheers,\n{agent}\n{company}",
    "de": "Hallo{first},\n\nhier der aktuelle Stand zu unserer Referenz {team} (Buchungsnummer {ref}).\n"
    "{status}\n"
    "{carrier} fliegt die Sendung von {route}{depart}, Ankunft etwa {eta}.{price}\n\n"
    "Viele Grüße\n{agent}\n{company}",
}
AIRLINE_SAID = {
    "en": "Latest status from {carrier}: {said}",
    "de": "Letzter Status von {carrier}: {said}",
}
DEPART = {"en": ", leaving {day}", "de": ", Abflug {day}"}
PRICE = {"en": " The all-in price is {price}.", "de": " Der All-in-Preis ist {price}."}


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
    return short_day(value, language)


def departure_of(booking: dict) -> str | None:
    """Departure consistent with the quoted arrival (arrival = departure + 1 + transit)."""
    transit = int(booking.get("transit_days") or 0)
    eta = booking.get("eta")
    if eta and transit > 0:
        return (date.fromisoformat(str(eta)[:10]) - timedelta(days=1 + transit)).isoformat()
    ready = booking.get("ready_date")
    return str(ready)[:10] if ready else None


def _upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def asker_name(body: str) -> str:
    """First name of the person asking, only when their mail signs with one."""
    name = find_first_name("", fresh_text(body or ""))
    return name if name and name[:1].isupper() and name.isalpha() else ""


class TrackingAgent:
    def __init__(self, agent_name: str = "Lena", company: str = "WRATHOFCODE Air Freight") -> None:
        self.agent_name = agent_name
        self.company = company

    def answer(self, booking: dict, language: str, first: str = "") -> str:
        language = language if language in ANSWER else "en"
        status_key = booking.get("status") if booking.get("status") in STATUS else "booked"
        airline_said = (booking.get("note") or "").strip()
        carrier = carrier_name(booking.get("carrier") or "") or "the airline"
        if airline_said:
            if airline_said[-1] not in ".!?":
                airline_said += "."
            status_text = AIRLINE_SAID[language].format(carrier=carrier, said=airline_said)
        else:
            status_text = _upper(STATUS[status_key][language].format(carrier=carrier)) + "."
        depart = departure_of(booking)
        price = booking.get("price")
        joiner = " to " if language == "en" else " nach "
        return capitalize_sentences(
            ANSWER[language].format(
                first=f" {first}" if first else "",
                status=status_text,
                ref=booking.get("booking_reference") or "pending",
                team=booking.get("team_reference"),
                carrier=carrier,
                route=place(str(booking.get("origin")))
                + joiner
                + place(str(booking.get("destination"))),
                depart=DEPART[language].format(day=day(depart, language)) if depart else "",
                eta=day(booking.get("eta"), language),
                price=PRICE[language].format(
                    price=money(price, booking.get("currency") or "EUR", language)
                )
                if price and price != "None"
                else "",
                agent=self.agent_name,
                company=self.company,
            )
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
        body = self.answer(booking, language, asker_name(mail.body))
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
