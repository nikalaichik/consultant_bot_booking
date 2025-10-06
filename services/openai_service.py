from openai import AsyncOpenAI
from typing import Dict
from config import Config
import logging
import tenacity
import re

logger = logging.getLogger(__name__)

def strip_markdown(text: str) -> str:
        """Убирает markdown разметку"""
        text = text.replace('**', '')
        text = text.replace('*', '')
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
        return text

class OpenAIService:
    def __init__(self, api_key: str, model: str, model_mini: str, config: Config):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.model_mini = model_mini
        self.config = config

    def _get_system_prompt(self, intent: str, user_profile: Dict = None) -> str:
        """Системный промпт в зависимости от намерения"""

        base_prompt = self.config.SYSTEM_PROMPT_BASE

        intent_prompts = {
            "emergency": self.config.SYSTEM_PROMPT_EMERGENCY,
            "consultation": self.config.SYSTEM_PROMPT_CONSULTATION,
            "booking": self.config.SYSTEM_PROMPT_BOOKING,
            "pricing": self.config.SYSTEM_PROMPT_PRICING,
            "aftercare": self.config.SYSTEM_PROMPT_AFTERCARE,
        }
        if intent in intent_prompts:
            base_prompt += "\n\n" + intent_prompts[intent]

        # Добавляем профиль пользователя
        if user_profile:
            profile_info = f"""
ПРОФИЛЬ КЛИЕНТА:
Тип кожи: {user_profile.get('skin_type', 'не указан')}
Возраст: {user_profile.get('age_group', 'не указан')}
Предыдущие процедуры: {user_profile.get('previous_procedures', 'нет данных')}
"""
            base_prompt += profile_info

        return base_prompt

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
        stop=tenacity.stop_after_attempt(3),
        retry=tenacity.retry_if_exception_type(Exception)
    )

    async def generate_response(
        self,
        user_message: str,
        context: str,
        intent: str = "general",
        user_profile: Dict = None,
        use_mini: bool = False
    ) -> str:
        """Генерирует ответ на основе контекста с retry логикой"""

        try:
            model = self.model_mini if use_mini else self.model
            system_prompt = self._get_system_prompt(intent, user_profile)

            # Определяем качество контекста для более точных инструкций
            context_quality = self._evaluate_context_quality(context, user_message)
            # Добавляем профиль пользователя в промпт
            if user_profile:
                profile_info = f"""
                ПРОФИЛЬ КЛИЕНТА:
                Тип кожи: {user_profile.get('skin_type', 'не указан')}
                Возраст: {user_profile.get('age_group', 'не указан')}
                Предыдущие процедуры: {user_profile.get('previous_procedures', 'нет данных')}
                """
                system_prompt += profile_info

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""КАЧЕСТВО НАЙДЕННОЙ ИНФОРМАЦИИ: {context_quality}
                 КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ:
{context if context.strip() else "Релевантная информация в базе знаний не найдена."}

