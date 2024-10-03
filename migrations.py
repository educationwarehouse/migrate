# coding=utf-8
# SPDX-FileCopyrightText: 2023-present Remco <remco@educationwarehouse.nl>
#
# SPDX-License-Identifier: MIT
# type: ignore

from edwh_migrate import migration, ViewMigrationManager


class ExampleDependency(ViewMigrationManager):
    # will also run used_by (= ExampleViewManager)

    def down(self):
        print('2. this happens before before the migration', self.db._uri)

    def up(self):
        print('3. this happens after after the migration', self.db._uri)


class ExampleViewManager(ViewMigrationManager):
    uses = [
        ExampleDependency,
    ]
    # only runs itself, not the dependency

    def down(self):
        print('1. this happens before the migration', self.db._uri)

    def up(self):
        print('4. this happens after the migration', self.db._uri)


@migration
def feature_1(db):
    # mogelijkheden om in een feature te doen:
    # 1. SQL strings uitvoeren richting database
    # 2. Bestanden lezen en uitvoeren als sql string, of verschillende statements achter elkaar
    # 3. PG_RESTORE uitvoeren mbv plumbum om zo een hele database te recoveren
    # en daarnaast
    # 1. wijzigingen die in de data horen nav een schemawijziging...
    #
    # een andere manier zou zijn om dit uit bestanden te lezen en die door te voeren
    # dan heb je de functies niet zo zeer nodig, maar heb je wel je schema bijgewerkt. Zolang je geen
    # logica van python nodig hebt kun je best veel doen met alleen maar SQL scripts
    # sorted(/features/*.sql) | cat vanaf invoer |
    return True


@migration(requires=feature_1)
def feature_2(db):
    print("feature_2")
    return True


@migration(requires=feature_2)
def feature_3(db):
    print("feature_3")
    return True


@migration
def functionalname_date_sequencenr(db):
    with ExampleDependency(db):
        db.executesql("""
        
        """)

    db.commit()
    return False
