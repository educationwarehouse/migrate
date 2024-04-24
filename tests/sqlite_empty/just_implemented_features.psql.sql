-- Begin transaction
BEGIN;

-- Create table if not exists
CREATE TABLE IF NOT EXISTS public.ewh_implemented_features (
    id SERIAL PRIMARY KEY, -- id as a serial primary key (auto increment)
    name TEXT,
    installed CHAR(1),
    last_update_dttm TIMESTAMP
);

-- Since PostgreSQL does not use the `DELETE FROM sqlite_sequence` statement, 
-- we can skip this part. It is used to reset autoincrement values in SQLite, 
-- but in PostgreSQL, this is automatically handled with the SERIAL data type.

-- Commit the transaction
COMMIT;