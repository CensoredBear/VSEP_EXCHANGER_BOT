import asyncio
from bybit_p2p import get_p2p_idr_usdt_avg_rate

async def main():
    try:
        avg = await get_p2p_idr_usdt_avg_rate()
        print(f"Средний курс P2P Bybit (3-10 заявки): {avg}")
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 