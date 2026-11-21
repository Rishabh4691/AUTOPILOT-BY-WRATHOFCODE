# Fuzz log

- Round 1: 8 fake RFQs, 6 failed. Fixed comma+each lot counts (je/each/każda), Polish/Italian count words, ready date (lista/pronta, date before keyword, self-drop date), French "à destination de" route, umlaut signature cities, multilingual aerosol/adhesive DG terms.
- Round 2: 10 fake RFQs, 4 failed. Fixed DG "class N" in the body, dest equal to origin when "bring to MUC airport", "en dólares"/Swiss franc currency words, Italian "più veloce" and "pronti", more fastest phrases.
- Round 3 (pricing): sheet source fell back to today when the departure day (ready +1 for door pickup) was after the sheet validity, so expired sheets were priced. Fixed in core/agents/sheets.py.
- Round 4: 10 fake RFQs, 3 failed. Fixed door pickup keeping an explicit "from FRA" instead of the pickup zone airport, German "holt die Ware ab"/"abholbereit" not seen as pickup, "3 x (LxWxH), weight per pallet N kg" lot counts.
