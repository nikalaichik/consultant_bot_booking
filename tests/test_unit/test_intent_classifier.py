import pytest
from services.bot_logic import IntentClassifier

def test_intent_accuracy():
    classifier = IntentClassifier()

    test_cases = [
        ("сколько стоит чистка", "pricing"),
        ("запишите меня на завтра", "booking"),
        ("болит место укола", "emergency"),
        ("что делать после процедуры", "aftercare"),
        ("какую процедуру выбрать", "consultation")
    ]

    for message, expected in test_cases:
        result = classifier.classify_by_keywords_and_patterns(message)
        assert result == expected, f"'{message}' -> ожидался {expected}, получен {result}"