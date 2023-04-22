# coding=utf-8
# SPDX-FileCopyrightText: 2023-present Remco <remco@educationwarehouse.nl>
#
# SPDX-License-Identifier: MIT

from edwh_migrate import migration

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
    db.executesql('''
    ''')
    db.commit()
    return True
