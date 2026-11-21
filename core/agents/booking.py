from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from core.agents.directory import CarrierDirectory
from core.agents.human_writer import carrier_name, proper
from core.agents.portal import PortalPriceSource
from core.config import Settings, auth_headers
from core.contracts import Agent, EventStatus, Mail, MailKind, OutgoingMail, Stage
from mail import lang
from mail.extract import extract as rules_extract
from mail.extract import find_first_name, find_ready
from mail.text import fresh_text, reply_subject
from mail.writer import capitalize_sentences, place

log = logging.getLogger("core.booking")

RATE_FRESH_S = 14 * 60
BOOKING_REF = re.compile(r"\bBK-[A-Za-z0-9]{6,12}\b")

ACCEPT = [
    r"\byes\b",
    r"\bbook (it|this|that|us|the)\b",
    r"\bplease (go ahead|proceed|book)\b",
    r"\bgo ahead\b",
    r"\bwe accept\b",
    r"\baccept(ed)?\b",
    r"\bconfirm(ed)?\b",
    r"\blet'?s do it\b",
    r"\bsounds good\b",
    r"\bthat works\b",
    r"\bworks for us\b",
    r"\bdeal\b",
    r"\bapproved?\b",
    r"\bagreed?\b",
    r"\bproceed\b",
    r"\bwe('ll| will) take it\b",
    r"\bpo (attached|follows|number)\b",
    r"\bpurchase order\b",
    r"\bplease arrange\b",
    r"\bgo for it\b",
    r"\bbook (it|them) in\b",
    r"\bfreigegeben\b",
    r"\bauftrag\b",
    r"\bbon pour accord\b",
    r"\baprobado\b",
    r"\bapprovato\b",
    r"\bzatwierdzam\b",
    r"\bja\b",
    r"\bbitte buchen\b",
    r"\bbuchen sie\b",
    r"\beinverstanden\b",
    r"\bpasst\b",
    r"\bgerne buchen\b",
    r"\boui\b",
    r"\bréserve[rz]?\b",
    r"\bd'accord\b",
    r"\bc'est bon\b",
    r"\bvalid(é|ons)\b",
    r"\bsí\b",
    r"\breserv(a|e|ar|en)\b",
    r"\badelante\b",
    r"\bde acuerdo\b",
    r"\bconfirmamos\b",
    r"\bsì\b",
    r"\bprenot(a|ate|iamo)\b",
    r"\bprocedi(amo|ete)?\b",
    r"\bva bene\b",
    r"\bconfermiamo\b",
    r"\btak\b",
    r"\brezerwuj",
    r"\bakceptuj",
    r"\bzgoda\b",
    r"\bpotwierdzam\b",
]
DECLINE = [
    r"^\s*no\b",
    r"\bno,? thanks?\b",
    r"\bnot (now|yet|interested|needed|go ahead)",
    r"\bdon'?t (book|proceed)\b",
    r"\bwill not\b",
    r"\bwon'?t\b",
    r"\btoo (expensive|high|slow)\b",
    r"\bcancel",
    r"\bdecline",
    r"\bnein\b",
    r"\bnicht buchen\b",
    r"\bzu teuer\b",
    r"\bstorn",
    r"^\s*non\b",
    r"\btrop cher\b",
    r"\bannul",
    r"\bdemasiado caro\b",
    r"\btroppo caro\b",
    r"^\s*nie\b",
    r"\bza drogo\b",
    r"\bcheaper\b",
    r"\bfaster\b",
]

CONFIRM = {
    "en": "Hi {first},\n\ngood news, it's booked. Booking reference {ref}, our reference {team}.\n"
    "{carrier}, {route}, {transit} transit, arriving around {eta}.\n"
    "We'll keep an eye on it and let you know if anything changes.\n\nCheers,\n{agent}\n{company}",
    "de": "Hallo {first},\n\nerledigt, die Sendung ist gebucht. Buchungsnummer {ref}, unsere Referenz {team}.\n"
    "{carrier}, {route}, {transit} Laufzeit, Ankunft etwa {eta}.\n"
    "Wir behalten alles im Blick und melden uns, falls sich etwas ändert.\n\nViele Grüße\n{agent}\n{company}",
    "fr": "Bonjour {first},\n\nc'est réservé. Référence de réservation {ref}, notre référence {team}.\n"
    "{carrier}, {route}, {transit} de transit, arrivée vers {eta}.\n"
    "Nous suivons l'envoi et vous prévenons si quelque chose change.\n\nBien à vous,\n{agent}\n{company}",
    "es": "Hola {first},\n\nya está reservado. Referencia de reserva {ref}, nuestra referencia {team}.\n"
    "{carrier}, {route}, {transit} de tránsito, llegada sobre el {eta}.\n"
    "Lo seguimos de cerca y te avisamos si cambia algo.\n\nUn saludo,\n{agent}\n{company}",
    "it": "Ciao {first},\n\nfatto, è prenotato. Riferimento prenotazione {ref}, il nostro riferimento {team}.\n"
    "{carrier}, {route}, {transit} di transito, arrivo verso {eta}.\n"
    "Lo seguiamo noi e ti avvisiamo se cambia qualcosa.\n\nUn saluto,\n{agent}\n{company}",
    "pl": "Dzień dobry {first},\n\nzarezerwowane. Numer rezerwacji {ref}, Państwa numer {team}.\n"
    "{carrier}, {route}, {transit} tranzytu, przylot około {eta}.\n"
    "Pilnujemy przesyłki i damy znać, gdyby coś się zmieniło.\n\nPozdrawiam,\n{agent}\n{company}",
}
DAYS = {
    "en": ("day", "days"),
    "de": ("Tag", "Tage"),
    "fr": ("jour", "jours"),
    "es": ("día", "días"),
    "it": ("giorno", "giorni"),
    "pl": ("dzień", "dni"),
}


