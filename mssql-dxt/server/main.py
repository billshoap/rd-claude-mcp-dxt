#!/usr/bin/env python3

import os
import sys
import json
import pyodbc
from mcp.server.fastmcp import FastMCP

# Initialize MCP Server
mcp = FastMCP("mssql-dxt-server")

# This environment variable can be used by the DXT to get its config.
USER_CONFIG_ENV_VAR = "USER_CONFIG"

def _is_placeholder(value: str | None) -> bool:
    """Checks if a string value is an unsubstituted placeholder."""
    if value is None:
        return False
    return value.startswith("${user_config.") and value.endswith("}")

def _get_env_val(var_name: str) -> str | None:
    """Gets environment variable, returning None if it's a placeholder or not set."""
    val = os.environ.get(var_name)
    if _is_placeholder(val):
        print(f"Info: Environment variable '{var_name}' contains placeholder, treating as not set.", file=sys.stderr)
        return None
    return val

def _get_bool_env(var_name: str, default: bool) -> bool:
    val_str = _get_env_val(var_name)
    if val_str is None:
        return default
    return val_str.lower() == 'true'

def _get_int_env(var_name: str, default: int) -> int:
    val_str = _get_env_val(var_name)
    if val_str is None:
        return default
    try:
        return int(val_str)
    except ValueError:
        print(f"Warning: Could not parse environment variable {var_name} ('{val_str}') as int, using default {default}.", file=sys.stderr)
        return default

def load_connections_from_env():
    """Loads connection configurations from individual environment variables."""
    active_connections = []
    for i in range(1, 4):  # For conn1, conn2, conn3
        env_prefix = f"APP_CONN{i}_"

        # Special handling for enable default for conn1
        enable_env_val = os.environ.get(f"{env_prefix}ENABLE") # Read raw value for default check
        if i == 1 and enable_env_val is None: # APP_CONN1_ENABLE not set at all
            is_enabled = True # Default for conn1_enable is true from manifest
        elif _is_placeholder(enable_env_val) and i == 1: # APP_CONN1_ENABLE is placeholder
             is_enabled = True # Treat placeholder as "not set by user", apply manifest default
        else: # For conn2, conn3, or if conn1_enable is explicitly set (even if placeholder for those)
            is_enabled = _get_bool_env(f"{env_prefix}ENABLE", False) # Default for conn2/3_enable is false

        if is_enabled:
            name = _get_env_val(f"{env_prefix}NAME")
            server = _get_env_val(f"{env_prefix}SERVER")
            database = _get_env_val(f"{env_prefix}DATABASE")

            if not all([name, server, database]): # Checks if any are None (due to placeholder or not set) or empty string
                print(f"Warning: Connection slot {i} is enabled but missing one or more required fields (Name, Server, Database). Check env vars starting with '{env_prefix}'. Skipping.", file=sys.stderr)
                continue

            port = _get_int_env(f"{env_prefix}PORT", 1433) # Default from manifest

            auth_method_val = _get_env_val(f"{env_prefix}AUTH_METHOD")
            auth_method = auth_method_val if auth_method_val else "sql_server_authentication" # Default from manifest

            username = _get_env_val(f"{env_prefix}USERNAME") # No default, can be None
            password = _get_env_val(f"{env_prefix}PASSWORD") # No default, can be None

            driver_val = _get_env_val(f"{env_prefix}DRIVER")
            driver = driver_val if driver_val else "ODBC Driver 17 for SQL Server" # Default from manifest

            trust_cert = _get_bool_env(f"{env_prefix}TRUST_CERT", False) # Default from manifest

            connection_details = {
                "name": name,
                "server": server,
                "port": port,
                "database": database,
                "auth_method": auth_method,
                "username": username,
                "password": password,
                "driver": driver,
                "trust_cert": trust_cert
            }

            if connection_details["auth_method"] == "sql_server_authentication" and not connection_details["username"]:
                print(f"Warning: Connection '{name}' (Slot {i}) uses SQL Server Authentication but Username is not provided. This might lead to connection issues.", file=sys.stderr)

            active_connections.append(connection_details)

    if not active_connections:
        print("Info: No active connections configured or enabled from environment variables.", file=sys.stderr)

    return {"connections": active_connections}


USER_CONFIG_DATA = None # This will be populated by load_connections_from_env

