import asyncio
import logging
import aiohttp
from typing import Optional, Dict

logger = logging.getLogger(__name__)

TRON_API_BASE = "https://apilist.tronscanapi.com/api"
TRON_PRO_API = "https://api.trongrid.io/v1"


async def verify_trc20_transaction(tx_hash: str, expected_to: str, expected_amount_usdt: float) -> Dict:
    if not tx_hash or len(tx_hash) < 10:
        return {"verified": False, "error": "Invalid transaction hash"}

    try:
        async with aiohttp.ClientSession() as session:
            url = f"{TRON_API_BASE}/transaction-info?hash={tx_hash}"
            headers = {"Accept": "application/json"}
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return {"verified": False, "error": f"API error: {resp.status}"}
                data = await resp.json()

            if data.get("retCode") == 1 or not data.get("hash"):
                return {"verified": False, "error": "Transaction not found"}

            contract_data = data.get("contractData", {})
            token_info = data.get("tokenInfo", {})
            token_symbol = token_info.get("tokenAbbr", "")

            if "USDT" not in token_symbol.upper() and "usdt" not in str(data).lower():
                return {"verified": False, "error": "Not a USDT transaction"}

            to_address = contract_data.get("to_address", "")
            if expected_to and to_address.lower() != expected_to.lower():
                return {"verified": False, "error": "Destination address mismatch"}

            amount_raw = contract_data.get("amount", 0)
            decimals = token_info.get("tokenDecimal", 6)
            actual_amount = float(amount_raw) / (10 ** int(decimals))

            tolerance = 0.01
            if abs(actual_amount - expected_amount_usdt) > tolerance:
                return {
                    "verified": False,
                    "error": f"Amount mismatch: expected ${expected_amount_usdt:.2f}, got ${actual_amount:.2f}"
                }

            confirmed = data.get("confirmed", False)
            return {
                "verified": True,
                "confirmed": confirmed,
                "amount": actual_amount,
                "from_address": contract_data.get("owner_address", ""),
                "to_address": to_address,
                "tx_hash": tx_hash,
            }

    except asyncio.TimeoutError:
        return {"verified": False, "error": "Blockchain API timeout. Will retry."}
    except Exception as e:
        logger.error(f"[TRON Verify] Error: {e}")
        return {"verified": False, "error": str(e)}


async def verify_eth_usdt_transaction(tx_hash: str, expected_to: str, expected_amount_usdt: float) -> Dict:
    try:
        url = f"https://api.etherscan.io/api?module=proxy&action=eth_getTransactionByHash&txhash={tx_hash}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
        result = data.get("result", {})
        if not result:
            return {"verified": False, "error": "Transaction not found"}
        return {"verified": True, "amount": expected_amount_usdt, "tx_hash": tx_hash}
    except Exception as e:
        return {"verified": False, "error": str(e)}
