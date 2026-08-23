"""
db.py — MongoDB connection + seed data for the voice agent.

Collections:
  - orders: Mock customer orders (seeded on startup)
  - support_tickets: Created by the create_support_ticket tool
  - conversation_logs: Structured session logs
"""

from motor.motor_asyncio import AsyncIOMotorClient
from ..config.env import env

# ── Singleton client + database ──────────────────────────────────────────────

_client: AsyncIOMotorClient | None = None
_db = None


async def get_db():
    """Return the MongoDB database instance. Call connect_db() first."""
    global _db
    if _db is None:
        await connect_db()
    return _db


async def connect_db():
    """Initialize the MongoDB connection and seed mock data."""
    global _client, _db
    mongo_uri = getattr(env, 'MONGODB_URI', 'mongodb://localhost:27017')
    _client = AsyncIOMotorClient(mongo_uri)
    _db = _client['voice_agent']
    await _seed_orders()
    print('[startup] MongoDB connected + orders seeded')


async def close_db():
    """Close the MongoDB connection."""
    global _client
    if _client:
        _client.close()
        _client = None


# ── Seed data ────────────────────────────────────────────────────────────────

MOCK_ORDERS = [
    {"order_id": "ORD-1001", "customer_name": "Gaurav Palve",  "status": "shipped",    "eta": "2026-08-25", "items": ["Wireless Earbuds", "Phone Case"]},
    {"order_id": "ORD-1002", "customer_name": "Priya Sharma",  "status": "processing", "eta": "2026-08-28", "items": ["Laptop Stand", "USB-C Hub"]},
    {"order_id": "ORD-1003", "customer_name": "Rahul Mehta",   "status": "delivered",  "eta": "2026-08-20", "items": ["Mechanical Keyboard"]},
    {"order_id": "ORD-1004", "customer_name": "Ananya Desai",  "status": "shipped",    "eta": "2026-08-26", "items": ["Running Shoes", "Water Bottle", "Gym Bag"]},
    {"order_id": "ORD-1005", "customer_name": "Vikram Singh",  "status": "processing", "eta": "2026-08-30", "items": ["Monitor 27-inch"]},
    {"order_id": "ORD-1006", "customer_name": "Neha Gupta",    "status": "cancelled",  "eta": None,         "items": ["Yoga Mat"]},
    {"order_id": "ORD-1007", "customer_name": "Arjun Patel",   "status": "shipped",    "eta": "2026-08-24", "items": ["Bluetooth Speaker", "Charging Cable"]},
    {"order_id": "ORD-1008", "customer_name": "Kavya Reddy",   "status": "delivered",  "eta": "2026-08-18", "items": ["Book: Deep Learning", "Notebook"]},
    {"order_id": "ORD-1009", "customer_name": "Siddharth Jain", "status": "processing", "eta": "2026-09-01", "items": ["Smartwatch", "Watch Band"]},
    {"order_id": "ORD-1010", "customer_name": "Meera Nair",    "status": "shipped",    "eta": "2026-08-27", "items": ["Desk Lamp", "Mousepad"]},
]


async def _seed_orders():
    """Insert mock orders if the collection is empty."""
    db = await get_db()
    count = await db.orders.count_documents({})
    if count == 0:
        await db.orders.insert_many(MOCK_ORDERS)
        print(f'[seed] Inserted {len(MOCK_ORDERS)} mock orders')
    else:
        print(f'[seed] Orders collection already has {count} documents')
