import aiohttp
import json

BYBIT_P2P_API = "https://api2.bybit.com/fiat/otc/item/online"

async def get_p2p_idr_usdt_avg_rate() -> float:
    """
    Получить средний курс P2P Bybit (цены с 3 по 10 ордер на покупку USDT за IDR).
    Возвращает float (курс) или выбрасывает исключение при ошибке.
    """
    payload = {
        "currencyId": "IDR",
        "tokenId": "USDT",
        "side": "1",
        "size": "10",
        "page": "1"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(BYBIT_P2P_API, data=json.dumps(payload)) as resp:
            data = await resp.json()
            result = data.get("result")
            items = result.get("items") if result else None
            if resp.status != 200:
                raise Exception(f"Bybit P2P API error: HTTP {resp.status}")
            ret_code = data["ret_code"] if "ret_code" in data else data.get("retCode")
            ret_msg = data.get("ret_msg") or data.get("retMsg")
            if ret_code == 0 and items:
                prices = [float(item.get("price", 0)) for item in items if item.get("price")]
                if len(prices) >= 10:
                    avg = sum(prices[2:10]) / 8  # среднее с 3 по 10
                    return avg
                elif prices:
                    avg = sum(prices) / len(prices)
                    return avg
                else:
                    raise Exception("Bybit P2P: нет цен в офферах")
            else:
                raise Exception(f"Bybit P2P: ret_code={ret_code}, ret_msg={ret_msg}, офферов={len(items) if items else 0}") 