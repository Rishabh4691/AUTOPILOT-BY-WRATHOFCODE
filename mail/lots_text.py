"""Words for the one-reply-per-request text when a request holds several shipments."""

from .writer import WEEKDAYS, money, place, short_day

TEXT = {
    "en": {
        "hi": "Hi {first},", "intro": "thanks for the request. Here are your {n} shipments, each priced on its own as you asked:",
        "line": "{i}. {route}, {what}{kg} kg: I would go with {carrier}, the {pref} choice, {days} days in transit, arriving around {eta}. All-in price {price}, including {truck}air freight, fuel and security.",
        "truck": "the truck from your site to the airport, ", "pieces": "{n} pieces, ", "to": " to ",
        "end": "The prices are valid today, and a yes for one or all of them is all I need to book. Our reference is {ref}.",
        "sign": "Cheers,", "pref": {"fastest": "fastest", "cheapest": "cheapest"},
        "booked": "good news, all {n} shipments are booked:", "booked_line": "{i}. {route}: {carrier}, booking reference {bk}, all-in {price}, arriving around {eta}.",
        "booked_end": "We'll keep an eye on them and let you know if anything changes. Our reference is {ref}.",
    },
    "de": {
        "hi": "Hallo {first},", "intro": "danke für die Anfrage. Hier sind Ihre {n} Sendungen, jede einzeln kalkuliert, wie gewünscht:",
        "line": "{i}. {route}, {what}{kg} kg: Ich würde {carrier} nehmen, die {pref} Lösung, {days} Tage Laufzeit, Ankunft etwa {eta}. All-in-Preis {price}, inklusive {truck}Luftfracht, Treibstoff und Sicherheit.",
        "truck": "Lkw von Ihrem Standort zum Flughafen, ", "pieces": "{n} Packstücke, ", "to": " nach ",
        "end": "Die Preise gelten heute, ein Ja für eine oder alle Sendungen genügt mir zum Buchen. Unsere Referenz ist {ref}.",
        "sign": "Viele Grüße", "pref": {"fastest": "schnellste", "cheapest": "günstigste"},
        "booked": "gute Nachricht, alle {n} Sendungen sind gebucht:", "booked_line": "{i}. {route}: {carrier}, Buchungsnummer {bk}, all-in {price}, Ankunft etwa {eta}.",
        "booked_end": "Wir behalten alles im Blick und melden uns, falls sich etwas ändert. Unsere Referenz ist {ref}.",
    },
    "fr": {
        "hi": "Bonjour {first},", "intro": "merci pour votre demande. Voici vos {n} envois, chacun chiffré séparément comme demandé :",
        "line": "{i}. {route}, {what}{kg} kg : je partirais avec {carrier}, l'option la plus {pref}, {days} jours de transit, arrivée vers {eta}. Prix tout compris {price}, incluant {truck}le fret aérien, le carburant et la sûreté.",
        "truck": "le camion de votre site à l'aéroport, ", "pieces": "{n} colis, ", "to": " à ",
        "end": "Les prix sont valables aujourd'hui, un oui pour un ou tous les envois suffit pour réserver. Notre référence est {ref}.",
        "sign": "Bien à vous,", "pref": {"fastest": "rapide", "cheapest": "économique"},
        "booked": "bonne nouvelle, les {n} envois sont réservés :", "booked_line": "{i}. {route} : {carrier}, référence de réservation {bk}, tout compris {price}, arrivée vers {eta}.",
        "booked_end": "Nous suivons les envois et vous prévenons si quelque chose change. Notre référence est {ref}.",
    },
    "es": {
        "hi": "Hola {first},", "intro": "gracias por la solicitud. Aquí tiene sus {n} envíos, cada uno cotizado por separado:",
        "line": "{i}. {route}, {what}{kg} kg: iría con {carrier}, la opción más {pref}, {days} días de tránsito, llegada sobre el {eta}. Precio todo incluido {price}, con {truck}flete aéreo, combustible y seguridad.",
        "truck": "el camión de su sitio al aeropuerto, ", "pieces": "{n} bultos, ", "to": " a ",
        "end": "Los precios valen hoy, y un sí para uno o todos los envíos basta para reservar. Nuestra referencia es {ref}.",
        "sign": "Un saludo,", "pref": {"fastest": "rápida", "cheapest": "económica"},
        "booked": "buenas noticias, los {n} envíos están reservados:", "booked_line": "{i}. {route}: {carrier}, referencia de reserva {bk}, todo incluido {price}, llegada sobre el {eta}.",
        "booked_end": "Los seguimos de cerca y le avisamos si cambia algo. Nuestra referencia es {ref}.",
    },
    "it": {
        "hi": "Ciao {first},", "intro": "grazie per la richiesta. Ecco le sue {n} spedizioni, ognuna quotata a parte come richiesto:",
        "line": "{i}. {route}, {what}{kg} kg: sceglierei {carrier}, l'opzione più {pref}, {days} giorni di transito, arrivo verso {eta}. Prezzo tutto incluso {price}, con {truck}trasporto aereo, carburante e sicurezza.",
        "truck": "il camion dalla vostra sede all'aeroporto, ", "pieces": "{n} colli, ", "to": " a ",
        "end": "I prezzi valgono oggi, e un sì per una o tutte le spedizioni basta per prenotare. Il nostro riferimento è {ref}.",
        "sign": "Un saluto,", "pref": {"fastest": "veloce", "cheapest": "economica"},
        "booked": "buone notizie, tutte le {n} spedizioni sono prenotate:", "booked_line": "{i}. {route}: {carrier}, riferimento prenotazione {bk}, tutto incluso {price}, arrivo verso {eta}.",
        "booked_end": "Le seguiamo noi e la avvisiamo se cambia qualcosa. Il nostro riferimento è {ref}.",
    },
    "nl": {
        "hi": "Hallo {first},", "intro": "bedankt voor de aanvraag. Hier zijn uw {n} zendingen, elk apart berekend zoals gevraagd:",
        "line": "{i}. {route}, {what}{kg} kg: ik zou gaan voor {carrier}, de {pref} optie, {days} dagen onderweg, aankomst rond {eta}. All-in prijs {price}, inclusief {truck}luchtvracht, brandstof en beveiliging.",
        "truck": "de truck van uw locatie naar de luchthaven, ", "pieces": "{n} colli, ", "to": " naar ",
        "end": "De prijzen gelden vandaag, een ja voor één of alle zendingen is genoeg om te boeken. Onze referentie is {ref}.",
        "sign": "Groeten,", "pref": {"fastest": "snelste", "cheapest": "goedkoopste"},
        "booked": "goed nieuws, alle {n} zendingen zijn geboekt:", "booked_line": "{i}. {route}: {carrier}, boekingsreferentie {bk}, all-in {price}, aankomst rond {eta}.",
        "booked_end": "We houden ze in de gaten en laten het weten als er iets verandert. Onze referentie is {ref}.",
    },
    "pt": {
        "hi": "Olá {first},", "intro": "obrigado pelo pedido. Aqui estão os seus {n} envios, cada um cotado à parte como pediu:",
        "line": "{i}. {route}, {what}{kg} kg: eu iria com {carrier}, a opção mais {pref}, {days} dias de trânsito, chegada por volta de {eta}. Preço tudo incluído {price}, com {truck}frete aéreo, combustível e segurança.",
        "truck": "o camião do seu local ao aeroporto, ", "pieces": "{n} volumes, ", "to": " para ",
        "end": "Os preços valem hoje, e um sim para um ou todos os envios basta para reservar. A nossa referência é {ref}.",
        "sign": "Cumprimentos,", "pref": {"fastest": "rápida", "cheapest": "económica"},
        "booked": "boas notícias, os {n} envios estão reservados:", "booked_line": "{i}. {route}: {carrier}, referência da reserva {bk}, tudo incluído {price}, chegada por volta de {eta}.",
        "booked_end": "Acompanhamos os envios e avisamos se algo mudar. A nossa referência é {ref}.",
    },
    "zh": {
        "hi": "{first}，您好！", "intro": "感谢您的询价。以下是您的 {n} 票货，按您的要求分别报价：",
        "line": "{i}. {route}，{what}{kg} kg：建议选择 {carrier}，{pref}方案，运输 {days} 天，预计 {eta} 左右到达。全包价格 {price}，包含{truck}空运费、燃油费和安检费。",
        "truck": "从贵司到机场的卡车提货、", "pieces": "{n} 件，", "to": " 至 ",
        "end": "以上价格今天有效，您确认其中一票或全部即可订舱。我们的参考号是 {ref}。",
        "sign": "祝好，", "pref": {"fastest": "最快", "cheapest": "最经济"},
        "booked": "好消息，{n} 票货已全部订好：", "booked_line": "{i}. {route}：{carrier}，订舱号 {bk}，全包 {price}，预计 {eta} 左右到达。",
        "booked_end": "我们会一直跟进，如有变化会及时告诉您。我们的参考号是 {ref}。",
    },
    "ja": {
        "hi": "{first}様", "intro": "お見積りのご依頼ありがとうございます。ご希望どおり、{n} 件の貨物をそれぞれお見積りしました：",
        "line": "{i}. {route}、{what}{kg} kg：{carrier}（{pref}プラン）をおすすめします。輸送 {days} 日、{eta}頃到着予定です。オールイン価格 {price}（{truck}航空運賃、燃油、保安料込み）。",
        "truck": "御社から空港までのトラック、", "pieces": "{n} 個、", "to": " → ",
        "end": "価格は本日有効です。いずれか、またはすべてご承認いただければ手配いたします。弊社参照番号は {ref} です。",
        "sign": "よろしくお願いいたします。", "pref": {"fastest": "最速", "cheapest": "最安"},
        "booked": "{n} 件すべての予約が完了しました：", "booked_line": "{i}. {route}：{carrier}、予約番号 {bk}、オールイン {price}、{eta}頃到着予定。",
        "booked_end": "引き続き貨物を確認し、変更があればご連絡いたします。弊社参照番号は {ref} です。",
    },
}


def words(lang: str) -> dict:
    return TEXT.get(lang, TEXT["en"])


def day(value, lang: str) -> str:
    return short_day(value, lang) if lang in WEEKDAYS else str(value)[:10]


def route(origin: str, destination: str, lang: str) -> str:
    return f"{place(origin)}{words(lang)['to']}{place(destination)}"


def price(amount, currency: str, lang: str) -> str:
    return money(amount, currency, lang if lang in WEEKDAYS else "en")
