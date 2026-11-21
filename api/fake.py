import asyncio
import json
import random
import time
import uuid

from .db import connect

CUSTOMERS = [
    ("Lena Hoffmann", "Bosch Rexroth", "de"),
    ("Marco Bianchi", "Brembo", "it"),
    ("Sophie Laurent", "Hermès Logistique", "fr"),
    ("James Carter", "Siemens Healthineers", "en"),
    ("Anna Kowalska", "LPP", "pl"),
]
ROUTES = [("MUC", "JFK"), ("FRA", "ORD"), ("MUC", "PVG"), ("FRA", "DXB"), ("MUC", "SIN"), ("FRA", "GRU")]
CARRIERS = ["Lufthansa Cargo", "Qatar Cargo", "Cathay Cargo", "Emirates SkyCargo", "Turkish Cargo"]
SOURCES = ["rate sheet", "portal", "carrier bid"]


def log(db, agent, rfq_id, step, status, message, duration_ms=None, cost=0.0, data=None):
    db.execute(
        "INSERT INTO events (ts, agent, rfq_id, step, status, message, duration_ms, llm_cost_usd, data_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (time.time(), agent, rfq_id, step, status, message, duration_ms, cost, json.dumps(data) if data else None),
    )


def price(kg):
    rate = round(random.uniform(1.6, 3.4), 2)
    fuel, security = round(kg * 0.85, 2), round(kg * 0.15, 2)
    lines = [
        {"label": f"Air freight {kg} kg × {rate}", "amount": round(kg * rate, 2)},
        {"label": "Fuel surcharge 0.85/kg", "amount": fuel},
        {"label": "Security surcharge 0.15/kg", "amount": security},
        {"label": "Air waybill", "amount": 35.0},
        {"label": "Handling", "amount": 45.0},
    ]
    return lines, round(sum(l["amount"] for l in lines), 2)


def email(name, origin, dest, kg, carrier, total, pref):
    first = name.split()[0]
    return (
        f"Hi {first},\n\n"
        f"thanks for the request. For {origin} to {dest}, {kg} kg chargeable, the {pref} option is "
        f"{carrier} at EUR {total:,.2f} all-in, transit about {random.randint(2, 5)} days.\n\n"
        "That covers freight, fuel and security surcharges, AWB and handling. Rate is valid for 24 hours.\n"
        "Just reply 'book it' and we'll confirm the space.\n\n"
        "Best,\nWRATHOFCODE Air"
    )


async def run_rfq(speed):
    rid = f"RFQ-{uuid.uuid4().hex[:6].upper()}"
    name, company, _ = random.choice(CUSTOMERS)
    origin, dest = random.choice(ROUTES)
    pref = random.choice(["cheapest", "fastest"])
    kg = round(random.uniform(40, 1400) * 2) / 2
    fails = random.random() < 0.12
    t0 = time.time()

    with connect() as db:
        db.execute(
            "INSERT INTO rfqs (id, thread_id, customer, subject, received_at, status, preference, origin, destination) VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, rid, f"{name} ({company})", f"Air quote {origin}-{dest}", t0, "NEW", pref, origin, dest),
        )
        log(db, "router", rid, "route", "ok", f"Customer RFQ from {company}", random.randint(40, 300))

    async def step(status, agent, name_, ok_msg, delay, **kw):
        await asyncio.sleep(delay / speed)
        with connect() as db:
            db.execute("UPDATE rfqs SET status=? WHERE id=?", (status, rid))
            log(db, agent, rid, name_, kw.pop("st", "info"), ok_msg, **kw)

    await step("EXTRACTED", "rfq", "extract", f"{origin}→{dest}, {kg} kg chargeable, wants {pref}", 3, st="start")
    await step("SOURCING", "rfq", "source", "Asked portal and 3 carriers for rates", 4)
    await asyncio.sleep(random.uniform(20, 70) / speed)

    lines, total = price(kg)
    carrier = random.choice(CARRIERS)
    with connect() as db:
        human = db.execute("SELECT human_takeover FROM rfqs WHERE id=?", (rid,)).fetchone()[0]
        if human:
            log(db, "rfq", rid, "hold", "info", "Held for human, autopilot paused")
            return
        breakdown = {
            "lines": lines,
            "total": total,
            "currency": "EUR",
            "chargeable_kg": kg,
            "source": random.choice(SOURCES),
            "candidates": [
                {"carrier": c, "source": random.choice(SOURCES), "total": round(total * random.uniform(1.0, 1.25), 2)}
                for c in random.sample(CARRIERS, 3)
            ],
        }
        db.execute(
            "UPDATE rfqs SET status='PRICED', chargeable_kg=?, carrier=?, total=?, currency='EUR', breakdown_json=? WHERE id=?",
            (kg, carrier, total, json.dumps(breakdown), rid),
        )
        log(db, "rfq", rid, "price", "info", f"Best: {carrier} EUR {total:,.2f}", data={"total": total})

    await asyncio.sleep(4 / speed)
    duration = int((time.time() - t0) * 1000 * speed)
    with connect() as db:
        if fails:
            db.execute("UPDATE rfqs SET status='FAILED' WHERE id=?", (rid,))
            log(db, "rfq", rid, "quote", "fail", "Quote rejected: price above best by 7%", duration)
            return
        body = email(name, origin, dest, kg, carrier, total, pref)
        db.execute(
            "UPDATE rfqs SET status='QUOTED', quoted_at=?, email_body=?, rate_id=? WHERE id=?",
            (time.time(), body, f"R-{uuid.uuid4().hex[:8]}", rid),
        )
        log(db, "rfq", rid, "quote", "ok", f"Quote sent: EUR {total:,.2f}", duration, round(random.uniform(0.00012, 0.00026), 6))

    if random.random() < 0.6:
        await asyncio.sleep(random.uniform(15, 40) / speed)
        with connect() as db:
            db.execute("UPDATE rfqs SET status='ACCEPTED' WHERE id=?", (rid,))
            log(db, "router", rid, "route", "ok", "Customer accepted the quote", random.randint(40, 200))
            log(db, "booking", rid, "book", "start", f"Booking {carrier}")
        await asyncio.sleep(3 / speed)
        with connect() as db:
            db.execute("UPDATE rfqs SET status='BOOKED' WHERE id=?", (rid,))
            log(db, "booking", rid, "book", "ok", f"Booked on {carrier}", random.randint(1500, 6000))


async def side_traffic(speed):
    while True:
        await asyncio.sleep(random.uniform(25, 60) / speed)
        with connect() as db:
            if random.random() < 0.7:
                log(db, "router", None, "route", "ok", "Tracking question", random.randint(40, 200))
                ok = random.random() < 0.92
                log(db, "tracking", None, "answer", "ok" if ok else "fail",
                    "Answered: shipment departed, ETA tomorrow" if ok else "No booking found for reference",
                    random.randint(400, 3500))
            else:
                airline = random.choice(CARRIERS)
                log(db, "router", None, "route", "ok", f"Tariff sheet from {airline}", random.randint(40, 200))
                log(db, "tariff", None, "ingest", "ok", f"Loaded new {airline} tariff, 142 lanes", random.randint(2000, 9000))


async def run(speed=6.0, every=360):
    asyncio.create_task(side_traffic(speed))
    while True:
        asyncio.create_task(run_rfq(speed))
        await asyncio.sleep(every / speed)
