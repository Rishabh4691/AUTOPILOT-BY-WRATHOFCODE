# Start kit: what's in it and how we read it

`data/kit/` holds the start kit (`/kit/start-kit.zip`). `python -m sourcing.kit`
turns the 10 rate sheets into `data/tariffs.json` (10 tariffs, 158 lanes).

## The rules: the same in all 10 sheets

| Rule | Value |
|---|---|
| Currency | EUR (all 10) |
| Valid | 1 to 30 Nov 2026 (all 10). December sheets will arrive by email. |
| Rates | per kg of chargeable weight, one rate per weight bracket |
| Chargeable weight | max(actual, volume weight). **1 cbm = 167 kg** (not cm³/6000) |
| Minimum charge | applies to the **freight only**, before surcharges |
| Fuel + security | per kg of the weight the freight is **billed on**: if we bill at the next break (e.g. 250 kg for a 230 kg shipment), surcharges are charged on 250 kg too |
| Origins | German airports only: CGN, DUS, FRA, HAM, MUC, STR |

`-45` (or `from 0 kg`) is the N rate: under 45 kg. Brackets run from their break up to the next one.

## The 10 sheets

| Airline | File | Layout | Breaks (kg) | Lanes |
|---|---|---|---|---|
| Cobalt Skylift | pdf, 6 pages | one block per lane (`Transit`, `Minimum`, `from 0 kg` …, `Fuel`, `Security`) | 0 45 100 300 500 1000 2000 | 21 |
| Danube Wings Cargo | **2 scanned jpgs** | table + surcharge table on page 2 | 0 45 100 300 500 1000 | 9 |
| Elbflug Air Freight | xlsx | `Origin: CGN` sections, numbers as text with a comma (`3,87`) | 0 45 100 300 500 1000 | 19 |
| Helix Air Freight | pdf | table, `Cologne (CGN) to Lagos (LOS)`, transit `D+4`, `EUR 76.00` | 0 45 100 **250** 500 1000 2000 | 12 |
| Kestrel Airways | xlsx | `Origin:` sections, fuel/security as extra columns, transit `D+4` | 0 45 100 **250** 500 1000 2000 | 18 |
| Orion Cargo Air | pdf, 4 pages | one block per lane, comma decimals | 0 45 100 300 500 1000 | 14 |
| Quetzal Air Freight | docx | table, `0 kg+` headers, comma decimals | 0 45 100 300 500 1000 2000 | 11 |
| Vega Skyfreight | xlsx | `Origin: Cologne (CGN)` sections, real numbers | 0 45 100 300 500 1000 2000 | 13 |
| Wayzata Air Cargo | xlsx | `CGN Cologne > DEL Delhi`, transit `2 days` | 0 45 100 300 500 1000 | 26 |
| Yellowtail Air Freight | txt | table, `EUR 5.92` cells | 0 45 100 **250** 500 1000 2000 | 15 |

## Traps we found

- **Danube is a scan.** OCR misreads 5 of its cells (for example `1,92` as `192`). We use a hand-checked copy,
  `data/kit/danube-wings-cargo-tariff-2026-11.verified.txt`. A December scan will need the same check: the parser
  rejects any row it can't read cleanly and raises an alarm. It never guesses.
- **Breaks differ by airline** (250 vs 300, some have no 2000). Never assume one set of breaks.
- **The next break up can be cheaper**, e.g. Yellowtail CGN-SYD at 230 kg: 230 × 3.87 + 230 × 0.97 = 1,113.20,
  but billed as 250 kg: 250 × 3.02 + 250 × 0.97 = 997.50. `get_sheet_prices` tries every higher break.
- **Some lanes have flat stretches** (two breaks with the same rate, e.g. Quetzal STR-SCL 1000 and 2000 both 2.39).
- **Some minimums are uneven** (138.86, 113.42 …). They are read exactly as printed.
- Rates never rise with weight in any sheet. The parser uses that as a check against misreads.

## Carrier list and pickup zones

- `carrier-list.csv`: 29 airlines (`serves` = destination IATA codes) and 22 truckers (`serves` = pickup zones).
  Only 10 airlines have sheets. The others are on the portal or answer bids by email. Zephyr Steppe, Himalaya
  Bridge, Lagoon Isles and Pampero serve only ASU, KTM, PPT, TNR and ULN, which no sheet covers.
- `pickup_zones.csv`: a zone is the first 2 digits of a German postcode, and it maps to an origin airport
  (e.g. 60 Frankfurt → FRA, 93 Regensburg → MUC). **For door-to-port, the pickup zone fixes the origin airport**,
  and the truckers that serve that zone get the pickup bid request.
- Airline key: we use the email name (`cobalt-skylift`) as `airline_code` for sheets and bids. The portal uses
  2-letter codes; booking matches by code or by name.
