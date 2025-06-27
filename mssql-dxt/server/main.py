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
        # This case should ideally be caught by user_config required fields
        # but good to have a fallback.
        raise ValueError("Server address and database name must be configured.")

    conn_str_parts = [
        f"DRIVER={{{DB_ODBC_DRIVER}}}",
        f"SERVER={DB_SERVER_ADDRESS},{DB_PORT}",
        f"DATABASE={database_name_override or DB_NAME}",
    ]

    if DB_AUTH_METHOD == "windows_authentication":
        conn_str_parts.append("Trusted_Connection=yes")
    elif DB_AUTH_METHOD == "sql_server_authentication":
        if not DB_USERNAME or DB_PASSWORD is None: # Check for None explicitly for password
            raise ValueError("Username and password are required for SQL Server Authentication.")
        conn_str_parts.append(f"UID={DB_USERNAME}")
        conn_str_parts.append(f"PWD={{{DB_PASSWORD}}}") # Passwords can have special chars
    else:
        raise ValueError(f"Unsupported authentication method: {DB_AUTH_METHOD}")

    if DB_TRUST_CERT:
        conn_str_parts.append("TrustServerCertificate=yes")

    connection_string = ";".join(conn_str_parts)

    try:
        # mcp.log.info(f"Attempting to connect with: {connection_string.replace(DB_PASSWORD, '********') if DB_PASSWORD else connection_string}")
        conn = pyodbc.connect(connection_string)
        return conn
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        # mcp.log.error(f"pyodbc error: {sqlstate} - {ex}")
        raise ConnectionError(f"Failed to connect to SQL Server: {ex}") # Raise a more generic error

# --- Tool Implementations ---

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

                try {
                    # Fetchall might fail for some statement types (e.g. DDL, non-returning DML)
                    # or if there are no rows.
                    rows = cursor.fetchall()
                    if rows:
                         results["rows"] = [list(row) for row in rows]
                } except pyodbc.ProgrammingError:
                    # This can happen if the query doesn't return rows (e.g., an UPDATE or INSERT statement)
                    # Or for some drivers/configurations after certain DDL.
                    # mcp.log.info(f"Query '{query[:100]}...' did not return rows or cursor became unavailable.")
                    pass # No rows to fetch, or not a query that returns rows.

                if not results["columns"] and not results["rows"]:
                    # If there are no columns and no rows (e.g. successful DML/DDL)
                    # Return a success message with row count if available
                    if cursor.rowcount != -1:
                        return json.dumps({"status": "success", "message": f"Query executed successfully. Rows affected: {cursor.rowcount}"})
                    else:
                        return json.dumps({"status": "success", "message": "Query executed successfully. No rows returned."})

                return json.dumps(results)

    except (pyodbc.Error, ConnectionError) as e:
        # mcp.log.error(f"Error in execute_query: {e}")
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        # mcp.log.error(f"Unexpected error in execute_query: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})


@mcp.tool()
def list_databases() -> str:
    """
    Lists all databases on the SQL server instance.
    Returns data as a JSON string: { "databases": ["db1", "db2", ...] } or an error message.
    """
    query = "SELECT name FROM sys.databases WHERE state = 0 ORDER BY name;" # Only online databases
    try:
        # Connect to the 'master' database or the initially configured DB_NAME to list all databases
        # Some server configs might restrict sys.databases visibility based on current DB context.
        # Using the configured DB_NAME is safer if it's guaranteed to have permissions.
        # If not, 'master' is a common choice for such global queries.
        # For simplicity, using the default connection from get_db_connection() for now.
        # This means the user specified in user_config needs permission to view sys.databases from their default DB.
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                databases = [row[0] for row in cursor.fetchall()]
                return json.dumps({"databases": databases})
    except (pyodbc.Error, ConnectionError) as e:
        # mcp.log.error(f"Error in list_databases: {e}")
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        # mcp.log.error(f"Unexpected error in list_databases: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def list_tables(database_name: str = None) -> str:
    """
    Lists all tables in the specified database (or the default if not provided).
    Returns data as a JSON string: { "tables": ["table1", "table2", ...] } or an error message.
    """
    # SQL to list tables varies slightly by RDBMS, this is for SQL Server
    query = "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME;"
    try:
        # Use the provided database_name or the default from config
        current_db_name = database_name if database_name else DB_NAME
        with get_db_connection(database_name_override=current_db_name) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                tables = [f"{row[0]}.{row[1]}" for row in cursor.fetchall()] # schema.table
                return json.dumps({"tables": tables})
    except (pyodbc.Error, ConnectionError) as e:
        # mcp.log.error(f"Error in list_tables: {e}")
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        # mcp.log.error(f"Unexpected error in list_tables: {e}")
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
    # Query for SQL Server
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
                if cursor.description: # Ensure there are columns before fetching
                    for row in cursor.fetchall():
                        columns.append({
                            "column_name": row[0],
                            "data_type": row[1],
                            "max_length": row[2] if row[2] is not None else -1, # -1 for types without length like int
                            "is_nullable": row[3]
                        })
                if not columns:
                     return json.dumps({"status": "error", "message": f"Table '{schema_name}.{table_name}' not found or has no columns in database '{current_db_name}'."})
                return json.dumps({"schema": columns})
    except (pyodbc.Error, ConnectionError) as e:
        # mcp.log.error(f"Error in get_table_schema: {e}")
        return json.dumps({"status": "error", "message": str(e)})
    except Exception as e:
        # mcp.log.error(f"Unexpected error in get_table_schema: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

# --- Main Execution ---
if __name__ == "__main__":
    # For local debugging, you might want to set environment variables manually here
    # or load them from a .env file if you add python-dotenv to requirements.txt
    # Example:
    # os.environ['MSSQL_SERVER_ADDRESS'] = 'localhost'
    # os.environ['MSSQL_DATABASE_NAME'] = 'MyTestDB'
    # os.environ['MSSQL_AUTHENTICATION_METHOD'] = 'windows_authentication'
    # ... etc.

    # FastMCP uses mcp.log for logging, which prints to stderr.
    # You can adjust its level or add more detailed logging if needed.
    # mcp.log.info("Starting MS SQL Server DXT Extension server...")
    # mcp.log.debug(f"Driver: {DB_ODBC_DRIVER}, Server: {DB_SERVER_ADDRESS}, DB: {DB_NAME}, Auth: {DB_AUTH_METHOD}")

    if not all([DB_SERVER_ADDRESS, DB_PORT, DB_NAME, DB_AUTH_METHOD, DB_ODBC_DRIVER]):
         # mcp.log.error("One or more required environment variables for DB connection are missing.")
         # This check is a bit redundant given manifest user_config "required": true,
         # but good for direct script execution or if env vars are somehow not passed.
         # The DXT host should ensure required user_config values are set.
         # For now, allow it to proceed and fail in get_db_connection if critical ones are missing.
         pass


    try {
        mcp.run()
    } except Exception as e:
        # mcp.log.critical(f"Server failed to start or crashed: {e}")
        # print(json.dumps({"status": "error", "message": f"Server critical failure: {e}"}), file=sys.stdout)
        sys.exit(1)
