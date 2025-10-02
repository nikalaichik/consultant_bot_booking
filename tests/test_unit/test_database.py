@pytest.mark.asyncio
async def test_database_crud():
    db = Database(":memory:")
    await db.init_tables()

    # Создание пользователя
    user = await db.get_or_create_user(12345, {
        "username": "testuser",
        "first_name": "Test",
        "last_name": "User"
    })
    assert user["telegram_id"] == 12345

    # Создание диалога
    conv_id = await db.save_conversation(
        12345, "Тест", "Ответ", "consultation", 1
    )
    assert conv_id is not None

    # Получение истории
    history = await db.get_user_conversations(12345)
    assert len(history) == 1