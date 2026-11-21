from __future__ import annotations

import asyncio
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
from mail.writer import WEEKDAYS, arrival_date, capitalize_sentences, money, place, short_day

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
    "{carrier} flies it from {route}{transit}, arriving around {eta}. The all-in price stays at {price}.\n"
    "We'll keep an eye on it and let you know if anything changes.\n\nCheers,\n{agent}\n{company}",
    "de": "Hallo {first},\n\nerledigt, die Sendung ist gebucht. Buchungsnummer {ref}, unsere Referenz {team}.\n"
    "{carrier}, {route}{transit}, Ankunft etwa {eta}. Der All-in-Preis bleibt bei {price}.\n"
    "Wir behalten alles im Blick und melden uns, falls sich etwas ändert.\n\nViele Grüße\n{agent}\n{company}",
    "fr": "Bonjour {first},\n\nc'est réservé. Référence de réservation {ref}, notre référence {team}.\n"
    "{carrier}, {route}{transit}, arrivée vers {eta}. Le prix tout compris reste {price}.\n"
    "Nous suivons l'envoi et vous prévenons si quelque chose change.\n\nBien à vous,\n{agent}\n{company}",
    "es": "Hola {first},\n\nya está reservado. Referencia de reserva {ref}, nuestra referencia {team}.\n"
    "{carrier}, {route}{transit}, llegada sobre el {eta}. El precio todo incluido sigue siendo {price}.\n"
    "Lo seguimos de cerca y te avisamos si cambia algo.\n\nUn saludo,\n{agent}\n{company}",
    "it": "Ciao {first},\n\nfatto, è prenotato. Riferimento prenotazione {ref}, il nostro riferimento {team}.\n"
    "{carrier}, {route}{transit}, arrivo verso {eta}. Il prezzo tutto incluso resta {price}.\n"
    "Lo seguiamo noi e ti avvisiamo se cambia qualcosa.\n\nUn saluto,\n{agent}\n{company}",
    "pl": "Dzień dobry {first},\n\nzarezerwowane. Numer rezerwacji {ref}, nasz numer referencyjny {team}.\n"
    "{carrier}, {route}{transit}, przylot około {eta}. Cena all-in pozostaje {price}.\n"
    "Pilnujemy przesyłki i damy znać, gdyby coś się zmieniło.\n\nPozdrawiam,\n{agent}\n{company}",
}
TRANSIT = {
    "en": ", {n} {unit} in transit",
    "de": ", {n} {unit} Laufzeit",
    "fr": ", {n} {unit} de transit",
    "es": ", {n} {unit} de tránsito",
    "it": ", {n} {unit} di transito",
    "pl": ", {n} {unit} tranzytu",
}
DAYS = {
    "en": ("day", "days"),
    "de": ("Tag", "Tage"),
    "fr": ("jour", "jours"),
    "es": ("día", "días"),
    "it": ("giorno", "giorni"),
    "pl": ("dzień", "dni"),
}


ACCEPT_INTL = re.compile(
    r"好的|同意|确认|请(?:帮我们|为我们)?(?:预订|订舱|安排|下单)|订舱|预订吧|就这个|没问题|"
    r"はい|お願いします|予約(?:を)?お願い|手配(?:を)?お願い|承認|了解しました|それで(?:お願い|進め)|"
    r"네[,，.\s]|좋습니다|예약해|진행해|확정|승인|"
    r"(?<!\w)(?:да|бронируйте|забронируйте|согласны|подтверждаем|оформляйте|давайте|"
    r"evet|onaylıyoruz|rezervasyon yap\w*|kabul ediyoruz|tamam|"
    r"sim|pode reservar|aceitamos|confirmamos|fechado|"
    r"graag boeken|akkoord|boek maar|bevestigd|ga je gang|"
    r"ja tack|boka|godkänt|ja tak|book det|"
    r"rezervujte|souhlasíme|igen|foglalja|da,? rezervați|evet)(?!\w)|"
    r"نعم|موافق|يرجى الحجز|احجز|نوافق|हाँ|जी हाँ|बुक कर|मंज़ूर|ใช่|ตกลง|จองเลย|vâng|đồng ý|đặt chỗ"
)
DECLINE_INTL = re.compile(
    r"不需要|不用了|不要(?:订|预订)|暂不|取消|太贵|不考虑|いいえ|キャンセル|見送り|高すぎ|結構です|"
    r"아니요|취소|비싸|필요 없|"
    r"(?<!\w)(?:нет|не нужно|не будем|отмен\w*|дорого|hayır|iptal|pahalı|não|cancelar|caro demais|"
    r"nee|annuleren|te duur|nej|avbryt|för dyrt|zrušit|lemondjuk)(?!\w)|"
    r"لا نريد|إلغاء|غالي|नहीं|रद्द|ยกเลิก|hủy"
)


