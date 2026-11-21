import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.agents.classifier import RuleClassifier
from core.agents.directory import load_directory
from core.agents.mailbox import parse_mail
from core.config import load_settings
from core.contracts import Attachment, Mail, MailKind

FIXTURES = Path(__file__).parent / "fixtures"
NO_THREADS: frozenset[int] = frozenset()


@pytest.fixture
def classifier(tmp_path: Path) -> RuleClassifier:
    settings = load_settings(tmp_path, {"FIVEU_API_KEY": "test-key"})
    return RuleClassifier(settings, load_directory(FIXTURES / "kit"))


def fixture_mail(name: str) -> Mail:
    return parse_mail(json.loads((FIXTURES / "mail" / name).read_text(encoding="utf-8")))


def make_mail(sender: str, subject: str = "Hello", body: str = "", **extra: object) -> Mail:
    fields: dict[str, object] = {
        "id": 50,
        "sender": sender,
        "to": "wrathofcode@hackloop.mail",
        "subject": subject,
        "body": body,
        "in_reply_to": None,
        "references": (),
        "received_at": datetime(2026, 11, 21, 14, 0, tzinfo=UTC),
    }
    return Mail.model_validate(fields | extra)


@pytest.mark.parametrize(
    ("sender", "kind"),
    [
        ("wrathofcode@hackloop.mail", MailKind.OWN),
        ("ratedesk@hackloop.mail", MailKind.PORTAL_REPLY),
        ("tracking@hackloop.mail", MailKind.TRACKING),
        ("taunusfracht@hackloop.mail", MailKind.TRUCKER_BID),
    ],
)
def test_sender_rules(classifier: RuleClassifier, sender: str, kind: MailKind) -> None:
    assert classifier.classify(make_mail(sender), NO_THREADS).kind == kind


def test_airline_bid(classifier: RuleClassifier) -> None:
    result = classifier.classify(fixture_mail("carrier_bid.json"), NO_THREADS)
    assert result.kind == MailKind.CARRIER_BID
    assert result.reason


def test_booking_confirmation(classifier: RuleClassifier) -> None:
    mail = make_mail("gannet-airways@hackloop.mail", "Booking BK-1234 confirmed")
    assert classifier.classify(mail, NO_THREADS).kind == MailKind.BOOKING_CONFIRMATION


def test_tariff_by_keyword_or_attachment(classifier: RuleClassifier) -> None:
    by_word = make_mail("gannet-airways@hackloop.mail", "New rate sheet", "valid from Monday")
    with_file = make_mail(
        "gannet-airways@hackloop.mail", attachments=(Attachment(id=1, filename="rates.csv"),)
    )
    assert classifier.classify(by_word, NO_THREADS).kind == MailKind.TARIFF
    assert classifier.classify(with_file, NO_THREADS).kind == MailKind.TARIFF


def test_follow_up_in_known_thread(classifier: RuleClassifier) -> None:
    mail = make_mail("buyer@example.com", "Re: quote", "Any news?", references=(7,))
    assert classifier.classify(mail, frozenset({7})).kind == MailKind.FOLLOW_UP


def test_new_rfq(classifier: RuleClassifier) -> None:
    assert classifier.classify(fixture_mail("rfq_english.json"), NO_THREADS).kind == MailKind.RFQ
    german = fixture_mail("rfq_german_html.json")
    assert classifier.classify(german, NO_THREADS).kind == MailKind.RFQ


def test_newsletter_is_other(classifier: RuleClassifier) -> None:
    assert classifier.classify(fixture_mail("newsletter.json"), NO_THREADS).kind == MailKind.OTHER
