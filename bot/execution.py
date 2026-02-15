from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.config import Settings

try:
    from py_clob_client.client import ClobClient
except Exception:  # pragma: no cover
    ClobClient = None


@dataclass(slots=True)
class ExecutionResult:
    order_id: str
    status: str
    price: float
    size: float


class Executor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mode = settings.mode.value
        self.client = None
        if self.mode == "live":
            self.client = self._build_client(settings)

    def _build_client(self, settings: Settings):
        if ClobClient is None:
            raise RuntimeError("py-clob-client not installed/importable")
        if not settings.poly_private_key:
            raise RuntimeError("POLY_PRIVATE_KEY required in live mode")
        client = ClobClient(host=settings.poly_clob_host, key=settings.poly_private_key, chain_id=settings.poly_chain_id)

        if settings.poly_api_key and settings.poly_api_secret and settings.poly_api_passphrase:
            creds = {
                "key": settings.poly_api_key,
                "secret": settings.poly_api_secret,
                "passphrase": settings.poly_api_passphrase,
            }
            if hasattr(client, "set_api_creds"):
                client.set_api_creds(creds)
        else:
            if hasattr(client, "derive_api_key") and hasattr(client, "set_api_creds"):
                creds = client.derive_api_key()
                client.set_api_creds(creds)
            elif hasattr(client, "create_or_derive_api_creds"):
                creds = client.create_or_derive_api_creds()
                if hasattr(client, "set_api_creds"):
                    client.set_api_creds(creds)
        return client

    async def place_limit(self, token_id: str, side: str, price: float, size: float, best_ask: float | None = None) -> ExecutionResult:
        order_id = str(uuid.uuid4())
        if self.mode == "paper":
            status = "filled" if (side == "buy" and best_ask is not None and price >= best_ask) else "open"
            return ExecutionResult(order_id=order_id, status=status, price=price, size=size)

        if self.client is None:
            raise RuntimeError("live client missing")

        order_args = {
            "token_id": token_id,
            "price": price,
            "size": size,
            "side": side,
        }
        if hasattr(self.client, "create_order") and hasattr(self.client, "post_order"):
            signed = self.client.create_order(order_args)
            resp = self.client.post_order(signed)
            oid = str(resp.get("orderID") or resp.get("id") or order_id)
            return ExecutionResult(order_id=oid, status="submitted", price=price, size=size)

        raise RuntimeError("Unsupported py-clob-client version: missing create_order/post_order")

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
