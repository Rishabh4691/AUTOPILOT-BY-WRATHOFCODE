# Sourcing layer (Aryan): every price source, booking, tariff updates

All prices come from three places. This package asks all of them and returns `PriceOption`s.
Amaan's orchestrator picks one (cheapest, fastest, or 50/50 for bids).

```
RFQ mail ─▶ Shipment ─┬─▶ get_sheet_prices()      data/tariffs.json   (instant, free)
                      ├─▶ get_portal_options()    rate portal API     (rate-limited)
                      └─▶ bid_request_email()     2–5 carriers + truckers by mail → parse_bid_reply()
                                   ▼
                            list[PriceOption]  ─▶  Amaan picks one  ─▶  quote
customer says yes ─▶ book_option()  ─▶ portal booking or booking email
airline mails a new tariff ─▶ ingest_tariff_mail() ─▶ data/tariffs.json (new version)
```

## Setup

```bash
pip install -r sourcing/requirements.txt
echo "FIVEU_API_KEY=<team key>" >> .env        # never commit .env
python -m sourcing.kit                         # rebuilds data/tariffs.json from data/kit/
python -m pytest tests/sourcing -q             # 49 tests
```

## Use it

```python
from sourcing import Shipment, get_sheet_prices, PortalClient, get_portal_options

s = Shipment(
    rfq_id="RFQ-123", origin="FRA", destination="JFK",
    pieces=[{"count": 2, "length": 120, "width": 80, "height": 100}],  # cm (or dim_unit="in")
    gross_weight=300,                                                   # total kg (or weight_unit="lb")
    preference="cheapest", door_pickup=False,
)
sheet = get_sheet_prices(s)                 # every sheet option on the lane, cheapest first
async with PortalClient() as portal:        # key from FIVEU_API_KEY (or TEAM_KEY)
    portal_opts, notes = await get_portal_options(s, portal)
```

Each `PriceOption` has `source` (sheet/portal/bid), `leg` (air/pickup), `airline`, `total` + `currency`
(the all-in for that leg), `total_eur`, `transit_days`, `chargeable_weight_kg`, `billed_weight_kg`,
`lines` (the breakdown for the email), `rate_id`, `valid_until` and `notes` (why, e.g. "billed as 250 kg").

**Door-to-port:** zone = the first 2 digits of the postcode. `sourcing.kit.airport_for_zone(zone)` gives the
origin airport. Add the cheapest trucker `pickup` bid to the air price. Truckers send no tariffs.

**Before quoting:** `sanity_problems(s)` flags lb/kg or in/cm mix-ups (density outside 20–1000 kg/m³)
and bad IATA codes. Hold those for a human.

## Bids

```python
from sourcing import BidTracker, carriers_for, bid_ref, bid_request_email, parse_bid_reply, bid_option
from sourcing.kit import load_carriers

tracker, carriers = BidTracker(), load_carriers()
for c in carriers_for(s, carriers):                 # airlines serving the destination (+ truckers for the zone)
    ref = bid_ref(s.rfq_id, c)
    sent = await mailbox.send(**bid_request_email(s, c, ref))   # POST /v1/mailbox/messages
    tracker.record_sent(sent, s.rfq_id, c, ref)
# for each incoming mail:
if hit := tracker.match(mail):                      # by in_reply_to / references / [BID ref] subject
    option = bid_option(s, hit, parse_bid_reply(mail["body"]))   # None if declined or no price
tracker.waiting(s.rfq_id)                           # carriers that haven't answered yet (for the cut-off)
```

Plain regex parsing, no LLM. A `low` confidence quote means "check before using it".

## Booking

`await book_option(option, team_reference=rfq_id, portal=portal, shipment=s, carriers=carriers)`
returns `BookingResult`: `status` booked / email / failed, `booking_reference`, `price_changed`, and
`email` (when it must be sent instead). See `docs/PORTAL.md` for the status codes.

## New monthly tariffs

```python
import sourcing.kit_parsers                         # registers the parser
from sourcing import is_tariff_mail, ingest_tariff_mail, TariffStore
if is_tariff_mail(mail, carriers):                  # airline sender + sheet attachment
    res = ingest_tariff_mail(mail, [(name, bytes_)], carriers, TariffStore())
    # res.stored, res.notes (decision log), res.alarms (show red in the UI)
```

The newest version valid on the quote date wins, per airline. Old versions stay in the file.
Unreadable rows → alarm, and nothing changes.

## Open questions for the mentors

1. Portal 409 says "already booked under another team_reference". Can two RFQs ever share a rate_id? (We always fetch a fresh one.)
2. Sheet-only airlines can't be booked on the portal. Is a booking email to the airline enough?
3. Is the portal `total` the full air price, or are there flat fees (AWB, handling) on top? The sheets have none.
