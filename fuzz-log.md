# Fuzz log

- Round 1: 8 fake RFQs, 6 failed. Fixed comma+each lot counts (je/each/każda), Polish/Italian count words, ready date (lista/pronta, date before keyword, self-drop date), French "à destination de" route, umlaut signature cities, multilingual aerosol/adhesive DG terms.
- Round 2: 10 fake RFQs, 4 failed. Fixed DG "class N" in the body, dest equal to origin when "bring to MUC airport", "en dólares"/Swiss franc currency words, Italian "più veloce" and "pronti", more fastest phrases.
- Round 3 (pricing): sheet source fell back to today when the departure day (ready +1 for door pickup) was after the sheet validity, so expired sheets were priced. Fixed in core/agents/sheets.py.
- Round 4: 10 fake RFQs, 3 failed. Fixed door pickup keeping an explicit "from FRA" instead of the pickup zone airport, German "holt die Ware ab"/"abholbereit" not seen as pickup, "3 x (LxWxH), weight per pallet N kg" lot counts.
- Round 5: 7 fake RFQs, 6 failed. Fixed reference numbers taken as pickup postcode, "not urgent"/"no es urgente" read as fastest, dd/mm/yyyy ready dates, "Kilogramm", Italian "da"/"cadauno" lot phrasing.
- Round 6: 8 fake RFQs, 2 failed. Fixed "Gross weight (kg): 812" / "Volume (cbm): 3.3" without a total label, ready dates written with month names (30 November 2026, 28 de noviembre de 2026, Nov 26, 2026).
- Round 7: 6 fake RFQs, 4 failed. Fixed weight taken from a "RE: FW:" subject, fallback DG check reading quoted history, Outlook history without an address ("From: Sales Team" + "Sent:", underscore line) not cut, "1.2 cbm each" not multiplied by the piece count.
- Round 8: 5 fake RFQs, 5 failed. Fixed US consignee ZIP (IL 60606) taken as pickup postcode, "Express" in a signature company name forcing fastest, Italian "peso lordo kg 450, volume mc 2,5", German "wird bei uns abgeholt", "each 50x40x30 cm and 18.5 kg".
