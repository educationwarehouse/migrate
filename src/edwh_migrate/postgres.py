try:
    import psycopg2
    import psycopg2.errors

    PostgresError = psycopg2.errors.Error

    PostgresUndefinedTable = psycopg2.errors.UndefinedTable

except ImportError:  # pragma: no cover
    """
    Create fallback exceptions for when psycopg2 is not installed (e.g. when using `migrate` with sqlite only).
    """

    class PostgresError(Exception):
        """
        Placeholder for when psycopg2 is not installed.
        """

    class PostgresUndefinedTable(Exception):
        """
        Placeholder for when psycopg2 is not installed.
        """