def hits(patterns: list[str], text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.I | re.M))


def is_acceptance(body: str) -> bool:
    text = fresh_text(body).lower()
    yes = hits(ACCEPT, text) + len(ACCEPT_INTL.findall(text))
    no = hits(DECLINE, text) + len(DECLINE_INTL.findall(text))
    return yes > 0 and yes > no


def quote_from_mail(body: str, airlines: list[str]) -> tuple[str, str, str] | None:
    """Airline, total and currency of a quote we sent, read back from its text."""
    from core.agents.trucker import parse_price

    text = fresh_text(body or "")
    lowered = text.lower()
    named = [(lowered.find(a.lower()), a) for a in airlines if a and a.lower() in lowered]
    parsed = parse_price(text)
    if not named or parsed is None:
        return None
    return min(named)[1], str(parsed[0]), parsed[1]


def record_sent_quote(
    store: Any,
    rfq_id: int | str,
    thread_id: int | str,
    customer: str,
    subject: str,
    carrier: str,
    total: Any,
    currency: str = "EUR",
    rate_id: str | None = None,
    email_body: str = "",
    received_at: datetime | None = None,
) -> None:
    """Save a quote sent outside the bot (script, second layer, by hand) so a later yes gets booked."""
    rid = str(rfq_id)
    if store._conn.execute("SELECT 1 FROM rfqs WHERE id=?", (rid,)).fetchone() is None:
        store.upsert_rfq(rid, str(thread_id), customer, subject, received_at or datetime.now(UTC), Stage.QUOTED.value)
    store.update_rfq(
        rid,
        status=Stage.QUOTED.value,
        quoted_at=datetime.now(UTC),
        email_body=email_body,
        carrier=carrier,
        total=total,
        currency=currency,
        rate_id=rate_id,
    )


def team_reference(rfq_id: str) -> str:
    return f"WOC-{rfq_id}"


def booking_eta(info: dict, today: date | None = None) -> str:
    """The arrival the quote promised; recomputed the same way only if it was never stored."""
    stored = info.get("arrival")
    if stored:
        return str(stored)[:10]
    return arrival_date(info.get("ready_date"), info.get("transit_days"), today).isoformat()


