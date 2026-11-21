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
}


def detect(text: str, default="en") -> str:
    tokens = re.findall(r"[a-zà-ÿąćęłńóśźż']+", (text or "").lower())
    if not tokens:
        return default
    scores = {lang: sum(1 for t in tokens if t in set(words)) for lang, words in WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else default