def get_db_connection(
    server_addr: str,
    port_num: str, # pyodbc expects port as string in connection string
    db_name: str,
    auth_method: str,
    odbc_driver: str,
    uname: str = None,
    pwd: str = None,
    trust_cert_bool: bool = False
):
    """Establishes and returns a pyodbc connection to the SQL Server using provided details."""
    if not server_addr or not db_name or not odbc_driver:
        raise ValueError("Server address, database name, and ODBC driver must be provided.")

    conn_str_parts = [
        f"DRIVER={{{odbc_driver}}}",
        f"SERVER={server_addr},{port_num}",
        f"DATABASE={db_name}",
    ]

    if auth_method == "windows_authentication":
        conn_str_parts.append("Trusted_Connection=yes")
    elif auth_method == "sql_server_authentication":
        if not uname: # Password can be blank for some SQL users
            raise ValueError("Username is required for SQL Server Authentication.")
        conn_str_parts.append(f"UID={uname}")
        # Password can be None or empty string, pyodbc handles it.
        # Ensure PWD key is added even if password is blank, but with proper quoting for empty.
        conn_str_parts.append(f"PWD={{{pwd or ''}}}")
    else:
        raise ValueError(f"Unsupported authentication method: {auth_method}")

    if trust_cert_bool:
        conn_str_parts.append("TrustServerCertificate=yes")

    connection_string = ";".join(conn_str_parts)
    # print(f"Attempting connection with: {connection_string.replace(pwd, '********') if pwd else connection_string}", file=sys.stderr) # For debugging

    try:
        conn = pyodbc.connect(connection_string, timeout=5) # Added timeout
        return conn
    except pyodbc.Error as ex:
        raise ConnectionError(f"Failed to connect to SQL Server '{server_addr}': {ex}")


def _get_connection_details_by_name(connection_name: str):
    """Helper to find connection details from USER_CONFIG_DATA."""
    global USER_CONFIG_DATA
    if USER_CONFIG_DATA is None: # Ensure it's loaded once
        USER_CONFIG_DATA = load_connections_from_env() # Changed function call

    connections = USER_CONFIG_DATA.get("connections", [])
    for conn_details in connections:
        if conn_details.get("name") == connection_name:
            return conn_details
    raise ValueError(f"Connection name '{connection_name}' not found in configuration.")

@mcp.tool()
def list_configured_connections() -> str:
    """
    Lists the names of all configured MSSQL connections.
    Returns data as a JSON string: { "connections": [{"name": "conn1"}, {"name": "conn2"}, ...] }
    """
    global USER_CONFIG_DATA
    if USER_CONFIG_DATA is None:
        USER_CONFIG_DATA = load_connections_from_env() # Changed function call

    connections = USER_CONFIG_DATA.get("connections", [])
    return json.dumps({"connections": [{"name": c.get("name")} for c in connections if c.get("name")]})

