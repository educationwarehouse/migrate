from src.edwh_migrate import setup_db, migrate
from src.edwh_migrate import ViewMigrationManager
from .fixtures import clean_migrate

class MyBaseView(ViewMigrationManager):
    uses = ()

    def up(self) -> None:
        print(0)

    def down(self) -> None:
        pass


class MyChildView1(ViewMigrationManager):
    uses = (MyBaseView,)

    def up(self) -> None:
        print(1)

    def down(self) -> None:
        pass


class MyChildView2(ViewMigrationManager):
    uses = (MyBaseView, MyChildView1)

    def up(self) -> None:
        print(2)

    def down(self) -> None:
        pass


def test_resolving_manager_order(clean_migrate):
    db = setup_db(migrate=True, migrate_enabled=True)

    with (MyChildView2(db), MyBaseView(db), MyChildView1(db)):
        ...
