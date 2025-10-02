import re

def sanitize_for_model(text: str, max_length: int = 2000) -> str:
    """
    Санитизация текста перед отправкой в GPT.
    - убираем лишние пробелы
    - обрезаем длину (чтобы не перегружать токены)
    """
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def sanitize_for_display(text: str, max_length: int = 500) -> str:
    """
    Санитизация текста, который будет показан пользователю.
    - убираем управляющие символы
    - убираем лишние пробелы
    - обрезаем длину
    """
    if not text:
        return ""
    # убираем управляющие символы (emoji/спецсимволы не трогаем)
    text = "".join(ch for ch in text if ch.isprintable())
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]