CONFIRM.update({
    "pt": "Olá {first},\n\nestá reservado. Referência da reserva {ref}, a nossa referência {team}.\n"
    "{carrier}, {route}{transit}, chegada por volta de {eta}. O preço tudo incluído mantém-se em {price}.\n"
    "Acompanhamos o envio e avisamos se algo mudar.\n\nCumprimentos,\n{agent}\n{company}",
    "nl": "Hallo {first},\n\nhet is geboekt. Boekingsreferentie {ref}, onze referentie {team}.\n"
    "{carrier}, {route}{transit}, aankomst rond {eta}. De all-in prijs blijft {price}.\n"
    "We houden het in de gaten en laten het weten als er iets verandert.\n\nGroeten,\n{agent}\n{company}",
    "zh": "{first}，您好！\n\n舱位已经订好。订舱号 {ref}，我们的参考号 {team}。\n"
    "{carrier}，{route}{transit}，预计 {eta} 左右到达。全包价格仍为 {price}。\n"
    "我们会一直跟进这票货，如有变化会及时告诉您。\n\n祝好，\n{agent}\n{company}",
    "ja": "{first}様\n\nご予約が完了しました。予約番号 {ref}、弊社参照番号 {team}。\n"
    "{carrier}、{route}{transit}、{eta}頃に到着予定です。オールイン価格は {price} のままです。\n"
    "引き続き貨物を確認し、変更があればご連絡いたします。\n\nよろしくお願いいたします。\n{agent}\n{company}",
    "ko": "{first}님, 안녕하세요.\n\n예약이 완료되었습니다. 예약 번호 {ref}, 당사 참조 번호 {team}.\n"
    "{carrier}, {route}{transit}, {eta}경 도착 예정입니다. 올인 가격은 {price} 그대로입니다.\n"
    "화물을 계속 확인하고 변경 사항이 있으면 알려 드리겠습니다.\n\n감사합니다.\n{agent}\n{company}",
    "ru": "Здравствуйте, {first}!\n\nГотово, груз забронирован. Номер брони {ref}, наш референс {team}.\n"
    "{carrier}, {route}{transit}, прибытие примерно {eta}. Цена «всё включено» остаётся {price}.\n"
    "Мы следим за отправкой и сообщим, если что-то изменится.\n\nС уважением,\n{agent}\n{company}",
    "tr": "Merhaba {first},\n\nrezervasyon tamam. Rezervasyon numarası {ref}, referansımız {team}.\n"
    "{carrier}, {route}{transit}, tahmini varış {eta}. Her şey dahil fiyat {price} olarak kalıyor.\n"
    "Gönderiyi takip ediyoruz, bir değişiklik olursa haber veririz.\n\nSaygılarımızla,\n{agent}\n{company}",
    "ar": "مرحباً {first}،\n\nتم الحجز. رقم الحجز {ref}، ومرجعنا {team}.\n"
    "{carrier}، {route}{transit}، الوصول المتوقع حوالي {eta}. السعر الشامل يبقى {price}.\n"
    "سنتابع الشحنة ونبلغك بأي تغيير.\n\nمع التحية،\n{agent}\n{company}",
})
TRANSIT.update({
    "pt": ", {n} {unit} de trânsito", "nl": ", {n} {unit} onderweg", "zh": "，运输 {n} {unit}",
    "ja": "、輸送 {n}{unit}", "ko": ", 운송 {n}{unit}", "ru": ", в пути {n} {unit}",
    "tr": ", {n} {unit} transit", "ar": "، مدة النقل {n} {unit}",
})
DAYS.update({
    "pt": ("dia", "dias"), "nl": ("dag", "dagen"), "zh": ("天", "天"), "ja": ("日", "日"),
    "ko": ("일", "일"), "ru": ("день", "дн."), "tr": ("gün", "gün"), "ar": ("يوم", "أيام"),
})
ROUTE_JOIN = {"pt": " para ", "nl": " naar ", "zh": " 至 ", "ja": " → ", "ko": " → ", "ru": " — ", "tr": " → ", "ar": " إلى "}


