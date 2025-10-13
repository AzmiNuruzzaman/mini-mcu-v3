# utils/cache_utils.py
import time

# Simple in-memory cache dictionary
_CACHE = {}

def set_cache(key: str, value, ttl: int = 300):
    """
    Set a value in cache with an optional TTL (seconds).
    """
    expire_at = time.time() + ttl if ttl else None
    _CACHE[key] = {"value": value, "expire_at": expire_at}

def get_cache(key: str):
    """
    Retrieve a value from cache. Returns None if expired or not found.
    """
    item = _CACHE.get(key)
    if not item:
        return None
    if item["expire_at"] and time.time() > item["expire_at"]:
        del _CACHE[key]
        return None
    return item["value"]

def delete_cache(key: str):
    """
    Remove a key from cache.
    """
    if key in _CACHE:
        del _CACHE[key]

def clear_cache():
    """
    Clear all cache.
    """
    _CACHE.clear()
