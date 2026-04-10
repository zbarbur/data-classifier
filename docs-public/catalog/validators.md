# Validators

Validators run after a regex pattern matches to reduce false positives. If a validator returns `False`, the match is discarded.

The library includes **10 validators**.

| Validator | Description |
|---|---|
| `aba_checksum` | No description available. |
| `dea_checkdigit` | No description available. |
| `ein_prefix` | No description available. |
| `iban_checksum` | IBAN mod-97 checksum validation. (Placeholder -- not yet implemented.) |
| `ipv4_not_reserved` | Rejects common non-PII IPv4 addresses: localhost (127.0.0.1), broadcast (255.255.255.255), and 0.0.0.0. |
| `luhn` | Luhn algorithm checksum validation for credit card numbers. Rejects values that do not pass the Luhn check. |
| `luhn_strip` | Luhn check after stripping separators (dashes, spaces). Same as `luhn` but pre-processes the value. |
| `npi_luhn` | No description available. |
| `ssn_zeros` | Rejects SSNs with all-zeros in any group (area, group, or serial). Also rejects known test/advertising SSNs (078-05-1120, 219-09-9999). |
| `vin_checkdigit` | No description available. |
