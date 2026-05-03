"""
Production Redis Cluster cache backend for Django.

Uses redis-py's native RedisCluster client (redis >= 4.1, included in
the project's redis==5.x dependency). No extra packages needed beyond
django-redis for the cache framework abstractions.

Settings example::

    CACHES = {
        "default": {
            "BACKEND": "config.cluster_cache.RedisClusterCache",
            "KEY_PREFIX": "user_service",
            "TIMEOUT": 600,
            "OPTIONS": {
                "startup_nodes": [
                    {"host": "redis-node-0", "port": 6379},
                    {"host": "redis-node-1", "port": 6379},
                    {"host": "redis-node-2", "port": 6379},
                ],
                "password": "redis_cluster_secret",
                "socket_connect_timeout": 5,
                "socket_timeout": 5,
                "max_connections": 50,
                "read_from_replicas": True,
            },
        }
    }
"""

import logging
import pickle
from contextlib import suppress
from typing import Any

from django.core.cache.backends.base import BaseCache, DEFAULT_TIMEOUT
from redis.cluster import ClusterNode, RedisCluster
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def _encode(value: Any) -> bytes:
    return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)


def _decode(raw: bytes) -> Any:
    return pickle.loads(raw)  # noqa: S301 — only our own serialised values


class RedisClusterCache(BaseCache):
    """Django cache backend backed by a Redis Cluster (3 masters + 3 replicas)."""

    def __init__(self, server: str, params: dict) -> None:
        super().__init__(params)
        opts = params.get("OPTIONS", {})

        startup_nodes = [
            ClusterNode(str(n["host"]), int(n["port"]))
            for n in opts.get("startup_nodes", [])
        ]
        if not startup_nodes:
            raise RuntimeError(
                "RedisClusterCache requires OPTIONS['startup_nodes'] to be configured."
            )

        self._client: RedisCluster = RedisCluster(
            startup_nodes=startup_nodes,
            decode_responses=False,
            password=opts.get("password") or None,
            socket_connect_timeout=int(opts.get("socket_connect_timeout", 5)),
            socket_timeout=int(opts.get("socket_timeout", 5)),
            retry_on_timeout=True,
            skip_full_coverage_check=True,
            max_connections=int(opts.get("max_connections", 50)),
            read_from_replicas=bool(opts.get("read_from_replicas", True)),
        )

    # ── helpers ───────────────────────────────────────────────────────────

    def _k(self, key: str, version: int | None = None) -> str:
        return self.make_key(key, version=version)

    def _ttl(self, timeout: Any) -> int | None:
        t = self.get_backend_timeout(timeout)
        return None if t is None else max(0, int(t))

    # ── BaseCache interface ───────────────────────────────────────────────

    def get_backend_timeout(self, timeout=DEFAULT_TIMEOUT) -> int | None:
        if timeout == DEFAULT_TIMEOUT:
            timeout = self.default_timeout
        return None if timeout is None else max(0, int(timeout))

    def add(self, key: str, value: Any, timeout=DEFAULT_TIMEOUT, version=None) -> bool:
        try:
            return bool(
                self._client.set(
                    self._k(key, version),
                    _encode(value),
                    nx=True,
                    ex=self._ttl(timeout),
                )
            )
        except RedisError:
            logger.exception("Cache.add failed for key %r", key)
            return False

    def get(self, key: str, default=None, version=None) -> Any:
        try:
            raw = self._client.get(self._k(key, version))
        except RedisError:
            logger.exception("Cache.get failed for key %r", key)
            return default
        return default if raw is None else _decode(raw)

    def set(self, key: str, value: Any, timeout=DEFAULT_TIMEOUT, version=None) -> bool:
        ttl = self._ttl(timeout)
        if ttl == 0:
            return self.delete(key, version=version)
        try:
            kwargs = {"ex": ttl} if ttl is not None else {}
            return bool(
                self._client.set(self._k(key, version),
                                 _encode(value), **kwargs)
            )
        except RedisError:
            logger.exception("Cache.set failed for key %r", key)
            return False

    def delete(self, key: str, version=None) -> bool:
        try:
            return bool(self._client.delete(self._k(key, version)))
        except RedisError:
            logger.exception("Cache.delete failed for key %r", key)
            return False

    def get_many(self, keys: list[str], version=None) -> dict:
        if not keys:
            return {}
        built = {k: self._k(k, version) for k in keys}
        try:
            raws = self._client.mget(list(built.values()))
        except RedisError:
            logger.exception("Cache.get_many failed")
            return {}
        return {
            orig: _decode(raw)
            for orig, raw in zip(built.keys(), raws)
            if raw is not None
        }

    def set_many(self, mapping: dict, timeout=DEFAULT_TIMEOUT, version=None) -> list:
        ttl = self._ttl(timeout)
        if ttl == 0:
            self.delete_many(list(mapping.keys()), version=version)
            return []
        failed: list[str] = []
        try:
            pipe = self._client.pipeline()
            for key, value in mapping.items():
                k = self._k(key, version)
                if ttl is not None:
                    pipe.set(k, _encode(value), ex=ttl)
                else:
                    pipe.set(k, _encode(value))
            results = pipe.execute()
            for key, ok in zip(mapping.keys(), results):
                if not ok:
                    failed.append(key)
        except RedisError:
            logger.exception("Cache.set_many failed")
            failed = list(mapping.keys())
        return failed

    def delete_many(self, keys: list[str], version=None) -> None:
        if not keys:
            return
        built = [self._k(k, version) for k in keys]
        try:
            self._client.delete(*built)
        except RedisError:
            logger.exception("Cache.delete_many failed")

    def has_key(self, key: str, version=None) -> bool:
        try:
            return bool(self._client.exists(self._k(key, version)))
        except RedisError:
            logger.exception("Cache.has_key failed for key %r", key)
            return False

    def incr(self, key: str, delta: int = 1, version=None) -> int:
        try:
            return int(self._client.incr(self._k(key, version), delta))
        except RedisError as exc:
            raise ValueError(
                f"Cache key {key!r} not found or Redis error.") from exc

    def clear(self) -> bool:
        try:
            self._client.flushdb()
            return True
        except RedisError:
            logger.exception("Cache.clear failed")
            return False

    def close(self, **kwargs) -> None:
        with suppress(RedisError):
            self._client.close()
