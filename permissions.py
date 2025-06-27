from db import db

async def is_admin_or_superadmin(user_id: int) -> bool:
    rank = await db.get_user_rank(user_id)
    return rank in ("admin", "админ", "superadmin", "суперадмин")

async def is_operator_or_admin(user_id: int) -> bool:
    rank = await db.get_user_rank(user_id)
    return rank in ("operator", "оператор", "admin", "админ", "superadmin", "суперадмин")

async def is_superadmin(user_id: int) -> bool:
    rank = await db.get_user_rank(user_id)
    return rank in ("superadmin", "суперадмин") 