def hits(patterns: list[str], text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.I | re.M))


def is_acceptance(body: str) -> bool:
    text = fresh_text(body).lower()
    yes, no = hits(ACCEPT, text), hits(DECLINE, text)
    return yes > 0 and yes > no


def team_reference(rfq_id: str) -> str:
    return f"WOC-{rfq_id}"


class BookingAgent:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        portal: PortalPriceSource,
        directory: CarrierDirectory,
        outbound: Any = None,
        agent_name: str = "Lena",
        company: str = "WRATHOFCODE Air Freight",
    ) -> None:
        self.client = client
        self.settings = settings
        self.portal = portal
        self.directory = directory
        self.outbound = outbound
        self.agent_name = agent_name
        self.company = company

    def _quoted(self, orch: Any, thread_id: int) -> dict | None:
        row = orch.store._conn.execute(
            "SELECT * FROM rfqs WHERE thread_id=? ORDER BY received_at DESC LIMIT 1",
            (str(thread_id),),
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in orch.store._conn.execute("SELECT * FROM rfqs LIMIT 0").description]
        return dict(zip(cols, row, strict=False))

    def _save(self, orch: Any, **fields: Any) -> None:
        self._ensure_columns(orch)
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "rfq_id")
        with orch.store._write() as conn:
            conn.execute(
                f"INSERT INTO bookings ({cols}) VALUES ({marks}) ON CONFLICT(rfq_id) DO UPDATE SET {updates}",  # noqa: S608
                tuple(fields.values()),
            )

    async def handle(self, orch: Any, mail: Mail, kind: MailKind) -> None:
        try:
            if kind is MailKind.BOOKING_CONFIRMATION:
                self.confirmed(orch, mail)
                return
            await self.on_reply(orch, mail)
        except Exception as error:
            log.exception("booking_failed", extra={"mail": mail.id})
            orch.emit(
                Agent.BOOKING,
                "book",
                EventStatus.ERROR,
                f"Booking for mail {mail.id} failed ({type(error).__name__}). A person should book it.",
                mail.thread_root_id,
            )

    async def recover(self, orch: Any, within_s: float = 1800) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=within_s)
        rows = orch.store._conn.execute(
            "SELECT s.id FROM seen_messages s JOIN rfqs r ON r.thread_id = CAST(s.thread_root_id AS TEXT) "
            "WHERE s.kind = ? AND r.status IN (?, ?) AND s.received_at >= ? ORDER BY s.id",
            (
                MailKind.FOLLOW_UP.value,
                Stage.QUOTED.value,
                Stage.ACCEPTED.value,
                cutoff.isoformat(),
            ),
        ).fetchall()
        done = 0
        for (mail_id,) in rows:
            try:
                mail = await orch.mailbox.read_one(int(mail_id))
            except Exception:
                continue
            await self.handle(orch, mail, MailKind.FOLLOW_UP)
            done += 1
        if done:
            orch.emit(
                Agent.BOOKING,
                "recover",
                EventStatus.INFO,
                f"Re-checked {done} replies for missed bookings.",
            )
        return done

    def confirmed(self, orch: Any, mail: Mail) -> None:
        ref = BOOKING_REF.search(f"{mail.subject} {mail.body}")
        if not ref:
            return
        said = re.search(r"^\s*status:\s*(.+?)\s*$", mail.body, re.I | re.M)
        with orch.store._write() as conn:
            cur = conn.execute(
                "UPDATE bookings SET status='confirmed', confirmed_at=?, note=COALESCE(?, note) "
                "WHERE booking_reference=?",
                (time.time(), said.group(1) if said else None, ref.group(0)),
            )
        if cur.rowcount:
            orch.emit(
                Agent.BOOKING, "confirmed", EventStatus.OK, f"Airline confirmed {ref.group(0)}."
            )

    async def on_reply(self, orch: Any, mail: Mail) -> None:
        rfq = self._quoted(orch, mail.thread_root_id)
        if rfq is None or rfq.get("status") not in (Stage.QUOTED.value, Stage.ACCEPTED.value):
            return
        if not is_acceptance(mail.body) and not is_acceptance(mail.subject):
            orch.emit(
                Agent.RFQ,
                "followup",
                EventStatus.INFO,
                f"Customer replied without accepting: {fresh_text(mail.body)[:120]}",
                int(rfq["id"]),
            )
            return
        rfq_id = str(rfq["id"])
        orch.store.update_rfq(rfq_id, status=Stage.ACCEPTED.value)
        orch.emit(
            Agent.BOOKING,
            "accepted",
            EventStatus.INFO,
            f"Customer accepted quote {rfq_id}.",
            int(rfq_id),
        )
        t0 = time.monotonic()
        info = json.loads(rfq.get("breakdown_json") or "{}")
        info.update(await self._shipment_facts(orch, rfq))
        booking = await self.book(orch, rfq, info)
        ms = int((time.monotonic() - t0) * 1000)
        if booking is None:
            orch.emit(
                Agent.BOOKING,
                "book",
                EventStatus.HOLD,
                f"Could not book request {rfq_id}. A person should book it now.",
                int(rfq_id),
                duration_ms=ms,
            )
            return
        orch.store.update_rfq(rfq_id, status=Stage.BOOKED.value, rate_id=booking.get("rate_id"))
        orch.emit(
            Agent.BOOKING,
            "book",
            EventStatus.OK,
            f"Booked {booking['carrier']} for request {rfq_id}: {booking.get('booking_reference') or 'by email'}.",
            int(rfq_id),
            duration_ms=ms,
        )
        await self.confirm_customer(orch, mail, rfq, info, booking)

    async def book(self, orch: Any, rfq: dict, info: dict) -> dict | None:
        rfq_id = str(rfq["id"])
        team = team_reference(rfq_id)
        rate_id = rfq.get("rate_id")
        quoted_at = rfq.get("quoted_at")
        fresh_enough = bool(quoted_at) and time.time() - float(quoted_at) < RATE_FRESH_S
        if rate_id and fresh_enough:
            done = await self._portal_book(rate_id, team)
            if done:
                return self._record(orch, rfq, info, done, "portal")
        option = await self._fresh(orch, rfq, info)
        if option is not None and option.rate_id:
            done = await self._portal_book(option.rate_id, team)
            if done:
                info = {**info, "transit_days": option.transit_days}
                return self._record(orch, rfq, info, done, "portal")
        return await self._email_airline(orch, rfq, info)

    async def _shipment_facts(self, orch: Any, rfq: dict) -> dict:
        try:
            original = await orch.mailbox.read_one(int(rfq["id"]))
        except Exception:
            return {}
        body = fresh_text(original.body)
        found = find_ready(body)
        facts: dict = {"ready_date": found.isoformat() if found else None}
        try:
            x = rules_extract(original.subject, body, original.sender, str(rfq["id"]))
            facts["gross_kg"] = x.gross_kg
        except Exception:
            facts["gross_kg"] = None
        return facts

    def _ensure_columns(self, orch: Any) -> None:
        if getattr(self, "_columns_ok", False):
            return
        have = {r[1] for r in orch.store._conn.execute("PRAGMA table_info(bookings)")}
        with orch.store._write() as conn:
            for name, kind in (("weight_kg", "REAL"), ("ready_date", "TEXT"), ("note", "TEXT")):
                if have and name not in have:
                    conn.execute(f"ALTER TABLE bookings ADD COLUMN {name} {kind}")
        self._columns_ok = True

    async def _portal_book(self, rate_id: str, team: str) -> dict | None:
        if self.settings.kill_switch:
            return None
        if self.settings.dry_run:
            log.info("dry_run_booking", extra={"rate_id": rate_id, "team": team})
            return {"booking_reference": "BK-DRYRUN00", "rate_id": rate_id, "status": "dry_run"}
        try:
            r = await self.client.post(
                f"{self.settings.base_url}/v1/portal/bookings",
                json={"rate_id": rate_id, "team_reference": team},
                headers=auth_headers(self.settings),
                timeout=15,
            )
        except httpx.HTTPError as error:
            log.warning("portal_booking_error", extra={"error": type(error).__name__})
            return None
        if r.status_code in (200, 201):
            data = r.json()
            return data if isinstance(data, dict) else None
        log.warning("portal_booking_refused", extra={"status": r.status_code, "body": r.text[:200]})
        return None

    async def _fresh(self, orch: Any, rfq: dict, info: dict) -> Any:
        try:
            original = await orch.mailbox.read_one(int(rfq["id"]))
            parsed, _ = await orch.extractor.extract(original)
            airline = info.get("carrier_code") or rfq.get("carrier")
            if not airline:
                return None
            return await self.portal.rate_for(parsed, str(airline))
        except Exception as error:
            log.warning(
                "fresh_rate_failed", extra={"rfq": rfq["id"], "error": type(error).__name__}
            )
            return None

    async def _email_airline(self, orch: Any, rfq: dict, info: dict) -> dict | None:
        carrier = str(rfq.get("carrier") or "")
        contact = next(
            (c for c in self.directory.airlines() if c.name.lower() == carrier.lower()), None
        )
        if contact is None:
            return None
        team = team_reference(str(rfq["id"]))
        body = (
            f"Hello,\n\nplease book the following air freight shipment under our reference {team}.\n"
            f"Route: {info.get('origin') or ''} to {info.get('destination') or ''}.\n"
            f"Chargeable weight: {rfq.get('chargeable_kg')} kg.\n"
            f"Agreed price: {info.get('flight') or rfq.get('total')} {rfq.get('currency') or 'EUR'} all-in.\n"
            "Please confirm with your booking reference.\n\nBest regards,\nWRATHOFCODE Air Freight"
        )
        if self.outbound is None:
            return None
        await self.outbound.send_new(contact.email, f"Booking request {team}", body)
        return self._record(
            orch,
            rfq,
            info,
            {"airline": contact.name, "price": rfq.get("total"), "currency": rfq.get("currency")},
            "email",
        )

    def _record(self, orch: Any, rfq: dict, info: dict, done: dict, method: str) -> dict:
        days = int(info.get("transit_days") or 0)
        today = datetime.now(UTC).date()
        ready = info.get("ready_date")
        depart = (
            max(today + timedelta(days=1), date.fromisoformat(ready))
            if ready
            else today + timedelta(days=1)
        )
        eta = (depart + timedelta(days=days)).isoformat()
        booking = {
            "rfq_id": str(rfq["id"]),
            "thread_id": str(rfq["thread_id"]),
            "customer": rfq.get("customer"),
            "booking_reference": done.get("booking_reference"),
            "team_reference": team_reference(str(rfq["id"])),
            "rate_id": done.get("rate_id"),
            "carrier": done.get("airline") or rfq.get("carrier"),
            "carrier_code": done.get("airline_code") or info.get("carrier_code"),
            "origin": info.get("origin") or rfq.get("origin"),
            "destination": info.get("destination") or rfq.get("destination"),
            "price": str(done.get("price") or rfq.get("total")),
            "currency": done.get("currency") or rfq.get("currency"),
            "transit_days": days,
            "ready_date": ready,
            "weight_kg": info.get("gross_kg"),
            "eta": eta,
            "status": "booked" if method == "portal" else "requested",
            "method": method,
            "booked_at": time.time(),
        }
        self._save(orch, **booking)
        return booking

    async def confirm_customer(
        self, orch: Any, mail: Mail, rfq: dict, info: dict, booking: dict
    ) -> None:
        if not orch.store.claim_outbox(mail.thread_root_id, Stage.BOOKED, mail.id, orch.clock()):
            return
        language = lang.detect(fresh_text(mail.body) or mail.subject)
        language = language if language in CONFIRM else "en"
        days = int(booking.get("transit_days") or 0)
        one, many = DAYS[language]
        eta_date = datetime.fromisoformat(booking["eta"]).date()
        body = CONFIRM[language].format(
            first=proper(find_first_name(mail.sender, mail.body)) or {"en": "there"}.get(language, ""),
            ref=booking.get("booking_reference") or "follows shortly",
            team=booking["team_reference"],
            carrier=carrier_name(booking["carrier"]),
            route=f"{place(booking['origin'])} to {place(booking['destination'])}",
            transit=f"{days} {one if days == 1 else many}",
            eta=f"{eta_date.strftime('%a')} {eta_date.day} {eta_date.strftime('%b')}"
            if language == "en"
            else eta_date.strftime("%d.%m."),
            agent=self.agent_name,
            company=self.company,
        )
        body = capitalize_sentences(re.sub(r" +,", ",", body))
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
            orch.store.mark_outbox_failed(mail.thread_root_id, Stage.BOOKED, type(error).__name__)
            raise
        orch.store.mark_outbox_sent(mail.thread_root_id, Stage.BOOKED, sent.id)
        orch.emit(
            Agent.BOOKING,
            "confirm",
            EventStatus.OK,
            f"Sent booking confirmation for request {rfq['id']}.",
            int(rfq["id"]),
        )