ВОПРОС КЛИЕНТА: {user_message}
ВАЖНО: Если контекст пустой или нерелевантный, используй контекстные ответы для данного намерения ({intent}) из системного промпта."""}
            ]

            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=800 if intent == "emergency" else 600,
                temperature=0.7,
                presence_penalty=0.1
            )
            if not response or not response.choices:
                logger.warning("OpenAI вернул пустой ответ")
                return self._get_fallback_response(intent, user_message)

            content = response.choices[0].message.content

            clean_content = strip_markdown(content)
            if not content or not content.strip():
                logger.warning("OpenAI вернул пустой контент")
                return self._get_fallback_response(intent, user_message)

            return clean_content

        except Exception as e:
            logger.exception(f"Ошибка генерации ответа OpenAI: {e}")
            return self._get_fallback_response(intent, user_message)
    def _evaluate_context_quality(self, context: str, user_message: str) -> str:
        """Оценивает качество найденного контекста"""
        if not context or context.strip() == "":
            return "ОТСУТСТВУЕТ"

        # Проверяем на стандартное сообщение об отсутствии информации
        if "не найдено релевантной информации" in context:
            return "ОТСУТСТВУЕТ"

        context_words = set(context.lower().split())
        message_words = set(user_message.lower().split())

        # Простая оценка пересечения ключевых слов
        overlap = len(context_words.intersection(message_words))

        if overlap >= 3:
            return "ВЫСОКОЕ"
        elif overlap >= 1:
            return "СРЕДНЕЕ"
        else:
            return "НИЗКОЕ"

    async def classify_intent(self, message: str) -> str:
        """Классифицирует намерение пользователя через GPT"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model_mini,
                messages=[
                    {
                        "role": "system",
                        "content": """Определи намерение клиента косметологической клиники.
                        Верни ТОЛЬКО одно слово:

                        emergency - экстренные ситуации, осложнения, аллергии, боль, воспаления
                        consultation - вопросы о процедурах, советы по уходу, рекомендации
                        booking - запись на прием, расписание, хочу записаться
                        pricing - вопросы о ценах, стоимости, сколько стоит
                        aftercare - уход после процедур, что можно/нельзя делать после
                        general - общие вопросы о клинике, контакты, режим работы"""
                    },
                    {"role": "user", "content": message}
                ],
                max_tokens=10,
                temperature=0.1
            )

            if not response or not response.choices:
                return "general"

            intent = response.choices[0].message.content.strip().lower()
            valid_intents = ["emergency", "consultation", "booking", "pricing", "aftercare", "general"]

            return intent if intent in valid_intents else "general"

        except Exception as e:
            logger.exception(f"Ошибка классификации намерения: {e}")
            return "general"

    def _get_fallback_response(self, intent: str, user_message: str = "") -> str:
        """Резервный ответ при ошибке API"""
        # Анализируем намерение из сообщения для более точного fallback
        message_lower = user_message.lower() if user_message else ""

        # Определяем, о чем спрашивает пользователь
        if any(word in message_lower for word in ["цена", "стоимость", "сколько"]):
            return f"""💰 Произошла техническая ошибка при получении информации о ценах.

📞 Актуальные цены уточняйте:
Телефон: {self.config.CLINIC_PHONE}
🕐 Режим работы: {self.config.WORKING_HOURS}

💡 Также можете записаться на бесплатную консультацию, где врач подберет процедуры и озвучит стоимость."""

        if any(word in message_lower for word in ["запись", "записаться", "время"]):
            return f"""📅 Произошла техническая ошибка системы записи.

📞 Для записи звоните напрямую:
Телефон: {self.config.CLINIC_PHONE}
💬 WhatsApp: {self.config.CLINIC_PHONE}

🕐 Режим работы: {self.config.WORKING_HOURS}
📍 Адрес: {self.config.CLINIC_ADDRESS}

Администратор подберет удобное время и подготовит к визиту."""

        if intent == "emergency":
            return f"""🚨 ТЕХНИЧЕСКИЙ СБОЙ, НО ВАША СИТУАЦИЯ ТРЕБУЕТ ВНИМАНИЯ!

📞 ОБРАЩАЙТЕСЬ НЕМЕДЛЕННО:
Клиника: {self.config.CLINIC_PHONE}
Скорая помощь: 103

⚠️ При экстренных проблемах после косметологических процедур - звоните в клинику или обращайтесь к врачу лично!

Не откладывайте при: болях, сильных покраснениях, отеках, аллергических реакциях."""

        if any(word in message_lower for word in ["процедур", "косметолог", "консультация"]):
            return f"""💬 Технический сбой при поиске информации о процедурах.

📞 Для детальной консультации:
Телефон: {self.config.CLINIC_PHONE}
💬 WhatsApp: {self.config.CLINIC_PHONE}

👩‍⚕️ Наши косметологи проконсультируют по:
• Подбору процедур для вашего типа кожи
• Составлению плана лечения
• Ответам на все вопросы о процедурах

🕐 Режим: {self.config.WORKING_HOURS}"""

        # Общий fallback
        return f"""😔 Произошла техническая ошибка при обработке вашего запроса.

📞 Для получения помощи:
Телефон: {self.config.CLINIC_PHONE}
💬 WhatsApp: {self.config.CLINIC_PHONE}
🕐 Режим работы: {self.config.WORKING_HOURS}

👩‍💼 Администратор или косметолог ответят на ваш вопрос лично.
Попробуйте переформулировать вопрос или обратитесь по телефону."""