import re

WORDS = {
    "de": "und der die das ist bitte für mit von wir sie ich nach angebot sendung grüße hallo vielen dank kolli luftfracht ab".split(),
    "fr": "le la les et est pour avec nous vous bonjour merci de des une un colis devis fret cordialement envoi".split(),
    "es": "el la los las y es para con nosotros usted hola gracias de una un bultos cotización envío saludos carga".split(),
    "it": "il lo la gli e è per con noi voi ciao grazie di una un colli preventivo spedizione saluti cordiali".split(),
    "pl": "i w na z do jest dla prosimy dzień dobry dziękuję wycena przesyłka pozdrawiam paczki".split(),
    "nl": "de het een en is voor met wij u hallo bedankt offerte zending groet".split(),
    "pt": "o a os as e é para com nós você olá obrigado de uma um cotação envio carga".split(),
    "en": "the and is for with we you hello hi thanks please of a an quote shipment regards pieces cargo".split(),
    "sv": "och är för med vi ni hej tack vänliga hälsningar offert frakt sändning kollin från till".split(),
    "da": "og er for med vi i hej tak venlig hilsen tilbud fragt forsendelse kolli fra til".split(),
    "no": "og er for med vi dere hei takk vennlig hilsen tilbud frakt sending kolli fra til".split(),
    "fi": "ja on että kanssa me te hei kiitos ystävällisin terveisin tarjous rahti lähetys kollia".split(),
    "cs": "a je pro s my vy dobrý den děkuji prosím nabídka zásilka letecká přeprava pozdravem".split(),
    "sk": "a je pre s my vy dobrý deň ďakujem prosím ponuka zásielka letecká preprava pozdravom".split(),
    "ro": "și este pentru cu noi dumneavoastră bună ziua mulțumesc ofertă expediere transport aerian".split(),
    "hu": "és van a az hogy kérem köszönöm jó napot ajánlat szállítmány légi fuvar üdvözlettel".split(),
    "tr": "ve bir için ile biz siz merhaba teşekkürler lütfen teklif gönderi hava kargo saygılarımla".split(),
    "hr": "i je za s mi vi dobar dan hvala molim ponuda pošiljka zračni prijevoz pozdrav".split(),
    "sl": "in je za z mi vi dober dan hvala prosim ponudba pošiljka letalski prevoz lep pozdrav".split(),
    "id": "dan yang untuk dengan kami anda halo terima kasih mohon penawaran pengiriman kargo udara salam".split(),
    "vi": "và là cho với chúng tôi bạn xin chào cảm ơn báo giá lô hàng vận chuyển hàng không trân trọng".split(),
    "sw": "na ni kwa sisi ninyi habari asante tafadhali bei mzigo usafirishaji wa anga salamu".split(),
    "lt": "ir yra už su mes jūs laba diena ačiū prašome pasiūlymas siunta krovinys pagarbiai".split(),
    "lv": "un ir par ar mēs jūs labdien paldies lūdzu piedāvājums sūtījums krava ar cieņu".split(),
    "et": "ja on eest koos meie teie tere aitäh palun pakkumine saadetis lennukaup lugupidamisega".split(),
    "ca": "i és per amb nosaltres vostè hola gràcies si us plau pressupost enviament càrrega salutacions".split(),
}

NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pl": "Polish",
    "nl": "Dutch", "pt": "Portuguese", "sv": "Swedish", "da": "Danish", "no": "Norwegian", "fi": "Finnish",
    "cs": "Czech", "sk": "Slovak", "ro": "Romanian", "hu": "Hungarian", "tr": "Turkish", "hr": "Croatian",
    "sl": "Slovenian", "id": "Indonesian", "vi": "Vietnamese", "sw": "Swahili", "lt": "Lithuanian",
    "lv": "Latvian", "et": "Estonian", "ca": "Catalan", "ru": "Russian", "uk": "Ukrainian", "bg": "Bulgarian",
    "sr": "Serbian", "el": "Greek", "ar": "Arabic", "fa": "Persian", "ur": "Urdu", "he": "Hebrew",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "th": "Thai", "hi": "Hindi", "bn": "Bengali",
    "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "ka": "Georgian",
    "hy": "Armenian", "am": "Amharic", "km": "Khmer", "my": "Burmese", "si": "Sinhala", "ml": "Malayalam",
    "kn": "Kannada", "lo": "Lao", "ne": "Nepali",
}

SCRIPTS = [
    ("ja", r"[぀-ヿ]"),
    ("ko", r"[가-힯ᄀ-ᇿ]"),
    ("zh", r"[一-鿿]"),
    ("th", r"[฀-๿]"),
    ("lo", r"[຀-໿]"),
    ("km", r"[ក-៿]"),
    ("my", r"[က-႟]"),
    ("el", r"[Ͱ-Ͽ]"),
    ("he", r"[֐-׿]"),
    ("ar", r"[؀-ۿݐ-ݿ]"),
    ("hi", r"[ऀ-ॿ]"),
    ("bn", r"[ঀ-৿]"),
    ("pa", r"[਀-੿]"),
    ("gu", r"[઀-૿]"),
    ("ta", r"[஀-௿]"),
    ("te", r"[ఀ-౿]"),
    ("kn", r"[ಀ-೿]"),
    ("ml", r"[ഀ-ൿ]"),
    ("si", r"[඀-෿]"),
    ("ka", r"[Ⴀ-ჿ]"),
    ("hy", r"[԰-֏]"),
    ("am", r"[ሀ-፿]"),
    ("ru", r"[Ѐ-ӿ]"),
]
CYRILLIC_WORDS = {
    "uk": "і ї є ґ".split(),
    "bg": "ъ".split(),
    "sr": "ђ ј љ њ ћ џ".split(),
}
DEVANAGARI_WORDS = {"mr": "आहे आणि आम्ही कृपया".split(), "ne": "छ हुन्छ हामी कृपया".split()}


def _script(text: str) -> str | None:
    letters = re.findall(r"[^\W\d_]", text)
    if not letters:
        return None
    counts = {code: len(re.findall(pattern, text)) for code, pattern in SCRIPTS}
    if counts["ja"]:
        counts["ja"] += counts["zh"]
    code = max(counts, key=counts.get)
    if counts[code] < max(3, len(letters) * 0.2):
        return None
    if code == "ru":
        lowered = text.lower()
        for other, marks in CYRILLIC_WORDS.items():
            if any(m in lowered for m in marks):
                return other
    if code == "ar":
        if re.search(r"[ٹڈڑںھےۓ]", text):
            return "ur"
        if re.search(r"[پچژگ]", text):
            return "fa"
    if code == "hi":
        for other, words in DEVANAGARI_WORDS.items():
            if sum(1 for w in words if w in text) >= 2:
                return other
    return code


def detect(text: str, default="en") -> str:
    script = _script(text or "")
    if script:
        return script
    tokens = re.findall(r"[^\W\d_][^\W\d_']*", (text or "").lower())
    if not tokens:
        return default
    scores = {lang: sum(1 for t in tokens if t in set(words)) for lang, words in WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else default


def for_request(mail_id: int | str, body: str, default="en") -> str:
    from .files import CACHE

    attached = "\n".join(
        text for (mid, _aid), (_name, text) in list(CACHE.items.items()) if str(mid) == str(mail_id) and text
    )
    if attached.strip():
        return detect(attached, detect(body, default))
    return detect(body, default)
