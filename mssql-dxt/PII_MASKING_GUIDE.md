# PII Masking Guide for DXT Developers

This guide explains how to configure and utilize the PII (Personally Identifiable Information) masking feature within DXTs that support it, using the `mssql-dxt` as an example.

## Overview

The PII masking system allows DXTs to automatically detect and mask sensitive data in query results before they are returned to the client. This is configured through the DXT's `manifest.json` file.

## Enabling PII Masking

To enable PII masking, you need to add a `pii_masking` object to your DXT's `manifest.json`.

```json
{
  "dxt_version": "0.1",
  "name": "your-dxt-name",
  // ... other manifest properties ...
  "pii_masking": {
    "enable": true, // Set to true to enable masking
    "default_strategy": "REDACT_ALL", // Default masking method
    "rules": [
      // ... your rules go here ...
    ],
    "predefined_patterns": {
      // ... custom or overridden regex patterns ...
    },
    "environment_variable_overrides": {
        "prefix": "MCP_YOUR_DXT_PII_", // Optional: Prefix for env var overrides
        "enable": "ENABLE_MASKING",
        "default_strategy": "DEFAULT_STRATEGY"
    }
  }
  // ... rest of manifest ...
}
```

Key fields in `pii_masking`:
-   `enable` (boolean): Set to `true` to activate PII masking. If `false` or if the `pii_masking` section is absent, masking is disabled.
-   `default_strategy` (string): The masking strategy to apply if a rule doesn't specify its own.
    -   Available strategies:
        -   `REDACT_ALL`: Replaces the entire value (e.g., with "[REDACTED]").
        -   `REDACT_PARTIAL_EMAIL`: Masks parts of an email (e.g., "u***r@d***n.com").
        -   `REDACT_PARTIAL_GENERIC`: Masks most of a string, leaving some characters at the start/end. Configurable via `strategy_params`.
        -   `HASH_SHA256`: Replaces the value with its SHA256 hash. Configurable with a salt via `strategy_params`.
-   `rules` (array): A list of rules that define what PII to look for and how to mask it.
-   `predefined_patterns` (object, optional): A dictionary where you can define or override named regex patterns.
-   `environment_variable_overrides` (object, optional): Configure environment variables that can override manifest settings.

## Defining Masking Rules

Each rule in the `rules` array is an object that specifies:
-   `rule_name` (string): A descriptive name for the rule (e.g., "MaskUserEmails").
-   `enabled` (boolean): Set to `true` for this rule to be active.
-   `type` (string): The type of detection mechanism.
    -   `predefined`: Uses a built-in or manifest-defined regex pattern.
    -   `custom_regex`: Uses a custom regex pattern you provide.
    -   `column_name_exact`: Masks the entire content of a column if its name matches exactly.
    -   `column_name_pattern`: Masks the entire content of a column if its name matches a glob pattern.
