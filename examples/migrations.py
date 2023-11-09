from pydal import DAL

from edwh_migrate import migration


@migration
def create_users_table_20231109_001(db: DAL):
    db.executesql(
        """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) NOT NULL,
            email VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """
    )
    db.commit()
    return True


@migration(requires=create_users_table_20231109_001)
def add_password_column_to_users_20231109_001(db: DAL):
    db.executesql(
        """
        ALTER TABLE users
        ADD COLUMN password VARCHAR(100) NOT NULL
    """
    )
    db.commit()
    return True
