# Secret Detection Reference

Everything the browser scanner uses to detect credentials in v1.
Two detection systems work together:

1. **Regex patterns** (41) — match tokens by their structural prefix/format
2. **Key-name patterns** (178) — score KV pair key names, gate values by entropy

Plus 21 placeholder suppression patterns and 19 config-value suppressions
(both generated from Python — see `docs/secret-scanner.md` for the full logic).

---

## Part 1: Regex Patterns (41 Credential)

These fire on the **regex pass**. Each pattern matches a specific token format
(e.g., `ghp_` for GitHub PATs, `sk_live_` for Stripe keys). No key-name context needed.

| Name | Entity | Conf. | Validator | What it matches |
|------|--------|-------|-----------|-----------------|
| `argon2_hash` | PASSWORD_HASH | 0.99 | `not_placeholder_credential` | Argon2 password hash ($argon2id$, $argon2i$, $argon2d$ prefi |
| `bcrypt_hash` | PASSWORD_HASH | 0.99 | `not_placeholder_credential` | bcrypt password hash ($2a$/$2b$/$2y$ prefix, cost + 22-char  |
| `github_token` | API_KEY | 0.99 | `not_placeholder_credential` | GitHub personal access token or OAuth token |
| `gitlab_pat` | API_KEY | 0.99 | `not_placeholder_credential` | GitLab personal access token (glpat- prefix) |
| `google_api_key` | API_KEY | 0.99 | `not_placeholder_credential` | Google API key (AIza prefix + 35 chars) |
| `openai_api_key` | API_KEY | 0.99 | `not_placeholder_credential` | OpenAI project API key (sk-proj- prefix, 80+ chars) |
| `private_key_pem` | PRIVATE_KEY | 0.99 | `not_placeholder_credential` | PEM-encoded private key header |
| `scrypt_hash` | PASSWORD_HASH | 0.99 | `not_placeholder_credential` | scrypt password hash ($scrypt$ prefix with optional params + |
| `sendgrid_api_key` | API_KEY | 0.99 | `not_placeholder_credential` | SendGrid API key (SG. prefix with two base64 segments) |
| `shacrypt_hash` | PASSWORD_HASH | 0.99 | `not_placeholder_credential` | SHA-256 ($5$) or SHA-512 ($6$) crypt password hash (glibc/Li |
| `shopify_access_token` | API_KEY | 0.99 | `not_placeholder_credential` | Shopify access token (shpat_, shpca_, shppa_, shpss_ prefix  |
| `slack_bot_token` | API_KEY | 0.99 | `not_placeholder_credential` | Slack bot token (xoxb- prefix) |
| `slack_user_token` | API_KEY | 0.99 | `not_placeholder_credential` | Slack user token (xoxp- prefix) |
| `slack_webhook_url` | API_KEY | 0.99 | `not_placeholder_credential` | Slack incoming webhook URL |
| `stripe_secret_key` | API_KEY | 0.99 | `not_placeholder_credential` | Stripe secret or restricted key (sk_live_*, rk_live_*, sk_te |
| `aws_access_key` | API_KEY | 0.95 | `not_placeholder_credential` | AWS Access Key ID (AKIA prefix + 16 alphanumeric) |
| `azure_storage_account_key` | API_KEY | 0.95 | `not_placeholder_credential` | Azure Storage Account key (AccountKey= connection string fra |
| `cloudflare_api_token` | API_KEY | 0.95 | `not_placeholder_credential` | Cloudflare API token |
| `databricks_token` | API_KEY | 0.95 | `not_placeholder_credential` | Databricks personal access token (dapi prefix + 32 hex-like  |
| `digitalocean_oauth_token` | API_KEY | 0.95 | `not_placeholder_credential` | DigitalOcean OAuth access token |
| `digitalocean_pat` | API_KEY | 0.95 | `not_placeholder_credential` | DigitalOcean Personal Access Token |
| `discord_bot_token` | API_KEY | 0.95 | `not_placeholder_credential` | Discord bot token |
| `flyio_api_token` | API_KEY | 0.95 | `not_placeholder_credential` | Fly.io API token |
| `hashicorp_vault_token` | API_KEY | 0.95 | `not_placeholder_credential` | HashiCorp Vault token |
| `huggingface_token` | API_KEY | 0.95 | `not_placeholder_credential` | Hugging Face API token |
| `jwt_token` | API_KEY | 0.95 | `not_placeholder_credential` | JSON Web Token (three base64url segments starting with eyJ) |
| `linear_api_key` | API_KEY | 0.95 | `not_placeholder_credential` | Linear API key |
| `mailgun_api_key` | API_KEY | 0.95 | `not_placeholder_credential` | Mailgun API key (key- prefix + 32 hex chars) |
| `netlify_pat` | API_KEY | 0.95 | `not_placeholder_credential` | Netlify Personal Access Token |
| `npm_token` | API_KEY | 0.95 | `not_placeholder_credential` | npm access token |
| `pulumi_access_token` | API_KEY | 0.95 | `not_placeholder_credential` | Pulumi access token |
| `sentry_auth_token` | API_KEY | 0.95 | `not_placeholder_credential` | Sentry auth token |
| `stripe_publishable_key` | API_KEY | 0.95 | `not_placeholder_credential` | Stripe publishable key (less sensitive than secret, but stil |
| `supabase_service_key` | API_KEY | 0.95 | `not_placeholder_credential` | Supabase service role / personal access token |
| `terraform_cloud_token` | API_KEY | 0.95 | `not_placeholder_credential` | Terraform Cloud / HCP Terraform API token |
| `twilio_api_key` | API_KEY | 0.95 | `not_placeholder_credential` | Twilio API key (SK prefix + 32 hex chars) |
| `vercel_api_token` | API_KEY | 0.95 | `not_placeholder_credential` | Vercel API token |
| `connection_string` | API_KEY | 0.9 | `not_placeholder_credential` | Database connection string with protocol prefix |
| `generic_api_key` | API_KEY | 0.8 | `not_placeholder_credential` | Generic API key assignment pattern (api_key=... or api-key:  |
| `aws_secret_key` | API_KEY | 0.5 | `aws_secret_not_hex` | Potential AWS Secret Key (40 chars base64). Low confidence a |

> **1 pattern(s) excluded** (`random_password`) —
> require column-name context not available in browser text scanning.

---

## Part 2: Key-Name Patterns (178 Secret Scanner)

These fire on the **secret-scanner pass**. The scanner parses KV pairs from the text,
scores each key against these patterns, then applies a tiered entropy gate to the value.

### Tiers

| Tier | Count | Gate on value | Key examples |
|------|-------|---------------|-------------|
| **definitive** | 155 | Not obviously non-secret | `password`, `api_key`, `secret_key` |
| **strong** | 17 | Entropy >= 0.5 OR diversity >= 3 | `token`, `auth`, `bearer` |
| **contextual** | 6 | Entropy >= 0.7 AND diversity >= 3 | `key`, `hash`, `salt` |

### Definitive tier (155 patterns)

| Pattern | Score | Match type | Subtype |
|---------|-------|------------|---------|
| `access_key` | 0.95 | substring | API_KEY |
| `access_key_id` | 0.95 | substring | API_KEY |
| `access_token` | 0.95 | substring | API_KEY |
| `admin_password` | 0.95 | substring | OPAQUE_SECRET |
| `alibaba_access_key` | 0.95 | substring | API_KEY |
| `alibaba_access_key_secret` | 0.95 | substring | API_KEY |
| `aliyun_access_key` | 0.95 | substring | API_KEY |
| `ansible_vault_password` | 0.95 | substring | OPAQUE_SECRET |
| `api_key` | 0.95 | substring | API_KEY |
| `api_secret` | 0.95 | substring | API_KEY |
| `api_token` | 0.95 | substring | API_KEY |
| `apikey` | 0.95 | substring | API_KEY |
| `app_password` | 0.95 | substring | OPAQUE_SECRET |
| `artifactory_token` | 0.95 | substring | API_KEY |
| `atlassian_token` | 0.95 | substring | API_KEY |
| `auth0_client_secret` | 0.95 | substring | API_KEY |
| `auth0_token` | 0.95 | substring | API_KEY |
| `auth_token` | 0.95 | substring | API_KEY |
| `aws_access_key_id` | 0.95 | substring | API_KEY |
| `aws_secret_access_key` | 0.95 | substring | API_KEY |
| `aws_session_token` | 0.95 | substring | API_KEY |
| `azure_key` | 0.95 | substring | API_KEY |
| `azure_secret` | 0.95 | substring | API_KEY |
| `bearer_token` | 0.95 | substring | API_KEY |
| `buildkite_token` | 0.95 | substring | API_KEY |
| `cert_password` | 0.95 | substring | PRIVATE_KEY |
| `circleci_token` | 0.95 | substring | API_KEY |
| `clickhouse_password` | 0.95 | substring | OPAQUE_SECRET |
| `client_secret` | 0.95 | substring | API_KEY |
| `cloudflare_api_token` | 0.95 | substring | API_KEY |
| `cloudflare_token` | 0.95 | substring | API_KEY |
| `confluence_token` | 0.95 | substring | API_KEY |
| `consumer_secret` | 0.95 | substring | API_KEY |
| `cookie_secret` | 0.95 | substring | OPAQUE_SECRET |
| `couchbase_password` | 0.95 | substring | OPAQUE_SECRET |
| `csrf_secret` | 0.95 | substring | OPAQUE_SECRET |
| `datadog_app_key` | 0.95 | substring | API_KEY |
| `db_pass` | 0.95 | substring | OPAQUE_SECRET |
| `db_password` | 0.95 | substring | OPAQUE_SECRET |
| `db_pwd` | 0.95 | substring | OPAQUE_SECRET |
| `dd_api_key` | 0.95 | substring | API_KEY |
| `dd_application_key` | 0.95 | substring | API_KEY |
| `decryption_key` | 0.95 | substring | PRIVATE_KEY |
| `digitalocean_token` | 0.95 | substring | API_KEY |
| `discord_token` | 0.95 | substring | API_KEY |
| `django_secret_key` | 0.95 | substring | OPAQUE_SECRET |
| `do_pat` | 0.95 | substring | API_KEY |
| `docker_password` | 0.95 | substring | OPAQUE_SECRET |
| `drone_token` | 0.95 | substring | API_KEY |
| `elasticsearch_password` | 0.95 | substring | OPAQUE_SECRET |
| `encryption_key` | 0.95 | substring | API_KEY |
| `encryption_secret` | 0.95 | substring | PRIVATE_KEY |
| `es_password` | 0.95 | substring | OPAQUE_SECRET |
| `figma_pat` | 0.95 | substring | API_KEY |
| `figma_token` | 0.95 | substring | API_KEY |
| `flask_secret_key` | 0.95 | substring | OPAQUE_SECRET |
| `ftp_password` | 0.95 | substring | OPAQUE_SECRET |
| `gcp_credentials` | 0.95 | substring | API_KEY |
| `github_actions_token` | 0.95 | substring | API_KEY |
| `github_pat` | 0.95 | substring | API_KEY |
| `github_token` | 0.95 | substring | API_KEY |
| `gitlab_ci_token` | 0.95 | substring | API_KEY |
| `gitlab_deploy_token` | 0.95 | substring | API_KEY |
| `gitlab_runner_token` | 0.95 | substring | API_KEY |
| `gitlab_token` | 0.95 | substring | API_KEY |
| `heroku_api_key` | 0.95 | substring | API_KEY |
| `hmac_key` | 0.95 | substring | API_KEY |
| `hmac_secret` | 0.95 | substring | API_KEY |
| `hubspot_api_key` | 0.95 | substring | API_KEY |
| `hubspot_token` | 0.95 | substring | API_KEY |
| `ibm_cloud_api_key` | 0.95 | substring | API_KEY |
| `ibmcloud_api_key` | 0.95 | substring | API_KEY |
| `intercom_token` | 0.95 | substring | API_KEY |
| `jenkins_api_token` | 0.95 | substring | API_KEY |
| `jenkins_token` | 0.95 | substring | API_KEY |
| `jira_token` | 0.95 | substring | API_KEY |
| `jwt_secret` | 0.95 | substring | API_KEY |
| `keystore_password` | 0.95 | substring | PRIVATE_KEY |
| `linode_api_key` | 0.95 | substring | API_KEY |
| `linode_token` | 0.95 | substring | API_KEY |
| `mailgun_api_key` | 0.95 | substring | API_KEY |
| `mailgun_signing_key` | 0.95 | substring | API_KEY |
| `mariadb_password` | 0.95 | substring | OPAQUE_SECRET |
| `master_key` | 0.95 | substring | API_KEY |
| `mssql_password` | 0.95 | substring | OPAQUE_SECRET |
| `mysql_password` | 0.95 | substring | OPAQUE_SECRET |
| `neo4j_password` | 0.95 | substring | OPAQUE_SECRET |
| `netlify_token` | 0.95 | substring | API_KEY |
| `newrelic_api_key` | 0.95 | substring | API_KEY |
| `newrelic_license_key` | 0.95 | substring | API_KEY |
| `notion_integration_token` | 0.95 | substring | API_KEY |
| `notion_token` | 0.95 | substring | API_KEY |
| `npm_token` | 0.95 | substring | API_KEY |
| `nuget_api_key` | 0.95 | substring | API_KEY |
| `oauth_secret` | 0.95 | substring | API_KEY |
| `oauth_token` | 0.95 | substring | API_KEY |
| `oci_api_key` | 0.95 | substring | API_KEY |
| `okta_api_token` | 0.95 | substring | API_KEY |
| `okta_client_token` | 0.95 | substring | API_KEY |
| `oracle_cloud_key` | 0.95 | substring | API_KEY |
| `pagerduty_token` | 0.95 | substring | API_KEY |
| `passphrase` | 0.95 | substring | OPAQUE_SECRET |
| `passwd` | 0.95 | substring | OPAQUE_SECRET |
| `password` | 0.95 | substring | OPAQUE_SECRET |
| `pd_api_key` | 0.95 | substring | API_KEY |
| `postgres_password` | 0.95 | substring | OPAQUE_SECRET |
| `pre_shared_key` | 0.95 | substring | PRIVATE_KEY |
| `private_key` | 0.95 | substring | PRIVATE_KEY |
| `pypi_token` | 0.95 | substring | API_KEY |
| `rabbitmq_password` | 0.95 | substring | OPAQUE_SECRET |
| `redis_password` | 0.95 | substring | OPAQUE_SECRET |
| `root_password` | 0.95 | substring | OPAQUE_SECRET |
| `scaleway_key` | 0.95 | substring | API_KEY |
| `scaleway_secret_key` | 0.95 | substring | API_KEY |
| `secret_access_key` | 0.95 | substring | API_KEY |
| `secret_key` | 0.95 | substring | API_KEY |
| `sendgrid_api_key` | 0.95 | substring | API_KEY |
| `sentry_auth_token` | 0.95 | substring | API_KEY |
| `sentry_org_token` | 0.95 | substring | API_KEY |
| `service_account_key` | 0.95 | substring | API_KEY |
| `session_secret` | 0.95 | substring | OPAQUE_SECRET |
| `shared_secret` | 0.95 | substring | OPAQUE_SECRET |
| `signing_key` | 0.95 | substring | API_KEY |
| `signing_secret` | 0.95 | substring | API_KEY |
| `slack_token` | 0.95 | substring | API_KEY |
| `smtp_password` | 0.95 | substring | OPAQUE_SECRET |
| `ssh_key` | 0.95 | substring | PRIVATE_KEY |
| `ssh_passphrase` | 0.95 | substring | PRIVATE_KEY |
| `stripe_key` | 0.95 | substring | API_KEY |
| `stripe_secret` | 0.95 | substring | API_KEY |
| `teamcity_token` | 0.95 | substring | API_KEY |
| `tencent_cloud_secret` | 0.95 | substring | API_KEY |
| `tencentcloud_secretkey` | 0.95 | substring | API_KEY |
| `truststore_password` | 0.95 | substring | PRIVATE_KEY |
| `twilio_auth_token` | 0.95 | substring | API_KEY |
| `vercel_token` | 0.95 | substring | API_KEY |
| `vultr_api_key` | 0.95 | substring | API_KEY |
| `webhook_secret` | 0.95 | substring | API_KEY |
| `zendesk_token` | 0.95 | substring | API_KEY |
| `aes_key` | 0.9 | substring | PRIVATE_KEY |
| `conn_str` | 0.9 | substring | OPAQUE_SECRET |
| `connection_string` | 0.9 | substring | OPAQUE_SECRET |
| `credential` | 0.9 | substring | OPAQUE_SECRET |
| `credentials` | 0.9 | substring | OPAQUE_SECRET |
| `database_url` | 0.9 | substring | OPAQUE_SECRET |
| `discord_webhook` | 0.9 | substring | API_KEY |
| `gha_token` | 0.9 | substring | API_KEY |
| `id_token` | 0.9 | word_boundary | API_KEY |
| `oidc_token` | 0.9 | substring | API_KEY |
| `pwd` | 0.9 | substring | OPAQUE_SECRET |
| `refresh_token` | 0.9 | substring | API_KEY |
| `saml_token` | 0.9 | substring | API_KEY |
| `secret` | 0.9 | word_boundary | OPAQUE_SECRET |
| `slack_webhook` | 0.9 | substring | API_KEY |
| `token_secret` | 0.9 | word_boundary | API_KEY |

### Strong tier (17 patterns)

| Pattern | Score | Match type | Subtype |
|---------|-------|------------|---------|
| `authorization` | 0.85 | substring | API_KEY |
| `bearer` | 0.85 | substring | API_KEY |
| `deploy_token` | 0.85 | substring | API_KEY |
| `dsn` | 0.85 | word_boundary | OPAQUE_SECRET |
| `mongo_uri` | 0.85 | substring | OPAQUE_SECRET |
| `mongo_url` | 0.85 | substring | OPAQUE_SECRET |
| `psk` | 0.85 | word_boundary | PRIVATE_KEY |
| `redis_url` | 0.85 | substring | OPAQUE_SECRET |
| `session_key` | 0.85 | substring | API_KEY |
| `token` | 0.85 | word_boundary | OPAQUE_SECRET |
| `auth` | 0.8 | word_boundary | OPAQUE_SECRET |
| `ci_token` | 0.8 | word_boundary | API_KEY |
| `jwt` | 0.8 | word_boundary | API_KEY |
| `pass` | 0.8 | word_boundary | OPAQUE_SECRET |
| `state_token` | 0.8 | substring | API_KEY |
| `client_id` | 0.7 | substring | API_KEY |
| `session_id` | 0.7 | substring | OPAQUE_SECRET |

### Contextual tier (6 patterns)

| Pattern | Score | Match type | Subtype |
|---------|-------|------------|---------|
| `code_verifier` | 0.65 | word_boundary | API_KEY |
| `iv` | 0.65 | word_boundary | OPAQUE_SECRET |
| `nonce` | 0.65 | word_boundary | OPAQUE_SECRET |
| `hash` | 0.6 | word_boundary | OPAQUE_SECRET |
| `salt` | 0.6 | word_boundary | OPAQUE_SECRET |
| `key` | 0.55 | suffix | OPAQUE_SECRET |

---

## Part 3: Suppression

Values that match these are filtered OUT (not reported as findings):

- **19 config values** — `true`, `false`, `production`, `development`, etc.
- **34 placeholder values** — `changeme`, `password`, `secret`, etc.
- **21 placeholder patterns** — repeated chars, `YOUR_API_KEY_HERE`, `{{VAR}}`, `<token>`, etc.
- **Anti-indicators** — `example`, `test`, `demo`, `sample` in key or value
- **URLs** — values starting with `http://` or `https://`
- **Dates** — values matching `YYYY-MM-DD` or `YYYY/MM/DD`
- **Prose** — values with spaces and >60% alphabetic characters

All suppression data is generated from the Python source.
Run `npm run generate` to refresh after Python changes.
