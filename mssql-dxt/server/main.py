#!/usr/bin/env python3

import os
import sys
import json
import pyodbc
from mcp.server.fastmcp import FastMCP

# Initialize MCP Server
mcp = FastMCP("mssql-dxt-server")

# Database connection details from environment variables
DB_SERVER_ADDRESS = os.environ.get("MSSQL_SERVER_ADDRESS")
DB_PORT = os.environ.get("MSSQL_PORT", "1433")
DB_NAME = os.environ.get("MSSQL_DATABASE_NAME")
DB_USERNAME = os.environ.get("MSSQL_USERNAME")
DB_PASSWORD = os.environ.get("MSSQL_PASSWORD")
DB_AUTH_METHOD = os.environ.get("MSSQL_AUTHENTICATION_METHOD", "sql_server_authentication")
DB_ODBC_DRIVER = os.environ.get("MSSQL_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
DB_TRUST_CERT = os.environ.get("MSSQL_TRUST_SERVER_CERTIFICATE", "false").lower() == "true"

def get_db_connection(database_name_override=None):
    """Establishes and returns a pyodbc connection to the SQL Server."""
    if not DB_SERVER_ADDRESS or not DB_NAME:
        raise ValueError("Server address and database name must be configured.")

    conn_str_parts = [
        f"DRIVER={{{DB_ODBC_DRIVER}}}",
        f"SERVER={DB_SERVER_ADDRESS},{DB_PORT}",
        f"DATABASE={database_name_override or DB_NAME}",
    ]

    if DB_AUTH_METHOD == "windows_authentication":
        conn_str_parts.append("Trusted_Connection=yes")
    elif DB_AUTH_METHOD == "sql_server_authentication":
        if not DB_USERNAME or DB_PASSWORD is None:
            raise ValueError("Username and password are required for SQL Server Authentication.")
        conn_str_parts.append(f"UID={DB_USERNAME}")
        conn_str_parts.append(f"PWD={{{DB_PASSWORD}}}")
    else:
        raise ValueError(f"Unsupported authentication method: {DB_AUTH_METHOD}")

    if DB_TRUST_CERT:
        conn_str_parts.append("TrustServerCertificate=yes")

    connection_string = ";".join(conn_str_parts)

    try:
        conn = pyodbc.connect(connection_string)
        return conn
    except pyodbc.Error as ex:
        # sqlstate = ex.args[0] # Uncomment for debugging if needed
        raise ConnectionError(f"Failed to connect to SQL Server: {ex}")

@mcp.tool()
def execute_query(query: str) -> str:
    """
    Executes a SQL query against the connected database.
    Returns data as a JSON string: { "columns": ["col1", ...], "rows": [[val1, ...], ...] }
    or an error message.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)

                results = {"columns": [], "rows": []}
                if cursor.description:
                    results["columns"] = [column[0] for column in cursor.description]

                fetched_rows_list = []
                try:
                    fetched_rows_from_cursor = cursor.fetchall()
                    if fetched_rows_from_cursor:
                         fetched_rows_list = [list(row_item) for row_item in fetched_rows_from_cursor]
                         results["rows"] = fetched_rows_list
                except pyodbc.ProgrammingError:
                    # Query did not return rows (e.g., UPDATE, INSERT) or cursor unavailable.
                    pass

                if not results["columns"] and not results["rows"]:
                    if cursor.rowcount != -1:
                        return json.dumps({"status": "success", "message": f"Query executed successfully. Rows affected: {cursor.rowcount}"})
                    else:
                        return json.dumps({"status": "success", "message": "Query executed successfully. No rows returned and no rowcount available."})

                return json.dumps(results)

    except (pyodbc.Error, ConnectionError) as e:
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def list_databases() -> str:
    """
    Lists all databases on the SQL server instance.
    Returns data as a JSON string: { "databases": ["db1", "db2", ...] } or an error message.
    """
    query = "SELECT name FROM sys.databases WHERE state = 0 ORDER BY name;"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                databases = [row[0] for row in cursor.fetchall()]
                return json.dumps({"databases": databases})
    except (pyodbc.Error, ConnectionError) as e:
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def list_tables(database_name: str = None) -> str:
    """
    Lists all tables in the specified database (or the default if not provided).
    Returns data as a JSON string: { "tables": ["table1", "table2", ...] } or an error message.
    """
    query = "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME;"
    try:
        current_db_name = database_name if database_name else DB_NAME
        with get_db_connection(database_name_override=current_db_name) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                tables = [f"{row[0]}.{row[1]}" for row in cursor.fetchall()]
                return json.dumps({"tables": tables})
    except (pyodbc.Error, ConnectionError) as e:
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def get_table_schema(table_name: str, schema_name: str = 'dbo', database_name: str = None) -> str:
    """
    Gets the schema (columns, types, nullability) for a specified table.
    Table name should be just the table name. Schema name defaults to 'dbo'.
    Returns data as a JSON string:
    { "schema": [{"column_name": "col1", "data_type": "varchar", "max_length": 255, "is_nullable": "YES"}, ...] }
    or an error message.
    """
    query = """
    SELECT
        COLUMN_NAME,
        DATA_TYPE,
        CHARACTER_MAXIMUM_LENGTH,
        IS_NULLABLE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = ? AND TABLE_SCHEMA = ?
    ORDER BY ORDINAL_POSITION;
    """
    try:
        current_db_name = database_name if database_name else DB_NAME
        with get_db_connection(database_name_override=current_db_name) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, table_name, schema_name)
                columns = []
                if cursor.description:
                    for row in cursor.fetchall():
                        columns.append({
                            "column_name": row[0],
                            "data_type": row[1],
                            "max_length": row[2] if row[2] is not None else -1,
                            "is_nullable": row[3]
                        })
                if not columns:
                     return json.dumps({"status": "error", "message": f"Table '{schema_name}.{table_name}' not found or has no columns in database '{current_db_name}'."})
                return json.dumps({"schema": columns})
    except (pyodbc.Error, ConnectionError) as e:
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

if __name__ == "__main__":
    # Basic check for essential config, though manifest 'required' should handle most cases.
    if not all([DB_SERVER_ADDRESS, DB_PORT, DB_NAME, DB_AUTH_METHOD, DB_ODBC_DRIVER]):
         # Consider logging an error or exiting if critical info is missing for direct script run.
         # For DXT operation, the host ensures user_config values are passed as env vars.
         pass

    try:
        mcp.run()
    except Exception as e:
        # Consider logging this critical failure.
        # print(json.dumps({"status": "error", "message": f"Server critical failure: {e}"}), file=sys.stdout) # For direct run debugging
        sys.exit(1)