def confirmation_body(
    booking: dict, rfq: dict, language: str, first: str, agent: str, company: str
) -> str:
    language = language if language in CONFIRM else "en"
    days = int(booking.get("transit_days") or 0)
    one, many = DAYS[language]
    transit = TRANSIT[language].format(n=days, unit=one if days == 1 else many) if days > 0 else ""
    total = rfq.get("total") or booking.get("price")
    currency = rfq.get("currency") or booking.get("currency") or "EUR"
    body = CONFIRM[language].format(
        first=first or {"en": "there"}.get(language, ""),
        ref=booking.get("booking_reference") or "follows shortly",
        team=booking["team_reference"],
        carrier=carrier_name(booking["carrier"]),
        route=f"{place(booking['origin'])}{ROUTE_JOIN.get(language, ' to ')}{place(booking['destination'])}",
        transit=transit,
        eta=short_day(booking["eta"], language) if language in WEEKDAYS else str(booking["eta"])[:10],
        price=money(total, currency, language) if total else "as quoted",
        agent=agent,
        company=company,
    )
    body = re.sub(r"\byour reference (WOC-)", r"our reference \1", body, flags=re.I)
    return capitalize_sentences(re.sub(r" +,", ",", body))


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
        self.declined: set[int] = set()
        self.retry_after_s = 30.0

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
            if int(mail_id) in self.declined:
                continue
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

    async def adopt(self, orch: Any, mail: Mail) -> dict | None:
        """A yes in a thread whose quote the bot did not send itself: read our quote and store it."""
        if mail.in_reply_to is None:
            return None
        try:
            ours = await orch.mailbox.read_one(int(mail.in_reply_to))
        except Exception:
            return None
        our_address = (self.settings.our_address or "").lower()
        if our_address and ours.sender.strip().lower() != our_address:
            return None
        found = quote_from_mail(ours.body, [c.name for c in self.directory.airlines()])
        if found is None:
            orch.emit(
                Agent.BOOKING, "book", EventStatus.HOLD,
                f"Customer accepted in thread {mail.thread_root_id}, but our quote there names no airline and price. "
                "A person should book it now.", mail.thread_root_id,
            )
            return None
        carrier, total, currency = found
        record_sent_quote(
            orch.store, mail.thread_root_id, mail.thread_root_id, mail.sender, ours.subject,
            carrier, total, currency, email_body=ours.body,
        )
        log.info("booking_adopted_quote", extra={"rfq": mail.thread_root_id, "carrier": carrier, "total": total})
        return self._quoted(orch, mail.thread_root_id)

    async def on_reply(self, orch: Any, mail: Mail) -> None:
        if mail.id in self.declined:
            return
        accepted = is_acceptance(mail.body) or is_acceptance(mail.subject)
        rfq = self._quoted(orch, mail.thread_root_id)
        if rfq is not None and rfq.get("status") == Stage.BOOKED.value:
            return
        if (rfq is None or rfq.get("status") not in (Stage.QUOTED.value, Stage.ACCEPTED.value)) and accepted:
            rfq = await self.adopt(orch, mail)
        if rfq is None or rfq.get("status") not in (Stage.QUOTED.value, Stage.ACCEPTED.value):
            return
        if not accepted:
            self.declined.add(mail.id)
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
        if booking is None:
            log.warning("booking_retry", extra={"rfq": rfq_id})
            await asyncio.sleep(self.retry_after_s)
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
        if rate_id:
            done = await self._portal_book(rate_id, team)
            if done:
                return self._record(orch, rfq, info, done, "portal")
            if fresh_enough:
                log.warning("portal_booking_failed_with_fresh_rate", extra={"rfq": rfq_id})
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
            + (f"Rate reference: {rfq.get('rate_id')}.\n" if rfq.get("rate_id") else "")
            + f"Route: {info.get('origin') or rfq.get('origin') or ''} to "
            f"{info.get('destination') or rfq.get('destination') or ''}.\n"
            + (
                f"Chargeable weight: {rfq.get('chargeable_kg')} kg.\n"
                if rfq.get("chargeable_kg")
                else ""
            )
            + f"Agreed price: {info.get('flight') or rfq.get('total')} {rfq.get('currency') or 'EUR'} all-in.\n"
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
        ready = info.get("ready_date")
        eta = booking_eta(info)
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
            "price": str(rfq.get("total") or done.get("price")),
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
        body = confirmation_body(
            booking,
            rfq,
            language,
            proper(find_first_name(mail.sender, mail.body)),
            self.agent_name,
            self.company,
        )
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
