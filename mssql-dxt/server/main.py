#!/usr/bin/env python3

import os
import sys
import json
import pyodbc
from mcp.server.fastmcp import FastMCP

# Initialize MCP Server
mcp = FastMCP("mssql-dxt-server")

# Global store for server configurations
SERVER_CONFIGS = {}

def load_server_configs():
    """Loads server configurations from environment variable."""
    global SERVER_CONFIGS
    configs_json_str = os.environ.get("MSSQL_SERVER_CONFIGS")
    if not configs_json_str:
        # Log this or raise an error so it's visible during startup if configs are missing
        print("ERROR: MSSQL_SERVER_CONFIGS environment variable not found or empty.", file=sys.stderr)
        SERVER_CONFIGS = {} # Ensure it's an empty dict if loading fails
        return

    try:
        configs_list = json.loads(configs_json_str)
        if not isinstance(configs_list, list):
            print("ERROR: MSSQL_SERVER_CONFIGS is not a JSON list.", file=sys.stderr)
            SERVER_CONFIGS = {}
            return

        for config in configs_list:
            if isinstance(config, dict) and "name" in config:
                # Handle potentially unresolved placeholders for username/password
                # if they were not filled by the user (i.e., left as default/blank in UI)
                if config.get("username") == "${user_config.servers.items.properties.username}":
                    config["username"] = None
                if config.get("password") == "${user_config.servers.items.properties.password}":
                    config["password"] = None
                SERVER_CONFIGS[config["name"]] = config
            else:
                print(f"WARNING: Skipping invalid server configuration item: {config}", file=sys.stderr)
        print(f"Loaded {len(SERVER_CONFIGS)} server configurations: {list(SERVER_CONFIGS.keys())}", file=sys.stderr)

    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse MSSQL_SERVER_CONFIGS JSON: {e}", file=sys.stderr)
        SERVER_CONFIGS = {}
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while loading server configurations: {e}", file=sys.stderr)
        SERVER_CONFIGS = {}


def get_db_connection(server_name: str, database_name_override: str = None):
    """Establishes and returns a pyodbc connection to the specified SQL Server."""
    if not SERVER_CONFIGS:
        raise ConnectionError("No server configurations loaded. Cannot establish connection.")

    config = SERVER_CONFIGS.get(server_name)
    if not config:
        raise ValueError(f"Server configuration '{server_name}' not found.")

    db_server_address = config.get("server_address")
    db_port = str(config.get("port", "1433")) # Ensure port is a string
    db_name = database_name_override or config.get("database_name")
    db_username = config.get("username")
    db_password = config.get("password")
    db_auth_method = config.get("authentication_method", "sql_server_authentication")
    db_odbc_driver = config.get("driver", "ODBC Driver 17 for SQL Server")
    db_trust_cert = str(config.get("trust_server_certificate", "false")).lower() == "true"

    if not db_server_address or not db_name:
        raise ValueError(f"Server address and database name must be configured for '{server_name}'.")

    conn_str_parts = [
        f"DRIVER={{{db_odbc_driver}}}",
        f"SERVER={db_server_address},{db_port}",
        f"DATABASE={db_name}",
    ]

    if db_auth_method == "windows_authentication":
        conn_str_parts.append("Trusted_Connection=yes")
    elif db_auth_method == "sql_server_authentication":
        # Username might be optional if not required by server and driver allows it
        # Password can be None or empty string. pyodbc handles PWD={} for empty password.
        if db_username: # Only add UID if username is provided
            conn_str_parts.append(f"UID={db_username}")
        if db_password is not None: # Add PWD if password is not None (can be empty string)
             conn_str_parts.append(f"PWD={{{db_password}}}")
        # No explicit error here for missing username/password if auth method is SQL Server Auth,
        # as some setups might allow it (e.g. specific driver, server config).
        # The connection attempt will fail if they are truly required.
    else:
        raise ValueError(f"Unsupported authentication method: {db_auth_method} for server '{server_name}'.")

    if db_trust_cert:
        conn_str_parts.append("TrustServerCertificate=yes")

    connection_string = ";".join(conn_str_parts)
    mcp.log(f"Attempting to connect to '{server_name}' (DB: {db_name}) using driver: {db_odbc_driver}")


    try:
        conn = pyodbc.connect(connection_string, timeout=10) # Added connection timeout
        mcp.log(f"Successfully connected to '{server_name}' (DB: {db_name}).")
        return conn
    except pyodbc.Error as ex:
        mcp.log(f"ERROR: Failed to connect to SQL Server '{server_name}': {ex}")
        raise ConnectionError(f"Failed to connect to SQL Server '{server_name}': {ex}")