-   `pattern_name` (string, required for `predefined` type): The name of the pattern to use (e.g., "EMAIL", "PHONE", "SSN"). See `predefined_patterns` below or the library's defaults.
-   `pattern` (string, required for `custom_regex` type): The regex string. Example: `"^XYZ-[0-9]{4}$"`.
-   `column_names` (array of strings, required for `column_name_exact` type): List of exact column names to match. Example: `["user_id", "customer_id"]`. **Matching is case-insensitive.** (It's recommended to define these in lowercase in the manifest.)
-   `column_name_patterns` (array of strings, required for `column_name_pattern` type): List of glob-style column name patterns. Example: `["*_secret", "api_key_*"]`. **Matching is case-insensitive.** (It's recommended to define these in lowercase in the manifest.)
-   `apply_to_columns` (array of strings, optional): List of column names or glob patterns where this rule should be applied. If omitted or `["*"]`, the rule applies to all columns. This helps scope detection. Example: `["email", "contact_address"]`. **Matching is case-insensitive.** (It's recommended to define these in lowercase in the manifest.)
-   `strategy` (string, optional): Overrides the `default_strategy` for this specific rule.
-   `strategy_params` (object, optional): Parameters for the chosen strategy.
    -   For `REDACT_PARTIAL_GENERIC`: `{"visible_chars_start": 2, "visible_chars_end": 2, "min_len_to_mask": 5}`
    -   For `HASH_SHA256`: `{"salt": "your_unique_salt"}`

### Rule Processing Order
Currently, the first rule that successfully matches a piece of data (and its column context) will have its masking strategy applied. Subsequent rules are not processed for that specific data element.

### Example Rules:

```json
"rules": [
  {
    "rule_name": "MaskEmailsInSpecificColumns",
    "enabled": true,
    "type": "predefined",
    "pattern_name": "EMAIL",
    "apply_to_columns": ["user_email", "contactEmail"],
    "strategy": "REDACT_PARTIAL_EMAIL"
  },
  {
    "rule_name": "MaskAnySSN",
    "enabled": true,
    "type": "predefined",
    "pattern_name": "SSN",
    "apply_to_columns": ["*"] // Check all columns for SSN patterns
    // Uses default_strategy if not specified here
  },
  {
    "rule_name": "CustomInternalCode",
    "enabled": true,
    "type": "custom_regex",
    "pattern": "INTERNAL-[A-Z]{2}-[0-9]{5}",
    "apply_to_columns": ["notes", "description"],
    "strategy": "HASH_SHA256",
    "strategy_params": {"salt": "a_good_salt_value"}
  },
  {
    "rule_name": "RedactPasswordColumns",
    "enabled": true,
    "type": "column_name_pattern",
    "column_name_patterns": ["*password", "pwd", "*_secret_key"],
    "apply_to_columns": ["*"], // The column name is the pattern itself
    "strategy": "REDACT_ALL"
  }
]
```

## Predefined Patterns

The PII masking library comes with a set of default patterns:
-   `EMAIL`
-   `PHONE`
-   `SSN`
-   `CREDIT_CARD`
-   `IP_ADDRESS`

You can override these or add new ones in the `pii_masking.predefined_patterns` section of your `manifest.json`:

```json
"predefined_patterns": {
  "EMAIL": "your_custom_email_regex_if_needed", // Overrides default EMAIL
  "MY_CUSTOM_PATTERN": "^[A-Z0-9_]+$"
}
```
If a pattern is defined here, it takes precedence over the library's default for that name.

## Integration in DXT Server Code (Python Example)

The DXT server script (e.g., `main.py` for Python DXTs) needs to:
1.  **Import the `PiiMasker`**:
    ```python
    try:
        from lib.mcp_pii_utils.masker import PiiMasker
        PII_MASKER_ENABLED_LIB = True
    except ImportError:
        PiiMasker = None
        PII_MASKER_ENABLED_LIB = False
        # Log warning
    ```
2.  **Initialize the `PiiMasker`**:
    A global instance `PII_MASKER_INSTANCE` is typically created. A function like `load_pii_config_and_initialize_masker` reads the `manifest.json`, extracts the `pii_masking` config, and instantiates `PiiMasker(config)`. This function should be called once at startup.
    ```python
    # In main.py
    PII_MASKER_INSTANCE = None

    def load_pii_config_and_initialize_masker():
        global PII_MASKER_INSTANCE
        if not PII_MASKER_ENABLED_LIB: return
        try:
            # ... logic to find and read manifest.json ...
            manifest_data = json.load(f)
            pii_config = manifest_data.get("pii_masking", {"enable": False})
            PII_MASKER_INSTANCE = PiiMasker(pii_config)
            # ... logging ...
        except Exception as e:
            # ... error logging, disable masker ...
            PII_MASKER_INSTANCE = PiiMasker({"enable": False})

    # Call at startup:
    # load_pii_config_and_initialize_masker()
    ```
3.  **Apply Masking to Query Results**:
    In the function that executes database queries (e.g., `execute_query`):
    ```python
    # Inside execute_query, after fetching results:
    # results = {"columns": ["col1", "col2"], "rows": [[val1, val2], ...]}

    if PII_MASKER_INSTANCE and PII_MASKER_INSTANCE.enabled and results["rows"] and results["columns"]:
        try:
            results["rows"] = PII_MASKER_INSTANCE.mask_data(results["rows"], results["columns"])
        except Exception as pii_ex:
            # Log PII masking error
            pass # Decide whether to return original or error out

    # Return json.dumps(results)
    ```
Refer to the `mssql-dxt/server/main.py` for a complete integration example.

## Important Considerations
-   **Performance**: Complex regex rules or a large number of rules applied to many columns can impact performance. Use `apply_to_columns` to scope rules effectively.
-   **Regex Security**: Be cautious with user-supplied or complex regexes to avoid issues like ReDoS.
-   **False Positives/Negatives**: PII detection, especially with generic regexes, can have false positives or miss some PII. Tailor rules carefully. Column-specific rules are often more reliable.
-   **Order of Rules**: The first matching rule wins. If data could match multiple rules, order them accordingly.
-   **Data Types**: Currently, the PII masker primarily operates on string data. Non-string values are typically passed through without masking.

This guide should help you effectively implement PII masking in your DXTs.
```
