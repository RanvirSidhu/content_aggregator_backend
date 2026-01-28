import redis
import json
from redis.exceptions import ConnectionError
from app.core.config import settings
from app.core.logging import get_logger

redis_client: redis.Redis = None
logger = get_logger(__name__)


def init_redis():
    global redis_client
    host = settings.REDIS_CACHE_HOST
    port = settings.REDIS_CACHE_PORT
    logger.info(f"Initialization of Redis")
    logger.debug(f"HOST:{host}, PORT:{port}")
    try:
        pool = redis.ConnectionPool(host=host, port=port, db=0)
        redis_client = redis.Redis(connection_pool=pool)
        logger.debug("fRedis Initialized: {redis_client}")
        redis_client.ping()
        logger.debug(f"Successfully connected to Redis at {host}:{port}")
    except ConnectionError as e:
        logger.error(f"Redis connection error: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


def get_redis_client():
    return redis_client


def redis_cache_get(key: str):
    logger.debug(f"Looking in redis cache for key: {key}")
    cached_value = redis_client.get(key)
    if cached_value:
        logger.debug(f"Value found: {cached_value}")
        return json.loads(cached_value)
    else:
        logger.debug(f"Not found for key: {key}")

    return None


def redis_cache_set_expiry(key: str, time, value: str):
    logger.debug(f"Setting value for {key} for time {time}: {value}")
    redis_client.setex(key, time, value)


def shutdown_redis():
    logger.info(f"Redis client closed")
    redis_client.close()
