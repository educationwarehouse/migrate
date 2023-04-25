PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS "ewh_implemented_features"
(
    id               integer
        primary key autoincrement,
    name             text,
    installed        char(1),
    last_update_dttm datetime
);
DELETE FROM sqlite_sequence;
INSERT INTO sqlite_sequence VALUES('ewh_implemented_features',0);
COMMIT;