@mcp.tool()
def execute_query(connection_name: str, query: str) -> str:
    """
    Executes a SQL query against the specified MSSQL connection.
    Returns data as a JSON string: { "columns": ["col1", ...], "rows": [[val1, ...], ...] }
    or an error message.
    """
    try:
        conn_details = _get_connection_details_by_name(connection_name)
        with get_db_connection(
            server_addr=conn_details["server"],
            port_num=str(conn_details.get("port", 1433)),
            db_name=conn_details["database"],
            auth_method=conn_details["auth_method"],
            odbc_driver=conn_details["driver"],
            uname=conn_details.get("username"),
            pwd=conn_details.get("password"),
            trust_cert_bool=conn_details.get("trust_cert", False)
        ) as conn:
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
                    pass # Query did not return rows

                if not results["columns"] and not results["rows"]:
                    if cursor.rowcount != -1:
                        return json.dumps({"status": "success", "connection_name": connection_name, "message": f"Query executed successfully. Rows affected: {cursor.rowcount}"})
                    else:
                        return json.dumps({"status": "success", "connection_name": connection_name, "message": "Query executed successfully. No rows returned and no rowcount available."})

                return json.dumps({"connection_name": connection_name, **results})

    except (pyodbc.Error, ConnectionError, ValueError) as e:
        return json.dumps({"status": "error", "connection_name": connection_name, "message": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "connection_name": connection_name, "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def list_databases(connection_name: str) -> str:
    """
    Lists all databases on the specified SQL server instance.
    Returns data as a JSON string: { "databases": ["db1", "db2", ...] } or an error message.
    """
    query = "SELECT name FROM sys.databases WHERE state = 0 ORDER BY name;"
    try:
        conn_details = _get_connection_details_by_name(connection_name)
        with get_db_connection(
            server_addr=conn_details["server"],
            port_num=str(conn_details.get("port", 1433)),
            db_name=conn_details["database"], # Connect to default db to list others
            auth_method=conn_details["auth_method"],
            odbc_driver=conn_details["driver"],
            uname=conn_details.get("username"),
            pwd=conn_details.get("password"),
            trust_cert_bool=conn_details.get("trust_cert", False)
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                databases = [row[0] for row in cursor.fetchall()]
                return json.dumps({"connection_name": connection_name, "databases": databases})
    except (pyodbc.Error, ConnectionError, ValueError) as e:
        return json.dumps({"status": "error", "connection_name": connection_name, "message": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "connection_name": connection_name, "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def list_tables(connection_name: str, database_name: str = None) -> str:
    """
    Lists all tables in the specified database (or the connection's default if not provided)
    on the specified MSSQL connection.
    Returns data as a JSON string: { "tables": ["table1", "table2", ...] } or an error message.
    """
    query = "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME;"
    try:
        conn_details = _get_connection_details_by_name(connection_name)
        current_db_name = database_name if database_name else conn_details["database"]
        with get_db_connection(
            server_addr=conn_details["server"],
            port_num=str(conn_details.get("port", 1433)),
            db_name=current_db_name,
            auth_method=conn_details["auth_method"],
            odbc_driver=conn_details["driver"],
            uname=conn_details.get("username"),
            pwd=conn_details.get("password"),
            trust_cert_bool=conn_details.get("trust_cert", False)
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                tables = [f"{row[0]}.{row[1]}" for row in cursor.fetchall()]
                return json.dumps({"connection_name": connection_name, "database_name": current_db_name, "tables": tables})
    except (pyodbc.Error, ConnectionError, ValueError) as e:
        return json.dumps({"status": "error", "connection_name": connection_name, "message": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "connection_name": connection_name, "message": f"An unexpected error occurred: {str(e)}"})

@mcp.tool()
def get_table_schema(connection_name: str, table_name: str, schema_name: str = 'dbo', database_name: str = None) -> str:
    """
    Gets the schema for a specified table on a specified MSSQL connection.
    Schema name defaults to 'dbo'. Database defaults to connection's default.
    Returns data as a JSON string or an error message.
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
        conn_details = _get_connection_details_by_name(connection_name)
        current_db_name = database_name if database_name else conn_details["database"]
        with get_db_connection(
            server_addr=conn_details["server"],
            port_num=str(conn_details.get("port", 1433)),
            db_name=current_db_name,
            auth_method=conn_details["auth_method"],
            odbc_driver=conn_details["driver"],
            uname=conn_details.get("username"),
            pwd=conn_details.get("password"),
            trust_cert_bool=conn_details.get("trust_cert", False)
        ) as conn:
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
                     return json.dumps({"status": "error", "connection_name": connection_name, "database_name": current_db_name, "message": f"Table '{schema_name}.{table_name}' not found or has no columns in database '{current_db_name}'."})
                return json.dumps({"connection_name": connection_name, "database_name": current_db_name, "schema": columns})
    except (pyodbc.Error, ConnectionError, ValueError) as e:
        return json.dumps({"status": "error", "connection_name": connection_name, "message": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "connection_name": connection_name, "message": f"An unexpected error occurred: {str(e)}"})

def perform_startup_connection_tests():
    """
    Iterates through configured connections and attempts to connect to each one,
    logging the results to stderr.
    """
    global USER_CONFIG_DATA
    if USER_CONFIG_DATA is None: # Ensure it's loaded once
        USER_CONFIG_DATA = load_connections_from_env() # Changed function call

    connections = USER_CONFIG_DATA.get("connections", [])
    if not connections:
        print("No MSSQL connections configured.", file=sys.stderr)
        return

    print(f"Performing startup connection tests for {len(connections)} configured connection(s)...", file=sys.stderr)
    for conn_config in connections:
        conn_name = conn_config.get("name", "Unnamed Connection")
        print(f"Testing connection: '{conn_name}'...", file=sys.stderr)
        try:
            # For SQL Auth, ensure username is present if method is sql_server_authentication
            if conn_config.get("auth_method") == "sql_server_authentication" and not conn_config.get("username"):
                raise ValueError("Username is required for SQL Server Authentication.")

            # A simple query to test the connection
            test_query = "SELECT @@SERVERNAME"
            with get_db_connection(
                server_addr=conn_config["server"],
                port_num=str(conn_config.get("port", 1433)),
                db_name=conn_config["database"],
                auth_method=conn_config["auth_method"],
                odbc_driver=conn_config["driver"],
                uname=conn_config.get("username"),
                pwd=conn_config.get("password"),
                trust_cert_bool=conn_config.get("trust_cert", False)
            ) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(test_query)
                    server_name = cursor.fetchone()
                    if server_name:
                        print(f"  SUCCESS: Connected to '{conn_name}' (Server: {server_name[0]}).", file=sys.stderr)
                    else:
                        print(f"  SUCCESS: Connected to '{conn_name}' (Server name not retrieved).", file=sys.stderr)
        except (pyodbc.Error, ConnectionError, ValueError) as e:
            print(f"  FAILED to connect to '{conn_name}': {e}", file=sys.stderr)
        except Exception as e: # Catch any other unexpected errors during test
            print(f"  FAILED to connect to '{conn_name}' with an unexpected error: {e}", file=sys.stderr)
    print("Startup connection tests complete.", file=sys.stderr)


if __name__ == "__main__":
    print("DEBUG: Python script main block started.", file=sys.stderr)
    # Load config first by reading individual environment variables
    USER_CONFIG_DATA = load_connections_from_env()

    # Perform startup connection tests (logging to stderr)
    # These tests are for informative purposes and won't stop the DXT from running.
    perform_startup_connection_tests()

    try:
        mcp.run()
    except Exception as e:
        print(json.dumps({"status": "critical_error", "message": f"Server critical failure: {e}"}), file=sys.stdout) # Log to stdout for MCP
        sys.exit(1)
