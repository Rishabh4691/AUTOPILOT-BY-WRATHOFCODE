import re
import time
from dataclasses import dataclass

from . import kit, store
from .client import Mail
from .config import settings

KINDS = ("rfq", "accept", "followup", "bid", "portal_reply", "booking_confirm", "tariff", "tracking", "other")

ACCEPT = [
    r"\byes\b", r"\bbook (it|this|that|us|the)\b", r"\bplease (go ahead|proceed|book)\b", r"\bgo ahead\b",
    r"\bwe accept\b", r"\baccept(ed)?\b", r"\bconfirm(ed)?\b", r"\blet'?s do it\b", r"\bsounds good\b", r"\bdeal\b",
    r"\bja\b", r"\bbitte buchen\b", r"\bbuchen sie\b", r"\bgebucht\b", r"\beinverstanden\b", r"\bpasst\b", r"\bfreigabe\b",
    r"\boui\b", r"\bréserve[rz]?\b", r"\bd'accord\b", r"\bc'est bon\b", r"\bvalid(é|ons)\b",
    r"\bsí\b", r"\breserv(a|e|ar|en)\b", r"\badelante\b", r"\bde acuerdo\b", r"\bconfirmamos\b",
    r"\bsì\b", r"\bprenot(a|ate|iamo)\b", r"\bprocedi(amo|ete)?\b", r"\bva bene\b", r"\bconfermiamo\b",
    r"\btak\b", r"\brezerwuj", r"\bakceptuj", r"\bzgoda\b", r"\bpotwierdzam\b",
    r"\bja graag\b", r"\bboek\b", r"\bakkoord\b",
]
DECLINE = [
    r"^\s*no\b", r"\bno,? thanks?\b", r"\bnot (now|yet|interested|needed|book)", r"\bdon'?t (book|proceed)\b", r"\bcancel", r"\bdecline", r"\btoo (expensive|high|slow)\b",
    r"\bnein\b", r"\bnicht buchen\b", r"\bkein interesse\b", r"\bstorn", r"^\s*non\b", r"\bne pas\b", r"\bannul", r"\bno gracias\b",
    r"^\s*nie\b", r"\bcheaper\b", r"\bfaster\b", r"\bgünstiger\b", r"\bschneller\b", r"\bmoins cher\b",
    r"\bplus rapide\b", r"\bmás barato\b", r"\bmás rápido\b", r"\bpiù economico\b", r"\bpiù veloce\b", r"\banother option\b",
    r"\balternative\b",
]
RFQ = [
    r"\bquot(e|ation)\b", r"\brfq\b", r"\brate request\b", r"\bair ?freight\b", r"\bshipment\b", r"\bcargo\b",
    r"\bpieces?\b", r"\bpallets?\b", r"\bcartons?\b", r"\bkgs?\b", r"\blbs?\b", r"\bcbm\b", r"\bdims?\b", r"\bdimensions?\b",
    r"\bangebot\b", r"\banfrage\b", r"\bluftfracht\b", r"\bsendung\b", r"\bpaletten?\b", r"\bkolli\b",
    r"\bdevis\b", r"\bcotation\b", r"\bfret aérien\b", r"\bcolis\b",
    r"\bcotización\b", r"\bpresupuesto\b", r"\bcarga aérea\b", r"\bbultos\b",
    r"\bpreventivo\b", r"\bquotazione\b", r"\btrasporto aereo\b", r"\bcolli\b",
    r"\bwycen", r"\boferta\b", r"\bfracht lotnicz", r"\bpaczk",
]
LANE = re.compile(r"\b[A-Z]{3}\s*(?:-|–|to|→|>|nach|à|a)\s*[A-Z]{3}\b")
TRACKING = [
    r"\btrack(ing)?\b", r"\bwhere is\b", r"\bstatus\b", r"\beta\b", r"\barriv", r"\bdelivered\b", r"\bawb\b",
    r"\bsendungsverfolgung\b", r"\bwo ist\b", r"\bsuivi\b", r"\boù en est\b", r"\bseguimiento\b", r"\bdónde está\b",
    r"\btracciamento\b", r"\bdov'è\b", r"\bśledzeni", r"\bgdzie jest\b",
]
TARIFF = [
    r"\btariff", r"\btarif", r"\brate sheet\b", r"\bratesheet\b", r"\bnew rates\b", r"\bprice list\b", r"\bpreisliste\b",
    r"\bvalid from\b", r"\bgültig ab\b", r"\beffective\b", r"\bmonthly rates\b", r"\btarifa\b", r"\btariffa\b",
]
STRONG_TRACK = re.compile(
    r"\b(where is (my|our|the)|track(ing)?|status of|wo ist|sendungsverfolgung|où en est|suivi|dónde está|seguimiento|dov'è|tracciamento|gdzie jest)\b|\bBK-[A-Za-z0-9]{6,}",
    re.I,
)
MEASURES = re.compile(r"\d\s*(kg|kgs|lb|lbs|cm|in|cbm|m3)\b", re.I)
BOOKING_CONFIRM = r"\bbooking\s+BK-[A-Za-z0-9]{4,}\s+(is\s+)?confirmed\b"

