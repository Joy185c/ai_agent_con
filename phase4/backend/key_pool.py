"""
Key pool manager.

Core idea (from the blueprint): don't pin a key to a user. On every request,
look across all active keys for the given category (text/vision) and pick
whichever one has the most headroom left against its own RPM/RPD limits.
If a call comes back rate-limited, put that key in cooldown and retry with
the next-best key — the caller never sees the failure.

Usage counters live in Redis when available (so multiple backend workers
share the same view), and fall back to an in-process dict if Redis isn't
running — handy for local dev without extra infrastructure, though counts
won't be shared across multiple processes in that mode.
"""

import os
import time
from datetime import datetime, timezone
from typing import Optional

import db
import providers
import stream_filter

REDIS_URL = os.environ.get("REDIS_URL", "")

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None


class UsageStore:
    """Abstract interface — Redis or in-memory, callers don't care which."""

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        raise NotImplementedError

    async def get(self, key: str) -> int:
        raise NotImplementedError

    async def set_cooldown(self, key_id: int, seconds: int):
        raise NotImplementedError

    async def is_cooldown(self, key_id: int) -> bool:
        raise NotImplementedError


class RedisUsageStore(UsageStore):
    def __init__(self, url: str):
        self._client = aioredis.from_url(url, decode_responses=True)

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        val = await self._client.incr(key)
        if val == 1:
            await self._client.expire(key, ttl_seconds)
        return val

    async def get(self, key: str) -> int:
        val = await self._client.get(key)
        return int(val) if val else 0

    async def set_cooldown(self, key_id: int, seconds: int):
        await self._client.setex(f"cooldown:{key_id}", seconds, "1")

    async def is_cooldown(self, key_id: int) -> bool:
        return bool(await self._client.exists(f"cooldown:{key_id}"))


class MemoryUsageStore(UsageStore):
    """Fallback for local dev when no Redis is running. Single-process only."""

    def __init__(self):
        self._counters: dict[str, tuple[int, float]] = {}  # key -> (count, expires_at)
        self._cooldowns: dict[int, float] = {}  # key_id -> expires_at

    def _cleanup(self, key: str):
        if key in self._counters and self._counters[key][1] < time.time():
            del self._counters[key]

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        self._cleanup(key)
        count, expires = self._counters.get(key, (0, time.time() + ttl_seconds))
        count += 1
        self._counters[key] = (count, expires)
        return count

    async def get(self, key: str) -> int:
        self._cleanup(key)
        return self._counters.get(key, (0, 0))[0]

    async def set_cooldown(self, key_id: int, seconds: int):
        self._cooldowns[key_id] = time.time() + seconds

    async def is_cooldown(self, key_id: int) -> bool:
        expires = self._cooldowns.get(key_id)
        return bool(expires and expires > time.time())


def build_usage_store() -> UsageStore:
    if REDIS_URL and aioredis is not None:
        try:
            return RedisUsageStore(REDIS_URL)
        except Exception:
            pass
    return MemoryUsageStore()


usage_store = build_usage_store()


class NoAvailableKeyError(Exception):
    pass


def _rpm_bucket(key_id: int) -> str:
    minute = int(time.time() // 60)
    return f"rpm:{key_id}:{minute}"


def _rpd_bucket(key_id: int) -> str:
    # Fixed UTC-calendar-day window, not a rolling 24h window — most
    # providers reset this way, not exactly 24h after first use.
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"rpd:{key_id}:{day}"


async def _headroom_ratio(key_record: dict) -> float:
    """Fraction of capacity still free (1.0 = untouched, 0.0 = exhausted)."""
    rpm_used = await usage_store.get(_rpm_bucket(key_record["id"]))
    rpd_used = await usage_store.get(_rpd_bucket(key_record["id"]))
    rpm_ratio = 1 - (rpm_used / key_record["rpm_limit"]) if key_record["rpm_limit"] else 0
    rpd_ratio = 1 - (rpd_used / key_record["rpd_limit"]) if key_record["rpd_limit"] else 0
    return min(rpm_ratio, rpd_ratio)


async def select_best_key(category: str = "text", exclude_ids: Optional[set] = None,
                           candidates: Optional[list] = None) -> dict:
    """Pick the active key with the most headroom that isn't in cooldown or excluded.

    If `candidates` is given, choose among that explicit list instead of the
    shared admin pool — used for per-user BYOK keys.
    """
    exclude_ids = exclude_ids or set()
    pool = candidates if candidates is not None else db.active_keys(category)
    pool = [k for k in pool if k["id"] not in exclude_ids]

    scored = []
    for key_record in pool:
        if await usage_store.is_cooldown(key_record["id"]):
            continue
        ratio = await _headroom_ratio(key_record)
        if ratio <= 0:
            continue
        scored.append((ratio, key_record))

    if not scored:
        raise NoAvailableKeyError(f"No available '{category}' key in the pool right now.")

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1]


