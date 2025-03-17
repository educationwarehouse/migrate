from src.edwh_migrate import list_migrations, get_config
from src.edwh_migrate import migration

def test_cascading_order():
    # file 1
    @migration()
    def c1(db):
        ...

    @migration()
    def c2(db):
        ...

    @migration()
    def c3(db):
        ...

    @migration()
    def c4(db):
        ...

    @migration()
    def c5(db):
        ...

    @migration()
    def c6(db):
        ...

    # file 2
    @migration(requires=[c2])
    def a1(db):
        ...

    @migration()
    def a2(db):
        ...

    @migration(requires=[c4, c6])
    def a3(db):
        ...

    @migration()
    def a4(db):
        ...

    @migration()
    def a5(db):
        ...

    config = get_config()
    print(
        list_migrations(config)
    )
