"""Wishes the engine does not price: flag them so a person can look before the quote goes out."""

import re

FOREIGN_SITE = re.compile(
    r"\b(?:pick ?up|collect\w*|abhol\w*|from our (?:site|warehouse|plant|factory)|at our (?:site|warehouse|plant|factory)|"
    r"enlèvement|recogida|ritiro)\b[^.\n]{0,90}?\b(austria|österreich|vienna|wien|graz|linz|salzburg|switzerland|schweiz|suisse|"
    r"zürich|zurich|basel|bern|geneva|genf|france|frankreich|paris|lyon|netherlands|niederlande|holland|amsterdam|rotterdam|"
    r"belgium|belgien|brussels|brüssel|antwerp|poland|polen|warsaw|warschau|czech|tschechien|prague|prag|denmark|dänemark|"
    r"copenhagen|italy|italien|milan|mailand|spain|spanien|madrid|barcelona|luxembourg|luxemburg|sweden|schweden)\b",
    re.I,
)
DOOR_DELIVERY = re.compile(
    r"\b(door[- ]to[- ]door|deliver(?:y|ed)? to (?:the |our |their )?(?:consignee|customer'?s?|door|warehouse|premises|address|plant)|"
    r"(?:incl\w*|plus|with) (?:the )?(?:final )?delivery (?:at|in|to) (?:destination|the destination)|"
    r"\bDDP\b|\bDAP\b|zustellung (?:beim|an den) empfänger|bis zum empfänger|livraison (?:au|chez le) destinataire|"
    r"entrega (?:al|en) (?:destinatario|puerta)|consegna (?:al|presso il) destinatario)\b",
    re.I,
)
INSURANCE = re.compile(r"\b(insurance|insured|insure|versicherung|versichert|assurance|assuré|seguro|assicurazion\w*|ubezpiecz\w*)\b", re.I)


def special_wishes(text: str) -> list[str]:
    found = []
    if FOREIGN_SITE.search(text or ""):
        found.append("pickup outside Germany")
    if DOOR_DELIVERY.search(text or ""):
        found.append("delivery at destination")
    if INSURANCE.search(text or ""):
        found.append("insurance")
    return found