QUOTE_CUTS = [
    r"^\s*>.*$",
    r"^\s*(on|am|le|el|il|w dniu)\b.{0,120}(wrote|schrieb|a écrit|escribió|ha scritto|napisał).*$",
    r"^-{2,}\s*(original message|ursprüngliche nachricht|message d'origine|mensaje original|messaggio originale)\s*-{2,}.*$",
    r"^\s*(from|von|de|da|od):\s.*@.*$",
]


@dataclass
class Route:
    kind: str
    reason: str
    carrier: str | None = None
    rfq_id: str | None = None


def fresh_text(body: str) -> str:
    lines = []
    for line in (body or "").splitlines():
        low = line.lower()
        if any(re.match(p, low, re.I) for p in QUOTE_CUTS[1:]):
            break
        if re.match(QUOTE_CUTS[0], line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def hits(patterns, text) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.I | re.M))


def freight_hints(text: str) -> int:
    return hits(RFQ, text) + (1 if LANE.search(text) else 0)


def is_acceptance(text: str) -> bool:
    t = fresh_text(text).lower()
    yes, no = hits(ACCEPT, t), hits(DECLINE, t)
    return yes > 0 and yes > no


def thread_state(db, mail: Mail) -> dict:
    thread = mail.thread_id
    quoted = db.execute(
        "SELECT rfq_id FROM mail_outbox WHERE thread_id=? AND stage='quote' AND state IN ('sent','sending','dry_run','unknown') ORDER BY id LIMIT 1",
        (thread,),
    ).fetchone()
    rfq = db.execute("SELECT id, status FROM rfqs WHERE thread_id=? ORDER BY received_at LIMIT 1", (str(thread),)).fetchone()
    ours = db.execute("SELECT COUNT(*) FROM mail_outbox WHERE thread_id=? AND recipient!=?", (thread, mail.sender_email)).fetchone()[0]
    return {
        "quoted": bool(quoted),
        "rfq_id": (quoted[0] if quoted else None) or (rfq["id"] if rfq else None),
        "rfq_status": rfq["status"] if rfq else None,
        "we_started": ours > 0,
    }


def classify(mail: Mail, db) -> Route:
    sender = mail.sender_email
    text = f"{mail.subject}\n{fresh_text(mail.body)}"
    full = f"{mail.subject}\n{mail.body}"

    if sender == settings.our_address:
        return Route("other", "our own mail")
    if sender == settings.rate_desk:
        return Route("portal_reply", "from rate desk")
    if sender == settings.tracking_desk:
        return Route("tracking", "from tracking desk")

    carrier = kit.carriers().get(sender)
    if carrier:
        if re.search(BOOKING_CONFIRM, full, re.I):
            return Route("booking_confirm", f"booking confirmed by {carrier.name}", carrier.name)
        state = thread_state(db, mail)
        tariff_file = any(a.filename.lower().endswith((".pdf", ".xlsx", ".xls", ".csv", ".docx", ".txt", ".jpg", ".png")) for a in mail.attachments)
        if carrier.kind == "airline" and not state["we_started"] and (hits(TARIFF, full) or tariff_file):
            return Route("tariff", f"tariff from {carrier.name}", carrier.name)
        return Route("bid", f"{carrier.kind} reply from {carrier.name}", carrier.name, state["rfq_id"])

    if re.search(BOOKING_CONFIRM, full, re.I):
        return Route("booking_confirm", "booking confirmation")

    state = thread_state(db, mail)
    if mail.references or mail.in_reply_to:
        if state["quoted"]:
            if is_acceptance(mail.body) or is_acceptance(mail.subject):
                return Route("accept", "yes in a quoted thread", rfq_id=state["rfq_id"])
            return Route("followup", "reply in a quoted thread", rfq_id=state["rfq_id"])
        if state["rfq_id"]:
            return Route("followup", "more info before our quote", rfq_id=state["rfq_id"])
        if state["we_started"]:
            return Route("other", "reply to a mail we started")

    hints = freight_hints(text)
    strong = STRONG_TRACK.search(text) and not MEASURES.search(text)
    if hits(TRACKING, text) and (hints == 0 or strong):
        return Route("tracking", "tracking question from customer")
    if mail.references or mail.in_reply_to:
        return Route("followup", "reply in a thread we don't know yet")
    return Route("rfq", f"new customer thread, {hints} freight hints")


def route(mail: Mail) -> Route:
    t0 = time.monotonic()
    with store.connect() as db:
        r = classify(mail, db)
        db.execute("UPDATE mails SET kind=?, rfq_id=COALESCE(rfq_id, ?) WHERE id=?", (r.kind, r.rfq_id, mail.id))
        store.log_event(
            "router",
            r.rfq_id,
            "route",
            "ok",
            f"{r.kind}: {mail.subject[:70]} ({r.reason})",
            (time.monotonic() - t0) * 1000,
            data={"mail_id": mail.id, "thread_id": mail.thread_id, "from": mail.sender_email, "kind": r.kind},
            db=db,
        )
    return r
