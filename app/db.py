from contextlib import contextmanager
import logging
from threading import Lock

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout


class _PoolLogFilter(logging.Filter):
    def filter(self, record):
        # Driver parse/connect exceptions can embed a complete connection URI.
        # Keep the severity/event without forwarding arguments or tracebacks.
        record.msg = 'Database pool event; connection details omitted'
        record.args = ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


logging.getLogger('psycopg.pool').addFilter(_PoolLogFilter())


class DatabaseUnavailable(RuntimeError):
    pass


class Database:
    """Reuse at most four client connections; role/settings remain transaction-local."""
    def __init__(self, url: str):
        self._url = url
        self._pool = None
        self._lock = Lock()
        self._closed = False

    def _connections(self):
        if not self._url:
            raise DatabaseUnavailable('DATABASE_NOT_CONFIGURED')
        with self._lock:
            if self._closed:
                raise DatabaseUnavailable('DATABASE_CLOSED')
            if self._pool is None:
                # This client pool sits in front of Supabase's transaction pooler.
                # Disable named prepares; never rely on a retained server session.
                self._pool = ConnectionPool(self._url, min_size=1, max_size=4,
                    timeout=8, max_idle=60, max_lifetime=1800, open=False,
                    kwargs={'connect_timeout': 5, 'prepare_threshold': None,
                            'row_factory': dict_row, 'autocommit': True})
                self._pool.open()
            return self._pool

    def close(self):
        with self._lock:
            self._closed = True
            if self._pool is not None:
                self._pool.close()

    def read_one(self, query, params=None):
        """One read-only batch, including BEGIN/setup/query/COMMIT.

        Only trusted application SELECTs use this path. The guard is checked
        before returning any data; the transaction cannot modify any table.
        Financial writes retain the pre-execution guard in transaction().
        """
        try:
            with self._connections().connection() as conn:
                try:
                    # Explicit boundaries avoid psycopg's nested transaction
                    # contexts inserting extra pipeline synchronization waits.
                    with conn.pipeline():
                        conn.execute('BEGIN READ ONLY')
                        conn.execute('SET LOCAL ROLE service_role')
                        conn.execute("SET LOCAL statement_timeout = '15000ms'")
                        conn.execute("SET LOCAL lock_timeout = '5000ms'")
                        guard = conn.execute("SELECT has_column_privilege(current_user,'app.submissions','status','UPDATE') AS unsafe")
                        result = conn.execute(query, params)
                        conn.execute('COMMIT')
                except BaseException:
                    conn.rollback()
                    raise
                if guard.fetchone()['unsafe']:
                    raise DatabaseUnavailable('UNSAFE_DATABASE_GRANTS')
                return result.fetchone()
        except (PoolTimeout, PoolClosed):
            raise DatabaseUnavailable('DATABASE_BUSY_OR_UNAVAILABLE') from None

    @contextmanager
    def transaction(self):
        try:
            with self._connections().connection() as conn:
                with conn.transaction():
                    # Send independent setup statements together instead of waiting
                    # for four separate remote round trips. Exit flushes/errors
                    # before any application SQL can run.
                    with conn.pipeline():
                        conn.execute('SET LOCAL ROLE service_role')
                        conn.execute("SET LOCAL statement_timeout = '15000ms'")
                        conn.execute("SET LOCAL lock_timeout = '5000ms'")
                        guard = conn.execute("SELECT has_column_privilege(current_user,'app.submissions','status','UPDATE') AS unsafe")
                    if guard.fetchone()['unsafe']:
                        raise DatabaseUnavailable('UNSAFE_DATABASE_GRANTS')
                    yield conn
        except (PoolTimeout, PoolClosed):
            raise DatabaseUnavailable('DATABASE_BUSY_OR_UNAVAILABLE') from None

    def permission_gate(self):
        """Executes a real forbidden statement, with no row changes, in a savepoint."""
        with self.transaction() as conn:
            role = conn.execute('SELECT current_user AS role').fetchone()['role']
            if role != 'service_role':
                raise DatabaseUnavailable('RESTRICTED_ROLE_REQUIRED')
            try:
                with conn.transaction():
                    conn.execute("UPDATE app.submissions SET status='accepted' WHERE false")
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise DatabaseUnavailable('FORGERY_GATE_FAILED')
            conn.execute('SELECT active_reference_version_id FROM app.runtime_state WHERE singleton').fetchone()
        return {'restricted_role': role, 'forged_status_update': 'denied'}
