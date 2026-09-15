import contextlib
import logging
import time

from psycopg2.pool import ThreadedConnectionPool

from dsrag.utils.imports import LazyLoader

# Lazy load PostgreSQL dependencies
psycopg2 = LazyLoader("psycopg2", "psycopg2-binary")


class Postgres:
    MAX_IDLE_TIME = 300
    def __init__(self, connection_params: dict):
        self.last_connection = time.time()
        self.connection_params = connection_params
        self.connection_pool = self.create_connection_pool()

    def create_connection_pool(self):
        return ThreadedConnectionPool(
            1,  # minconn
            20,  # maxconn
            **self.connection_params
        )

    @contextlib.contextmanager
    def get_db_connection(self):
        """
        Context manager to acquire a connection from the pool and return it.
        """
        conn = None
        try:
            # When using a serverless Postgres instance connections may end up as orphans if the database is not being
            # used. This replaces all of them if a connection is not acquired frequently enough
            if time.time() - self.last_connection > self.MAX_IDLE_TIME:
                self.connection_pool.closeall()
                self.connection_pool = self.create_connection_pool()

            self.last_connection = time.time()
            conn = self.connection_pool.getconn()
            # Yield the connection object to the 'with' block
            yield conn
        except psycopg2.Error as e:
            # Roll back the transaction if an error occurs within the 'with' block
            if conn:
                conn.rollback()
            logging.error(f"Database error: {e}")
            raise
        finally:
            # Ensure the connection is returned to the pool when the block is exited
            if conn:
                # Commit the transaction if no exception was raised in the 'with' block
                if conn.autocommit is False:
                    conn.commit()
                self.connection_pool.putconn(conn)

    def __del__(self):
        self.connection_pool.closeall()
