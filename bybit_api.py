import aiohttp

BYBIT_TICKER_URL = "https://api.bybit.com/v5/market/tickers?category=spot&symbol=USDTIDR"

async def get_idr_usdt_rate() -> float:
    """
    Получить актуальный курс продажи IDR за USDT с Bybit (сколько USDT за 1 IDR)
    Возвращает float (курс) или выбрасывает исключение при ошибке.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(BYBIT_TICKER_URL, timeout=10) as resp:
            if resp.status != 200:
                raise Exception(f"Bybit API error: HTTP {resp.status}")
            data = await resp.json()
            # Ожидаем структуру: {'result': {'list': [{'symbol': 'USDTIDR', ...}]}}
            try:
                ticker = data['result']['list'][0]
                # Цена последней сделки (lastPrice) — сколько IDR за 1 USDT
                last_price = float(ticker['lastPrice'])
                # Нам нужен обратный курс: сколько USDT за 1 IDR
                rate = 1 / last_price if last_price else 0.0
                return rate
            except Exception as e:
                raise Exception(f"Bybit API parse error: {e}") 