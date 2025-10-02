@pytest.mark.asyncio
async def test_concurrent_requests():
    async def simulate_user(user_id):
        for i in range(10):
            # Имитация запроса
            await bot_logic.process_message(user_id, f"Сообщение {i}")

    # 50 пользователей, по 10 сообщений = 500 запросов
    tasks = [simulate_user(i) for i in range(50)]
    start_time = time.time()
    await asyncio.gather(*tasks)
    end_time = time.time()

    # Должно выполниться за разумное время
    assert end_time - start_time < 30.0