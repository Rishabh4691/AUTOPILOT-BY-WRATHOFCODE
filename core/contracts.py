from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

CENT = Decimal("0.01")


def to_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must carry a timezone")
    return value.astimezone(UTC)


def _iata(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"not an IATA airport code: {value!r}")
    return code


def _currency(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"not a currency code: {value!r}")
    return code


Money = Annotated[Decimal, AfterValidator(to_money)]
UtcDatetime = Annotated[datetime, AfterValidator(_utc)]
Iata = Annotated[str, AfterValidator(_iata)]
Currency = Annotated[str, AfterValidator(_currency)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Preference(StrEnum):
    CHEAPEST = "cheapest"
    FASTEST = "fastest"


class Stage(StrEnum):
    NEW = "NEW"
    EXTRACTED = "EXTRACTED"
    SOURCING = "SOURCING"
    PRICED = "PRICED"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    BOOKED = "BOOKED"
    TRACKING = "TRACKING"
    HELD = "HELD"
    SKIPPED = "SKIPPED"
    WAITING_DOCS = "WAITING_DOCS"


class MailKind(StrEnum):
    RFQ = "rfq"
    FOLLOW_UP = "follow_up"
    CARRIER_BID = "carrier_bid"
    TRUCKER_BID = "trucker_bid"
    PORTAL_REPLY = "portal_reply"
    BOOKING_CONFIRMATION = "booking_confirmation"
    TARIFF = "tariff"
    TRACKING = "tracking"
    OWN = "own"
    OTHER = "other"


class Agent(StrEnum):
    ROUTER = "router"
    RFQ = "rfq"
    BOOKING = "booking"
    TRACKING = "tracking"
    TARIFF = "tariff"


class EventStatus(StrEnum):
    OK = "ok"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    HOLD = "hold"


class Attachment(Frozen):
    id: int
    filename: str
    content_type: str = "application/octet-stream"
    size: int | None = None


class Mail(Frozen):
    id: int
    sender: str
    to: str
    subject: str
    body: str
    in_reply_to: int | None
    references: tuple[int, ...]
    received_at: UtcDatetime
    attachments: tuple[Attachment, ...] = ()

    @property
    def thread_root_id(self) -> int:
        return self.references[0] if self.references else self.id


class OutgoingMail(Frozen):
    to: str
    subject: str
    body: str
    in_reply_to: int


class Piece(Frozen):
    count: int = Field(ge=1)
    length_cm: PositiveDecimal
    width_cm: PositiveDecimal
    height_cm: PositiveDecimal
    weight_kg: PositiveDecimal | None = None


class RFQ(Frozen):
    mail_id: int
    thread_root_id: int
    customer: str
    subject: str
    origin: Iata
    destination: Iata
    pieces: tuple[Piece, ...]
    gross_kg: PositiveDecimal
    volume_cbm: Decimal | None = None
    door_pickup: bool
    pickup_zone: str | None = None
    pickup_postcode: str | None = None
    preference: Preference
    preference_assumed: bool
    ready_date: date | None = None
    currency: Currency | None = None
    received_at: UtcDatetime
    notes: tuple[str, ...] = ()


class Breakdown(Frozen):
    chargeable_kg: Decimal
    freight: Money = Decimal("0")
    fuel: Money = Decimal("0")
    security: Money = Decimal("0")
    other_surcharges: Money = Decimal("0")
    fees: Money = Decimal("0")
    pickup: Money = Decimal("0")
    fx_note: str | None = None


class PriceOption(Frozen):
    source: str
    carrier: str
    carrier_code: str | None = None
    rate_id: str | None = None
    rate_id_at: UtcDatetime | None = None
    valid_until: UtcDatetime | None = None
    total: Money
    currency: Currency
    transit_days: int = Field(ge=0)
    includes_pickup: bool = False
    breakdown: Breakdown | None = None


class PickupPrice(Frozen):
    source: str
    trucker: str
    zone: str
    total: Money
    currency: Currency
    received_at: UtcDatetime
    pickup_hours: Decimal | None = None


class Bid(Frozen):
    carrier: str
    mail_id: int
    total: Money
    currency: Currency
    transit_days: int = Field(ge=0)
    received_at: UtcDatetime


class LlmUsage(Frozen):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal | None = None
    duration_ms: int = 0


class LlmResult(Frozen):
    text: str
    usage: LlmUsage


class Quote(Frozen):
    rfq_mail_id: int
    thread_root_id: int
    to: str
    subject: str
    option: PriceOption
    pickup: PickupPrice | None = None
    total: Money
    currency: Currency
    body: str
    used_llm: bool
    usage: LlmUsage | None = None


class Booking(Frozen):
    booking_reference: str
    team_reference: str
    rate_id: str
    carrier: str
    carrier_code: str
    price: Money
    currency: Currency
    status: str


class Event(Frozen):
    ts: UtcDatetime
    agent: Agent
    step: str
    status: EventStatus
    message: str
    rfq_id: str | None = None
    duration_ms: int | None = None
    llm_cost_usd: Decimal = Decimal("0")
    data: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class Classification(Frozen):
    kind: MailKind
    reason: str


class ExtractionError(Exception):
    pass


class SourceUnavailable(Exception):
    pass


@runtime_checkable
class MailboxClient(Protocol):
    async def poll(self, since_id: int) -> tuple[list[Mail], int]: ...

    async def send(self, mail: OutgoingMail) -> Mail: ...

    async def read_one(self, message_id: int) -> Mail: ...


@runtime_checkable
class MailClassifier(Protocol):
    def classify(self, mail: Mail, known_rfq_threads: frozenset[int]) -> Classification: ...


@runtime_checkable
class LlmClient(Protocol):
    async def complete(
        self, system: str, user: str, max_output_tokens: int, json_mode: bool = False
    ) -> LlmResult: ...


@runtime_checkable
class RfqExtractor(Protocol):
    async def extract(self, mail: Mail) -> tuple[RFQ, LlmUsage | None]: ...


@runtime_checkable
class PriceSource(Protocol):
    name: str

    async def quote(self, rfq: RFQ) -> list[PriceOption]: ...


@runtime_checkable
class PickupSource(Protocol):
    name: str

    async def request(self, rfq: RFQ) -> None: ...

    async def collect(self, rfq: RFQ) -> PickupPrice | None: ...


@runtime_checkable
class EmailWriter(Protocol):
    async def write(
        self, rfq: RFQ, option: PriceOption, total: Decimal, currency: str
    ) -> tuple[str, LlmUsage | None]: ...


@runtime_checkable
class Booker(Protocol):
    async def book(self, option: PriceOption, team_reference: str) -> Booking: ...


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


Verdict = Literal["send", "wait", "hold"]


def options_in(options: Sequence[PriceOption], currency: str) -> list[PriceOption]:
    return [option for option in options if option.currency == currency]
