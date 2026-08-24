"""
tools.py — LangChain @tool functions for customer support.

Each tool:
  - Takes explicit parameters (no free-form text parsing)
  - Returns a consistent JSON shape: { success, data, error }
  - Queries MongoDB via the db module
  - Is independently testable
"""

import uuid
from datetime import datetime, timezone
from langchain_core.tools import tool

from .db import get_db


# ── Tool 1: Get Order Status ─────────────────────────────────────────────────

@tool
async def get_order_status(order_id: str) -> dict:
    """Look up the current status of a customer order by its order ID.
    Use this when the customer asks about their order status, where their order is, or what's happening with their order.
    The order_id should be in the format ORD-XXXX (e.g., ORD-1001)."""
    try:
        db = await get_db()
        order = await db.orders.find_one(
            {"order_id": order_id.upper()},
            {"_id": 0}
        )
        if not order:
            return {"success": False, "data": None, "error": f"No order found with ID {order_id}"}
        return {"success": True, "data": order, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


# ── Tool 2: Cancel Order ─────────────────────────────────────────────────────

@tool
async def cancel_order(order_id: str, confirmed: bool) -> dict:
    """Cancel a customer order. IMPORTANT: You must FIRST ask the user to confirm
    the cancellation before calling this tool. Only set confirmed=true after the
    user explicitly says yes. If the user hasn't confirmed yet, set confirmed=false.
    The order_id should be in the format ORD-XXXX (e.g., ORD-1001)."""
    try:
        # Enforce confirmation gate
        if not confirmed:
            return {
                "success": False,
                "data": None,
                "error": "User confirmation required. Please ask the user to confirm the cancellation first."
            }

        db = await get_db()
        order = await db.orders.find_one({"order_id": order_id.upper()})
        if not order:
            return {"success": False, "data": None, "error": f"No order found with ID {order_id}"}

        if order["status"] == "cancelled":
            return {"success": False, "data": None, "error": f"Order {order_id} is already cancelled."}

        if order["status"] == "delivered":
            return {"success": False, "data": None, "error": f"Order {order_id} has already been delivered and cannot be cancelled."}

        await db.orders.update_one(
            {"order_id": order_id.upper()},
            {"$set": {"status": "cancelled", "eta": None}}
        )
        return {
            "success": True,
            "data": {"order_id": order_id.upper(), "new_status": "cancelled"},
            "error": None
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


# ── Tool 3: Get Delivery Estimate ────────────────────────────────────────────

@tool
async def get_delivery_estimate(order_id: str) -> dict:
    """Get the estimated delivery date for a customer order.
    Use this when the customer asks when their order will arrive or delivery timeline.
    The order_id should be in the format ORD-XXXX (e.g., ORD-1001)."""
    try:
        db = await get_db()
        order = await db.orders.find_one(
            {"order_id": order_id.upper()},
            {"_id": 0, "order_id": 1, "status": 1, "eta": 1, "items": 1}
        )
        if not order:
            return {"success": False, "data": None, "error": f"No order found with ID {order_id}"}

        if order["status"] == "delivered":
            return {"success": True, "data": {"order_id": order_id.upper(), "status": "delivered", "message": "This order has already been delivered."}, "error": None}

        if order["status"] == "cancelled":
            return {"success": True, "data": {"order_id": order_id.upper(), "status": "cancelled", "message": "This order was cancelled."}, "error": None}

        return {
            "success": True,
            "data": {
                "order_id": order_id.upper(),
                "status": order["status"],
                "eta": order.get("eta"),
                "items": order.get("items", []),
            },
            "error": None
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


# ── Tool 4: Create Support Ticket ────────────────────────────────────────────

@tool
async def create_support_ticket(issue: str, order_id: str = "") -> dict:
    """Create a support ticket for issues that cannot be resolved directly.
    Use this when the customer has a problem that needs human follow-up,
    or when they want to escalate an issue. The order_id is optional."""
    try:
        db = await get_db()
        ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        ticket = {
            "ticket_id": ticket_id,
            "order_id": order_id.upper() if order_id else None,
            "issue": issue,
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.support_tickets.insert_one(ticket)
        # Return without _id (not JSON-serializable)
        ticket.pop("_id", None)
        return {"success": True, "data": ticket, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


# ── All tools list (for agent binding) ───────────────────────────────────────

ALL_TOOLS = [get_order_status, cancel_order, get_delivery_estimate, create_support_ticket]