@mcp.tool()
def execute_query(server_name: str, query: str) -> str:
    """
    Executes a SQL query against the specified database server.
    Returns data as a JSON string: { "columns": ["col1", ...], "rows": [[val1, ...], ...] }
    or an error message.
    """
    try:
        with get_db_connection(server_name) as conn:
            with conn.cursor() as cursor:
                mcp.log(f"Executing query on '{server_name}': {query[:200]}{'...' if len(query) > 200 else ''}")
                cursor.execute(query)

                results = {"columns": [], "rows": []}
                if cursor.description:
                    results["columns"] = [column[0] for column in cursor.description]

                fetched_rows_list = []
                try:
                    fetched_rows_from_cursor = cursor.fetchall() # Potentially memory intensive for large results
                    if fetched_rows_from_cursor:
                         fetched_rows_list = [list(row_item) for row_item in fetched_rows_from_cursor]
                         results["rows"] = fetched_rows_list
                except pyodbc.ProgrammingError:
                    # Query did not return rows (e.g., UPDATE, INSERT) or cursor unavailable.
                    pass # This is fine, means no rows to fetch.

                if not results["columns"] and not results["rows"]:
                    if cursor.rowcount != -1:
                        return json.dumps({"status": "success", "server_name": server_name, "message": f"Query executed successfully. Rows affected: {cursor.rowcount}"})
                    else:
                        return json.dumps({"status": "success", "server_name": server_name, "message": "Query executed successfully. No rows returned and no rowcount available."})

                print(f"Query on '{server_name}' returned {len(results['rows'])} rows.", file=sys.stderr)
                return json.dumps(results)

    except (pyodbc.Error, ConnectionError, ValueError) as e:
        print(f"ERROR in execute_query for '{server_name}': {e}", file=sys.stderr)
        return json.dumps({"status": "error", "server_name": server_name, "message": str(e)})
    except Exception as e:
        print(f"ERROR: An unexpected error occurred in execute_query for '{server_name}': {str(e)}", file=sys.stderr)
        return json.dumps({"status": "error", "server_name": server_name, "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def list_databases(server_name: str) -> str:
    """
    Lists all databases on the specified SQL server instance.
    Returns data as a JSON string: { "databases": ["db1", "db2", ...] } or an error message.
    """
    query = "SELECT name FROM sys.databases WHERE state = 0 ORDER BY name;"
    try:
        with get_db_connection(server_name) as conn: # Connect to the master/default db of the server config
            with conn.cursor() as cursor:
                print(f"Listing databases on '{server_name}'.", file=sys.stderr)
                cursor.execute(query)
                databases = [row[0] for row in cursor.fetchall()]
                print(f"Found {len(databases)} databases on '{server_name}'.", file=sys.stderr)
                return json.dumps({"databases": databases, "server_name": server_name})
    except (pyodbc.Error, ConnectionError, ValueError) as e:
        print(f"ERROR in list_databases for '{server_name}': {e}", file=sys.stderr)
        return json.dumps({"status": "error", "server_name": server_name, "message": str(e)})
    except Exception as e:
        print(f"ERROR: An unexpected error occurred in list_databases for '{server_name}': {str(e)}", file=sys.stderr)
        return json.dumps({"status": "error", "server_name": server_name, "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def list_tables(server_name: str, database_name: str = None) -> str:
    """
    Lists all tables in the specified database (or the default for the connection if not provided)
    on the specified server.
    Returns data as a JSON string: { "tables": ["table1", "table2", ...] } or an error message.
    """
    query = "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME;"
    try:
        # database_name parameter overrides the default database_name from the server's config for this call
        with get_db_connection(server_name, database_name_override=database_name) as conn:
            # The connection context (conn) is now to the correct database (either default or override)
            db_used = conn.getinfo(pyodbc.SQL_DATABASE_NAME) # Get actual DB connected to for logging
            print(f"Listing tables in database '{db_used}' on server '{server_name}'.", file=sys.stderr)
            with conn.cursor() as cursor:
                cursor.execute(query)
                tables = [f"{row[0]}.{row[1]}" for row in cursor.fetchall()]
                print(f"Found {len(tables)} tables in database '{db_used}' on server '{server_name}'.", file=sys.stderr)
                return json.dumps({"tables": tables, "server_name": server_name, "database_name": db_used})
    except (pyodbc.Error, ConnectionError, ValueError) as e:
        print(f"ERROR in list_tables for '{server_name}' (DB: {database_name}): {e}", file=sys.stderr)
        return json.dumps({"status": "error", "server_name": server_name, "database_name": database_name, "message": str(e)})
    except Exception as e:
        print(f"ERROR: An unexpected error occurred in list_tables for '{server_name}' (DB: {database_name}): {str(e)}", file=sys.stderr)
        return json.dumps({"status": "error", "server_name": server_name, "database_name": database_name, "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def get_table_schema(server_name: str, table_name: str, schema_name: str = 'dbo', database_name: str = None) -> str:
    """
    Gets the schema (columns, types, nullability) for a specified table on the specified server.
    Table name should be just the table name. Schema name defaults to 'dbo'.
    Database name parameter overrides the default database for the connection if provided.
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
        # database_name parameter overrides the default database_name from the server's config for this call
        with get_db_connection(server_name, database_name_override=database_name) as conn:
            db_used = conn.getinfo(pyodbc.SQL_DATABASE_NAME) # Get actual DB connected to for logging
            print(f"Getting schema for table '{schema_name}.{table_name}' in database '{db_used}' on server '{server_name}'.", file=sys.stderr)
            with conn.cursor() as cursor:
                cursor.execute(query, table_name, schema_name)
                columns = []
                if cursor.description:
                    for row in cursor.fetchall():
                        columns.append({
                            "column_name": row[0],
                            "data_type": row[1],
                            "max_length": row[2] if row[2] is not None else -1, # Ensure -1 for no max_length
                            "is_nullable": row[3]
                        })
                if not columns:
                     print(f"WARNING: Table '{schema_name}.{table_name}' not found or has no columns in database '{db_used}' on server '{server_name}'.", file=sys.stderr)
                     return json.dumps({"status": "error", "server_name": server_name, "database_name": db_used, "table_name": f"{schema_name}.{table_name}", "message": f"Table '{schema_name}.{table_name}' not found or has no columns in database '{db_used}'."})
                print(f"Schema retrieved for '{schema_name}.{table_name}' in database '{db_used}' on server '{server_name}'. Found {len(columns)} columns.", file=sys.stderr)
                return json.dumps({"schema": columns, "server_name": server_name, "database_name": db_used, "table_name": f"{schema_name}.{table_name}"})
    except (pyodbc.Error, ConnectionError, ValueError) as e:
        print(f"ERROR in get_table_schema for '{server_name}' (DB: {database_name}, Table: {schema_name}.{table_name}): {e}", file=sys.stderr)
        return json.dumps({"status": "error", "server_name": server_name, "database_name": database_name, "table_name": f"{schema_name}.{table_name}", "message": str(e)})
    except Exception as e:
        print(f"ERROR: An unexpected error occurred in get_table_schema for '{server_name}' (DB: {database_name}, Table: {schema_name}.{table_name}): {str(e)}", file=sys.stderr)
        return json.dumps({"status": "error", "server_name": server_name, "database_name": database_name, "table_name": f"{schema_name}.{table_name}", "message": f"An unexpected error occurred: {str(e)}"})

if __name__ == "__main__":
    print("MSSQL DXT Server starting up...", file=sys.stderr)
    load_server_configs() # Load configs at startup

    if not SERVER_CONFIGS:
        print("CRITICAL: No server configurations were loaded. The extension may not function correctly.", file=sys.stderr)
        # Depending on desired behavior, could exit here if running standalone and no configs.
        # For DXT, it might still run but tools will fail until valid configs are provided by the host.

    try:
        mcp.run()
    except Exception as e:
        print(f"CRITICAL: MCP server encountered an unrecoverable error: {e}", file=sys.stderr)
        # print(json.dumps({"status": "error", "message": f"Server critical failure: {e}"}), file=sys.stdout) # For direct run debugging
        sys.exit(1)
