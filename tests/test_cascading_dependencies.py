import pytest

from src.edwh_migrate import activate_migrations, get_config, list_migrations, migration, setup_db

from .fixtures import clean_migrate, sqlite_empty, tmp_empty_sqlite_db_file, tmp_sqlite_folder  # noqa


def test_cascading_order(tmp_empty_sqlite_db_file, clean_migrate):
    # file 1
    @migration()
    def c1(db):
        return True

    @migration()
    def c2(db):
        return True

    @migration()
    def c3(db):
        return True

    @migration()
    def c4(db):
        return True

    @migration()
    def c5(db):
        return True

    @migration()
    def c6(db):
        return True

    # file 2
    @migration(requires=[c2])
    def a1(db):
        return True

    @migration()
    def a2(db):
        return True

    @migration(requires=[c4, "c6"])
    def a3(db):
        return True

    @migration()
    def a4(db):
        return True

    @migration()
    def a5(db):
        return True

    config = get_config()

    expected_order = ["c1", "c2", "a1", "c3", "c4", "c5", "c6", "a3", "a2", "a4", "a5"]

    assert list(list_migrations(config).keys()) == expected_order

    assert activate_migrations(config)

    db = setup_db(config=config)

    assert db(db.ewh_implemented_features).select("name").column("name") == expected_order


def test_cascade_on_nonexisting(tmp_empty_sqlite_db_file, clean_migrate):
    @migration()
    def very_real(db): ...

    try:

        @migration(requires=["very_real", "very_fake"])
        def depends_on(db): ...

        assert False, "unreachable"
    except ValueError as e:
        assert "very_fake" in str(e)


def test_duplicate(tmp_empty_sqlite_db_file, clean_migrate):
    @migration()
    def very_first_001(db):
        return False

    with pytest.raises(ValueError):

        @migration()
        def very_first_001(db):
            return True
