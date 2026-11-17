"""
Optional helper for writing CRUD=macro escape-hatch functions (see attr_gen_functions modules, e.g.
mock_attr_gen_functions.py) as plain SQL DML against DuckDB, instead of hand-rolled pandas/DuckDB plumbing.
Also backs the "Open Live JDW" SQL explorer window (see ui/gui.py's JDWWindow).
"""

import duckdb


def _materialize_tables(con, tables_by_ref: dict) -> None:
    """
    Loads every table in tables_by_ref into con, named to match (e.g. tables_by_ref['account'] -> DuckDB
    table "account"). Column types are inferred from each dataframe's current contents; a table that's still
    completely empty has no data to infer types from, so every column is created as VARCHAR instead (a
    deterministic, safe default - DuckDB's own fallback for an all-empty column is unreliable and was
    observed picking INT32 for what were actually string id columns).
    """
    for name, df in tables_by_ref.items():
        if len(df) > 0:
            con.register(f"{name}__src", df)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM "{name}__src"')
            con.unregister(f"{name}__src")
        else:
            columns_sql = ", ".join(f'"{column}" VARCHAR' for column in df.columns)
            con.execute(f'CREATE TABLE "{name}" ({columns_sql})')


def _sync_tables_back(con, tables_by_ref: dict) -> None:
    """Writes each table's current contents in con back into the corresponding live dataframe, in place."""
    for name, df in tables_by_ref.items():
        result = con.execute(f'SELECT * FROM "{name}"').fetchdf()
        df.drop(df.index, inplace=True)
        for column in result.columns:
            df[column] = result[column].values


def run_sql(tables_by_ref: dict, statements) -> None:
    """
    Runs one or more SQL statements against an in-memory DuckDB connection pre-loaded with every table in
    tables_by_ref, then writes each table's post-statement contents back into the corresponding live
    dataframe in place - so INSERT/UPDATE/DELETE run here take effect immediately on the tables the engine
    actually uses. See _materialize_tables() for the column-typing caveat on still-empty tables.

    Parameters:
        - tables_by_ref (dict): the dict of live table dataframes a macro function receives, unmodified.
        - statements: a single SQL string, a single (sql, params) tuple, or a list of either, run in order.
    """
    if isinstance(statements, (str, tuple)):
        statements = [statements]

    con = duckdb.connect(":memory:")
    _materialize_tables(con, tables_by_ref)

    for statement in statements:
        if isinstance(statement, str):
            con.execute(statement)
        else:
            sql, params = statement
            con.execute(sql, params)

    _sync_tables_back(con, tables_by_ref)
    con.close()


def query(tables_by_ref: dict, sql: str):
    """
    Runs a single SQL statement against an in-memory DuckDB connection pre-loaded with every table in
    tables_by_ref (see _materialize_tables()'s docstring for the same typing caveat), syncs every table's
    post-statement contents back into the corresponding live dataframe (so this also works for INSERT/UPDATE/
    DELETE, not just SELECT), and returns the statement's own result set as a DataFrame.
    """
    con = duckdb.connect(":memory:")
    _materialize_tables(con, tables_by_ref)

    result_df = con.execute(sql).fetchdf()

    _sync_tables_back(con, tables_by_ref)
    con.close()
    return result_df


    for name, df in tables_by_ref.items():
        result = con.execute(f'SELECT * FROM "{name}"').fetchdf()
        df.drop(df.index, inplace=True)
        for column in result.columns:
            df[column] = result[column].values

    con.close()