async def record_success(key_record: dict, category: str = "text"):
    await usage_store.incr_with_ttl(_rpm_bucket(key_record["id"]), 65)
    await usage_store.incr_with_ttl(_rpd_bucket(key_record["id"]), 26 * 3600)
    try:
        db.increment_request_stat(key_record.get("provider"), category, "success")
    except Exception:
        pass  # analytics failure must never break the response


async def record_rate_limited(key_record: dict):
    # Cool down for a minute — usually enough for an RPM limit to clear.
    # If RPD is what's actually exhausted, it'll just get skipped again
    # on the next attempt since its headroom ratio will still read 0.
    await usage_store.set_cooldown(key_record["id"], 60)


async def call_llm_with_fallback(messages: list, category: str = "text", max_attempts: int = 5,
                                  candidates: Optional[list] = None):
    """
    Try the best available key; on rate-limit or invalid-key errors, retry
    with the next-best key. Yields text chunks from whichever key succeeds.
    Raises NoAvailableKeyError if the whole pool is exhausted.

    Pass `candidates` to restrict selection to a specific list (e.g. a
    single user's own BYOK keys) instead of the shared admin pool.
    """
    tried_ids: set = set()
    last_tried_provider = None

    for attempt in range(max_attempts):
        key_record = await select_best_key(category=category, exclude_ids=tried_ids, candidates=candidates)
        tried_ids.add(key_record["id"])
        
        # If this is a fallback attempt, yield an event about the switch
        if attempt > 0 and last_tried_provider and last_tried_provider != key_record["provider"]:
            yield {"type": "system_msg", "message": f"Switched to {key_record['provider'].capitalize()} due to {last_tried_provider.capitalize()} error/rate-limit"}
            
        last_tried_provider = key_record["provider"]
        
        stream_chat, _ = providers.get_adapter(key_record["provider"])

        try:
            got_any_output = False
            filtered_stream = stream_filter.filter_think_tags(
                stream_chat(key_record["api_key"], key_record["model"], messages)
            )
            async for chunk in filtered_stream:
                got_any_output = True
                if chunk:
                    yield chunk
            if got_any_output:
                await record_success(key_record, category)
                return
        except providers.RateLimitError:
            await record_rate_limited(key_record)
            continue
        except providers.InvalidKeyError:
            if key_record.get("source") == "user":
                db.mark_user_key_invalid(key_record["orig_id"])
            else:
                db.record_check_result(key_record["orig_id"], "invalid")
            continue
        except providers.ProviderError:
            # Some other provider-side error — skip this key, try the next.
            continue

    raise NoAvailableKeyError("All keys in the pool failed or are exhausted right now.")


async def test_key_validity(key_id: int) -> str:
    key_record = db.get_key(key_id)
    if not key_record:
        raise ValueError(f"No key with id {key_id}")
    _, test_validity = providers.get_adapter(key_record["provider"])
    result = await test_validity(key_record["api_key"], key_record["model"])
    db.record_check_result(key_id, result)
    return result


async def test_all_keys() -> list[dict]:
    results = []
    for key_record in db.list_keys():
        try:
            result = await test_key_validity(key_record["id"])
        except Exception as exc:  # noqa: BLE001 — surface any adapter error as invalid
            result = "invalid"
            db.record_check_result(key_record["id"], result)
        results.append({"id": key_record["id"], "provider": key_record["provider"], "result": result})
    return results


async def get_pool_usage_snapshot() -> list[dict]:
    """Live RPM/RPD snapshot for every active key in the pool (text + vision)."""
    results = []
    seen_orig_ids: set = set()
    for cat in ("text", "vision"):
        for kr in db.active_keys(cat):
            orig_id = kr["orig_id"]
            if orig_id in seen_orig_ids:
                continue
            seen_orig_ids.add(orig_id)
            rpm_used = await usage_store.get(_rpm_bucket(kr["id"]))
            rpd_used = await usage_store.get(_rpd_bucket(kr["id"]))
            in_cd    = await usage_store.is_cooldown(kr["id"])
            rpm_pct  = round(min(rpm_used / kr["rpm_limit"] * 100, 100), 1) if kr["rpm_limit"] else 0.0
            rpd_pct  = round(min(rpd_used / kr["rpd_limit"] * 100, 100), 1) if kr["rpd_limit"] else 0.0
            results.append({
                "key_id":    orig_id,
                "provider":  kr["provider"],
                "category":  kr["category"],
                "rpm_used":  rpm_used,
                "rpm_limit": kr["rpm_limit"],
                "rpm_pct":   rpm_pct,
                "rpd_used":  rpd_used,
                "rpd_limit": kr["rpd_limit"],
                "rpd_pct":   rpd_pct,
                "in_cooldown": in_cd,
            })
    return results
