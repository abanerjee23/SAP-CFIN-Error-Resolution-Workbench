"""Durable fictional notification delivery; never sends email or external messages."""

from typing import Any

from cfin.gateway import ServiceGateway


async def process_notification(cloud: ServiceGateway) -> dict[str, Any]:
    claimed = await cloud.rpc("cfin_claim_notification", {})
    if not claimed.get("claimed"):
        return {"claimed": False, "simulated": True}
    notification = claimed["notification"]
    # Success describes the local simulation only. Delivery identity and late-result
    # fencing are enforced by the database; no external transport is instantiated.
    receipt = await cloud.rpc(
        "cfin_complete_notification",
        {
            "notification_id": notification["id"],
            "lease_token": notification["lease_token"],
            "succeeded": True,
        },
    )
    return {"claimed": True, "simulated": True, "notification_id": notification["id"], **receipt}
