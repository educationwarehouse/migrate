import pytest
from testcontainers.redis import RedisContainer

from src.edwh_migrate import activate_migrations, get_config

from .fixtures import *


@pytest.fixture
def redis(request):
    r = RedisContainer("redis:6.2.6")
    request.addfinalizer(r.stop)

    r.start()
    return r


@pytest.fixture
def valkey(request):
    r = RedisContainer("valkey/valkey:7.2.5")
    request.addfinalizer(r.stop)

    r.start()
    return r


def test_redis_cleared(tmp_just_implemented_features_sqlite_db_file: Path, redis: RedisContainer):
    config = get_config()

    redis_host = redis.get_container_host_ip()
    redis_port = redis.get_exposed_port(redis.port)
    config.redis_host = f"{redis_host}:{redis_port}"

    redis_client = redis.get_client()

    redis_client.set("a", 1)
    assert redis_client.get("a")
    assert not redis_client.get("b")

    activate_migrations(config)

    assert not redis_client.get("a")
    assert not redis_client.get("b")


def test_valkey_cleared(tmp_just_implemented_features_sqlite_db_file: Path, valkey: RedisContainer):
    config = get_config()

    redis_host = valkey.get_container_host_ip()
    redis_port = valkey.get_exposed_port(valkey.port)
    config.redis_host = f"{redis_host}:{redis_port}"

    redis_client = valkey.get_client()

    redis_client.set("a", 1)
    assert redis_client.get("a")
    assert not redis_client.get("b")

    activate_migrations(config)

    assert not redis_client.get("a")
    assert not redis_client.get("b")
