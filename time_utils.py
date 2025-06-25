from datetime import datetime, timezone
import pytz

# def get_bali_and_msk_time_list():
#     """Вернуть список из 8 вариантов времени: 
#     UTC (дата+время), UTC (только время), Бали (дата+время), Бали (только время), МСК (дата+время), МСК (только время), Бали (дата+время), МСК (дата+время)
#     """
#     now_utc = datetime.utcnow()
#     bali_tz = pytz.timezone("Asia/Makassar")
#     msk_tz = pytz.timezone("Europe/Moscow")
#     now_utc_long = now_utc.strftime("%d.%m.%Y %H:%M:%S")
#     now_utc_short = now_utc.strftime("%H:%M")
#     now_bali = now_utc.astimezone(bali_tz).strftime("%d.%m.%Y %H:%M:%S")
#     now_bali_long = now_utc.astimezone(bali_tz).strftime("%d.%m.%Y %H:%M")
#     now_bali_short = now_utc.astimezone(bali_tz).strftime("%H:%M")
#     now_msk = now_utc.astimezone(msk_tz).strftime("%d.%m.%Y %H:%M:%S")
#     now_msk_short = now_utc.astimezone(msk_tz).strftime("%H:%M")
#     now_msk_long = now_utc.astimezone(msk_tz).strftime("%d.%m.%Y %H:%M")
#     return [
#         now_utc_long,      # 0: UTC дата+время
#         now_utc_short,     # 1: UTC только время
#         now_bali,          # 2: Бали дата+время часы:минуты:секунды
#         now_bali_short,    # 3: Бали только время часы:минуты
#         now_msk,           # 4: МСК дата+времячасы:минуты:секунды
#         now_msk_short,     # 5: МСК только время часы:минуты
#         now_bali_long,     # 6: Бали дата+время часы:минуты
#         now_msk_long,      # 7: МСК дата+время часы:минуты
#     ]