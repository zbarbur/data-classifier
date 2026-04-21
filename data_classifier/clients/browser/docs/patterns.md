# Secret Detection Reference

Everything the browser scanner uses to detect credentials.
Two detection systems work together:

1. **Regex patterns** (122) — match tokens by their structural prefix/format
2. **Key-name patterns** (283) — score KV pair key names, gate values by entropy

Plus placeholder suppression patterns and config-value suppressions
(both generated from Python — see `docs/secret-scanner.md` for the full logic).

---

## Part 1: Regex Patterns (122 Credential)

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
| `age_secret_key` | API_KEY | 0.98 | — | Age encryption tool secret key (AGE-SECRET-KEY-1 prefix, bec |
| `dynatrace_api_token` | API_KEY | 0.98 | — | Dynatrace API token (dt0c01. prefix with two dotted segments |
| `sendinblue_api_token` | API_KEY | 0.98 | — | Sendinblue (Brevo) API token (xkeysib- prefix, 64 hex + dash |
| `sentry_user_token` | API_KEY | 0.98 | — | Sentry user API token (sntryu_ prefix, 64 hex chars). Distin |
| `1password_secret_key` | API_KEY | 0.97 | — | 1Password secret key (A3-XXXXXX-... format). Fixed prefix wi |
| `clojars_api_token` | API_KEY | 0.97 | — | Clojars package registry API token (CLOJARS_ prefix, 60 alph |
| `doppler_api_token` | API_KEY | 0.97 | — | Doppler secrets manager API token (dp.pt. prefix, 43 alphanu |
| `duffel_api_token` | API_KEY | 0.97 | — | Duffel travel API token (duffel_test_ or duffel_live_ prefix |
| `easypost_api_key` | API_KEY | 0.97 | — | EasyPost live API key (EZAK prefix, 54 alphanumeric chars). |
| `easypost_test_api_key` | API_KEY | 0.97 | — | EasyPost test API key (EZTK prefix, 54 alphanumeric chars). |
| `flutterwave_public_key` | API_KEY | 0.97 | — | Flutterwave test public key (FLWPUBK_TEST- prefix, hex-subse |
| `flutterwave_secret_key` | API_KEY | 0.97 | — | Flutterwave test secret key (FLWSECK_TEST- prefix, hex-subse |
| `frameio_api_token` | API_KEY | 0.97 | — | Frame.io (Adobe) API token (fio-u- prefix, 64 alphanumeric/s |
| `hashicorp_vault_token_extended` | API_KEY | 0.97 | — | HashiCorp Vault batch token (hvb. prefix, 138-300 alphanumer |
| `heroku_api_key_v2` | API_KEY | 0.97 | — | Heroku API key v2 format (HRKU-AA prefix, 58 chars). Distinc |
| `microsoft_teams_webhook` | API_KEY | 0.97 | — | Microsoft Teams incoming webhook URL (webhook.office.com/web |
| `new_relic_api_key` | API_KEY | 0.97 | — | New Relic user API key (NRAK- prefix, 27 alphanumeric chars) |
| `new_relic_browser_token` | API_KEY | 0.97 | — | New Relic browser API token (NRJS- prefix, 19 hex chars). |
| `new_relic_insert_key` | API_KEY | 0.97 | — | New Relic insert (Insights) key (NRII- prefix, 32 chars). |
| `notion_api_token` | API_KEY | 0.97 | — | Notion API integration token (ntn_ prefix, 11-digit numeric  |
| `perplexity_api_key` | API_KEY | 0.97 | — | Perplexity AI API key (pplx- prefix, 48 alphanumeric chars). |
| `planetscale_api_token` | API_KEY | 0.97 | — | PlanetScale API token (pscale_tkn_ prefix). |
| `planetscale_password` | API_KEY | 0.97 | — | PlanetScale database password (pscale_pw_ prefix). |
| `prefect_api_token` | API_KEY | 0.97 | — | Prefect Cloud API token (pnu_ prefix, 36 alphanumeric chars) |
| `readme_api_token` | API_KEY | 0.97 | — | ReadMe.io API token (rdme_ prefix, 70 lowercase alphanumeric |
| `rubygems_api_token` | API_KEY | 0.97 | — | RubyGems.org API token (rubygems_ prefix, 48 hex chars). |
| `scalingo_api_token` | API_KEY | 0.97 | — | Scalingo PaaS API token (tk-us- prefix, 48 alphanumeric char |
| `shippo_api_token` | API_KEY | 0.97 | — | Shippo shipping API token (shippo_live_ or shippo_test_ pref |
| `slack_config_refresh_token` | API_KEY | 0.97 | — | Slack configuration refresh token (xoxe- prefix, version dig |
| `sourcegraph_access_token` | API_KEY | 0.97 | — | Sourcegraph access token (sgp_ prefix with 16-char instance  |
| `typeform_api_token` | API_KEY | 0.97 | — | Typeform API personal access token (tfp_ prefix, 59 chars). |
| `alibaba_access_key_id` | API_KEY | 0.96 | — | Alibaba Cloud access key ID (LTAI prefix, 20 alphanumeric ch |
| `artifactory_api_key_structured` | API_KEY | 0.96 | — | JFrog Artifactory API key (AKCp prefix, 69 alphanumeric char |
| `aws_access_key_id_extended` | API_KEY | 0.96 | — | AWS temporary (ASIA), AWS Billing (ABIA), or ACCA access key |
| `gcp_api_key` | API_KEY | 0.96 | — | Google Cloud Platform (GCP) API key (AIza prefix, 35 alphanu |
| `gitlab_token_extended` | API_KEY | 0.96 | — | GitLab extended token types: CICD job (glcbt-), deploy (gldt |
| `hashicorp_terraform_token` | API_KEY | 0.96 | — | HashiCorp Terraform Cloud API token (14-char prefix + .atlas |
| `infracost_api_token` | API_KEY | 0.96 | — | Infracost cloud cost estimation API token (ico- prefix, 32 a |
| `settlemint_access_token` | API_KEY | 0.96 | — | SettleMint application (sm_aat_), personal (sm_pat_), or ser |
| `slack_app_token` | API_KEY | 0.96 | — | Slack app-level token (xapp- prefix with numeric version and |
| `adobe_client_secret` | API_KEY | 0.95 | — | Adobe OAuth client secret (p8e- prefix, 32 alphanumeric char |
| `airtable_pat` | API_KEY | 0.95 | — | Airtable Personal Access Token — 'pat' prefix + 14-char toke |
| `anthropic_api_key` | API_KEY | 0.95 | `not_placeholder_credential` | Anthropic API key (sk-ant-api/admin prefix, 93+ char suffix) |
| `atlassian_api_token` | API_KEY | 0.95 | — | Atlassian (Jira/Confluence) API token with atatt3 prefix (18 |
| `aws_access_key` | API_KEY | 0.95 | `not_placeholder_credential` | AWS Access Key ID (AKIA prefix + 16 alphanumeric) |
| `azure_storage_account_key` | API_KEY | 0.95 | `not_placeholder_credential` | Azure Storage Account key (AccountKey= connection string fra |
| `cloudflare_api_token` | API_KEY | 0.95 | `not_placeholder_credential` | Cloudflare API token |
| `databricks_token` | API_KEY | 0.95 | `not_placeholder_credential` | Databricks personal access token (dapi prefix + 32 hex-like  |
| `digitalocean_oauth_token` | API_KEY | 0.95 | `not_placeholder_credential` | DigitalOcean OAuth access token |
| `digitalocean_pat` | API_KEY | 0.95 | `not_placeholder_credential` | DigitalOcean Personal Access Token |
| `discord_bot_token` | API_KEY | 0.95 | `not_placeholder_credential` | Discord bot token |
| `docker_hub_pat` | API_KEY | 0.95 | — | Docker Hub personal access token (dckr_pat_ prefix, 27 chars |
| `figma_pat` | API_KEY | 0.95 | — | Figma personal access token (figd_ prefix) |
| `flyio_api_token` | API_KEY | 0.95 | `not_placeholder_credential` | Fly.io API token |
| `grafana_cloud_api_token` | API_KEY | 0.95 | — | Grafana Cloud API token (glc_ prefix, base64 JWT body) |
| `grafana_service_account_token` | API_KEY | 0.95 | — | Grafana service account token (glsa_ prefix, 32 alnum + 8 he |
| `groq_api_key` | API_KEY | 0.95 | — | Groq API key (gsk_ prefix, 52 alphanumeric, fixed length) |
| `hashicorp_vault_token` | API_KEY | 0.95 | `not_placeholder_credential` | HashiCorp Vault token |
| `heroku_api_key` | API_KEY | 0.95 | — | Heroku OAuth access token (HRKU- prefix, 65 chars total incl |
| `huggingface_token` | API_KEY | 0.95 | `not_placeholder_credential` | Hugging Face API token |
| `jwt_token` | API_KEY | 0.95 | `not_placeholder_credential` | JSON Web Token (three base64url segments starting with eyJ) |
| `langfuse_public_key` | API_KEY | 0.95 | — | Langfuse public key — pk-lf- prefix followed by 32+ alphanum |
| `langfuse_secret_key` | API_KEY | 0.95 | — | Langfuse secret key — sk-lf- prefix followed by 32+ alphanum |
| `langsmith_api_key` | API_KEY | 0.95 | — | LangSmith (LangChain) API key — PAT (lsv2_pt_) or service ke |
| `linear_api_key` | API_KEY | 0.95 | `not_placeholder_credential` | Linear API key |
| `linear_api_token` | API_KEY | 0.95 | — | Linear API token (lin_api_ prefix) |
| `mailgun_api_key` | API_KEY | 0.95 | `not_placeholder_credential` | Mailgun API key (key- prefix + 32 hex chars) |
| `mapbox_api_token` | API_KEY | 0.95 | — | Mapbox public access token (pk. prefix, 60-char scope + 22-c |
| `netlify_pat` | API_KEY | 0.95 | `not_placeholder_credential` | Netlify Personal Access Token |
| `newrelic_browser_token` | API_KEY | 0.95 | — | New Relic Browser/JS Agent token (NRJS- prefix, 19 lowercase |
| `newrelic_user_api_key` | API_KEY | 0.95 | — | New Relic User API Key (NRAK- prefix, 27 uppercase alphanume |
| `notion_integration_token` | API_KEY | 0.95 | — | Notion integration token (ntn_ prefix, 11 digits + 35 alnum, |
| `npm_token` | API_KEY | 0.95 | `not_placeholder_credential` | npm access token |
| `nvidia_nim_api_key` | API_KEY | 0.95 | — | NVIDIA NIM/NGC API key (nvapi- prefix) |
| `openai_legacy_key` | API_KEY | 0.95 | `openai_legacy_key` | OpenAI legacy API key (sk- prefix, 48-char suffix, no proj-  |
| `packagist_token` | API_KEY | 0.95 | — | Packagist API token (packagist_ prefix, 3-char env tag, 68 h |
| `postman_api_key` | API_KEY | 0.95 | — | Postman API key (PMAK- prefix, 24-hex ID segment + hyphen +  |
| `pulumi_access_token` | API_KEY | 0.95 | `not_placeholder_credential` | Pulumi access token |
| `pypi_token` | API_KEY | 0.95 | — | PyPI upload token (pypi- prefix with static base64-encoded p |
| `replicate_api_key` | API_KEY | 0.95 | — | Replicate API key — r8_ prefix followed by exactly 40 alphan |
| `sentry_auth_token` | API_KEY | 0.95 | `not_placeholder_credential` | Sentry auth token |
| `square_oauth_secret` | API_KEY | 0.95 | — | Square OAuth application secret (sq0csp- prefix, 43-char bod |
| `stripe_publishable_key` | API_KEY | 0.95 | `not_placeholder_credential` | Stripe publishable key (less sensitive than secret, but stil |
| `supabase_service_key` | API_KEY | 0.95 | `not_placeholder_credential` | Supabase service role / personal access token |
| `terraform_cloud_token` | API_KEY | 0.95 | `not_placeholder_credential` | Terraform Cloud / HCP Terraform API token |
| `twilio_api_key` | API_KEY | 0.95 | `not_placeholder_credential` | Twilio API key (SK prefix + 32 hex chars) |
| `vercel_api_token` | API_KEY | 0.95 | `not_placeholder_credential` | Vercel API token |
| `xai_api_key` | API_KEY | 0.95 | — | xAI (Grok) API key — xai- prefix followed by 52+ base62 char |
| `authress_service_client_key` | API_KEY | 0.93 | — | Authress service client access key (sc_/ext_/scauth_/authres |
| `facebook_access_token` | API_KEY | 0.93 | — | Facebook/Meta page access token (EAAMxxxx or EAACxxxx prefix |
| `harness_api_key` | API_KEY | 0.92 | — | Harness.io personal (pat.) or service account (sat.) API tok |
| `openshift_user_token` | API_KEY | 0.92 | — | OpenShift user API token (sha256~ prefix, 43 URL-safe base64 |
| `artifactory_api_token` | API_KEY | 0.9 | — | JFrog Artifactory API token (AKC prefix) |
| `azure_ad_client_secret` | API_KEY | 0.9 | — | Azure AD client secret (Q~ pattern with alphanumeric prefix) |
| `connection_string` | API_KEY | 0.9 | `not_placeholder_credential` | Database connection string with protocol prefix |
| `facebook_graph_token` | API_KEY | 0.9 | — | Facebook Graph API access token (EAA prefix, 20-400 alphanum |
| `mailchimp_api_key` | API_KEY | 0.9 | — | Mailchimp API key (32 hex chars + datacenter suffix -usN) |
| `okta_api_token` | API_KEY | 0.9 | — | Okta SSWS API token — starts with '00', 42 chars total, alph |
| `onepassword_service_token` | API_KEY | 0.9 | — | 1Password service account token (ops_ prefix, base64 JSON bo |
| `posthog_api_key` | API_KEY | 0.9 | — | PostHog API key — phc_ (project API key) or phx_ (personal A |
| `render_api_key` | API_KEY | 0.9 | — | Render.com API key (rnd_ prefix). Format documented on rende |
| `grafana_legacy_api_key` | API_KEY | 0.85 | — | Grafana legacy API key (base64-encoded JSON starting with ey |
| `telegram_bot_token` | API_KEY | 0.85 | — | Telegram bot token (numeric bot ID + colon + 35-char alphanu |
| `basicauth_url` | API_KEY | 0.8 | `not_placeholder_credential` | HTTP Basic Auth credentials embedded in URL (user:password@h |
| `generic_api_key` | API_KEY | 0.8 | `not_placeholder_credential` | Generic API key assignment pattern (api_key=... or api-key:  |
| `instagram_legacy_token` | API_KEY | 0.75 | — | Instagram legacy access token (7-char hex user_id . 32-char  |
| `random_password` | OPAQUE_SECRET | 0.6 | `random_password` | Column-name-gated random password: short mixed-class string  |
| `aws_secret_key` | API_KEY | 0.5 | `aws_secret_not_hex` | Potential AWS Secret Key (40 chars base64). Low confidence a |

---

## Part 2: Key-Name Patterns (283 Secret Scanner)

These fire on the **secret-scanner pass**. The scanner parses KV pairs from text,
matches key names against this dictionary, then gates the value by entropy/diversity.

### Definitive tier (166 entries)

| Pattern | Score | Match | Subtype |
|---------|-------|-------|---------|
| `access_key` | 0.95 | substring | API_KEY |
| `access_key_id` | 0.95 | substring | API_KEY |
| `access_secret` | 0.95 | substring | API_KEY |
| `access_token` | 0.95 | substring | API_KEY |
| `admin_password` | 0.95 | substring | OPAQUE_SECRET |
| `aes_key` | 0.9 | substring | PRIVATE_KEY |
| `alibaba_access_key` | 0.95 | substring | API_KEY |
| `alibaba_access_key_secret` | 0.95 | substring | API_KEY |
| `aliyun_access_key` | 0.95 | substring | API_KEY |
| `ansible_vault_password` | 0.95 | substring | OPAQUE_SECRET |
| `api_dev_key` | 0.9 | substring | API_KEY |
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
| `conn_str` | 0.9 | substring | OPAQUE_SECRET |
| `connection_string` | 0.9 | substring | OPAQUE_SECRET |
| `consumer_secret` | 0.95 | substring | API_KEY |
| `cookie_secret` | 0.95 | substring | OPAQUE_SECRET |
| `couchbase_password` | 0.95 | substring | OPAQUE_SECRET |
| `credential` | 0.9 | substring | OPAQUE_SECRET |
| `credentials` | 0.9 | substring | OPAQUE_SECRET |
| `csrf_secret` | 0.95 | substring | OPAQUE_SECRET |
| `database_url` | 0.9 | substring | OPAQUE_SECRET |
| `datadog_app_key` | 0.95 | substring | API_KEY |
| `db_pass` | 0.95 | substring | OPAQUE_SECRET |
| `db_password` | 0.95 | substring | OPAQUE_SECRET |
| `db_pwd` | 0.95 | substring | OPAQUE_SECRET |
| `dd_api_key` | 0.95 | substring | API_KEY |
| `dd_application_key` | 0.95 | substring | API_KEY |
| `decryption_key` | 0.95 | substring | PRIVATE_KEY |
| `digitalocean_token` | 0.95 | substring | API_KEY |
| `discord_token` | 0.95 | substring | API_KEY |
| `discord_webhook` | 0.9 | substring | API_KEY |
| `django_secret_key` | 0.95 | substring | OPAQUE_SECRET |
| `do_pat` | 0.95 | substring | API_KEY |
| `docker_password` | 0.95 | substring | OPAQUE_SECRET |
| `drone_token` | 0.95 | substring | API_KEY |
| `elasticsearch_password` | 0.95 | substring | OPAQUE_SECRET |
| `email_password` | 0.9 | substring | OPAQUE_SECRET |
| `enc_key` | 0.9 | substring | PRIVATE_KEY |
| `encoding_key` | 0.9 | substring | API_KEY |
| `encryption_key` | 0.95 | substring | API_KEY |
| `encryption_secret` | 0.95 | substring | PRIVATE_KEY |
| `es_password` | 0.95 | substring | OPAQUE_SECRET |
| `figma_pat` | 0.95 | substring | API_KEY |
| `figma_token` | 0.95 | substring | API_KEY |
| `flask_secret_key` | 0.95 | substring | OPAQUE_SECRET |
| `ftp_password` | 0.95 | substring | OPAQUE_SECRET |
| `gcp_credentials` | 0.95 | substring | API_KEY |
| `gha_token` | 0.9 | substring | API_KEY |
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
| `id_token` | 0.9 | word_boundary | API_KEY |
| `intercom_token` | 0.95 | substring | API_KEY |
| `jenkins_api_token` | 0.95 | substring | API_KEY |
| `jenkins_token` | 0.95 | substring | API_KEY |
| `jira_token` | 0.95 | substring | API_KEY |
| `jwt_secret` | 0.95 | substring | API_KEY |
| `keystore_password` | 0.95 | substring | PRIVATE_KEY |
| `license_key` | 0.9 | substring | API_KEY |
| `linode_api_key` | 0.95 | substring | API_KEY |
| `linode_token` | 0.95 | substring | API_KEY |
| `mail_pass` | 0.9 | substring | OPAQUE_SECRET |
| `mail_password` | 0.9 | substring | OPAQUE_SECRET |
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
| `oidc_token` | 0.9 | substring | API_KEY |
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
| `product_key` | 0.9 | substring | API_KEY |
| `private_key` | 0.95 | substring | PRIVATE_KEY |
| `pwd` | 0.9 | substring | OPAQUE_SECRET |
| `pypi_token` | 0.95 | substring | API_KEY |
| `rabbitmq_password` | 0.95 | substring | OPAQUE_SECRET |
| `redis_password` | 0.95 | substring | OPAQUE_SECRET |
| `refresh_token` | 0.9 | substring | API_KEY |
| `root_password` | 0.95 | substring | OPAQUE_SECRET |
| `saml_token` | 0.9 | substring | API_KEY |
| `scaleway_key` | 0.95 | substring | API_KEY |
| `scaleway_secret_key` | 0.95 | substring | API_KEY |
| `secret` | 0.9 | word_boundary | OPAQUE_SECRET |
| `secret-key` | 0.95 | substring | API_KEY |
| `secret_access_key` | 0.95 | substring | API_KEY |
| `secret_key` | 0.95 | substring | API_KEY |
| `secretkey` | 0.95 | substring | API_KEY |
| `sendgrid_api_key` | 0.95 | substring | API_KEY |
| `sentry_auth_token` | 0.95 | substring | API_KEY |
| `sentry_org_token` | 0.95 | substring | API_KEY |
| `service_account_key` | 0.95 | substring | API_KEY |
| `session_secret` | 0.95 | substring | OPAQUE_SECRET |
| `shared_secret` | 0.95 | substring | OPAQUE_SECRET |
| `signing_key` | 0.95 | substring | API_KEY |
| `signing_secret` | 0.95 | substring | API_KEY |
| `slack_token` | 0.95 | substring | API_KEY |
| `slack_webhook` | 0.9 | substring | API_KEY |
| `smtp_password` | 0.95 | substring | OPAQUE_SECRET |
| `ssh_key` | 0.95 | substring | PRIVATE_KEY |
| `ssh_passphrase` | 0.95 | substring | PRIVATE_KEY |
| `stripe_key` | 0.95 | substring | API_KEY |
| `stripe_secret` | 0.95 | substring | API_KEY |
| `teamcity_token` | 0.95 | substring | API_KEY |
| `tencent_cloud_secret` | 0.95 | substring | API_KEY |
| `tencentcloud_secretkey` | 0.95 | substring | API_KEY |
| `token_secret` | 0.9 | word_boundary | API_KEY |
| `truststore_password` | 0.95 | substring | PRIVATE_KEY |
| `twilio_auth_token` | 0.95 | substring | API_KEY |
| `vercel_token` | 0.95 | substring | API_KEY |
| `vultr_api_key` | 0.95 | substring | API_KEY |
| `webhook_secret` | 0.95 | substring | API_KEY |
| `zendesk_token` | 0.95 | substring | API_KEY |

### Strong tier (63 entries)

| Pattern | Score | Match | Subtype |
|---------|-------|-------|---------|
| `adafruit_key` | 0.7 | substring | API_KEY |
| `adobe_client_id` | 0.7 | substring | API_KEY |
| `amplitude` | 0.7 | substring | API_KEY |
| `auth` | 0.8 | word_boundary | OPAQUE_SECRET |
| `authorization` | 0.85 | substring | API_KEY |
| `bearer` | 0.85 | substring | API_KEY |
| `braintree` | 0.7 | substring | API_KEY |
| `bugsnag` | 0.7 | substring | API_KEY |
| `ci_token` | 0.8 | word_boundary | API_KEY |
| `client_id` | 0.7 | substring | API_KEY |
| `coinbase_api_key` | 0.7 | substring | API_KEY |
| `deepseek` | 0.7 | substring | API_KEY |
| `deploy_token` | 0.85 | substring | API_KEY |
| `dev_key` | 0.85 | substring | API_KEY |
| `dropbox_api_key` | 0.7 | substring | API_KEY |
| `dropbox_token` | 0.7 | substring | API_KEY |
| `dsn` | 0.85 | word_boundary | OPAQUE_SECRET |
| `elevenlabs` | 0.7 | substring | API_KEY |
| `facebook` | 0.7 | substring | API_KEY |
| `facebook_token` | 0.7 | substring | API_KEY |
| `gemini` | 0.7 | substring | API_KEY |
| `jwt` | 0.8 | word_boundary | API_KEY |
| `klaviyo` | 0.7 | substring | API_KEY |
| `langfuse` | 0.7 | substring | API_KEY |
| `langsmith` | 0.7 | substring | API_KEY |
| `linkedin_client_id` | 0.7 | substring | API_KEY |
| `linkedin_client_secret` | 0.7 | substring | API_KEY |
| `mixpanel` | 0.7 | substring | API_KEY |
| `mongo_password` | 0.85 | substring | OPAQUE_SECRET |
| `mongo_uri` | 0.85 | substring | OPAQUE_SECRET |
| `mongo_url` | 0.85 | substring | OPAQUE_SECRET |
| `mongodb` | 0.7 | substring | OPAQUE_SECRET |
| `nexmo` | 0.7 | substring | API_KEY |
| `nvidia` | 0.7 | substring | API_KEY |
| `opsgenie` | 0.7 | substring | API_KEY |
| `pass` | 0.8 | word_boundary | OPAQUE_SECRET |
| `pg_password` | 0.85 | substring | OPAQUE_SECRET |
| `postgres_uri` | 0.8 | substring | OPAQUE_SECRET |
| `postgresql` | 0.7 | substring | OPAQUE_SECRET |
| `posthog` | 0.7 | substring | API_KEY |
| `psk` | 0.85 | word_boundary | PRIVATE_KEY |
| `razorpay` | 0.7 | substring | API_KEY |
| `redis_url` | 0.85 | substring | OPAQUE_SECRET |
| `replicate` | 0.7 | substring | API_KEY |
| `ringcentral` | 0.7 | substring | API_KEY |
| `salesforce` | 0.7 | substring | API_KEY |
| `session_id` | 0.7 | substring | OPAQUE_SECRET |
| `session_key` | 0.85 | substring | API_KEY |
| `sfdc` | 0.7 | word_boundary | API_KEY |
| `snowflake` | 0.7 | substring | OPAQUE_SECRET |
| `snowflake_account` | 0.75 | substring | OPAQUE_SECRET |
| `snowflake_password` | 0.85 | substring | OPAQUE_SECRET |
| `state_token` | 0.8 | substring | API_KEY |
| `telnyx` | 0.7 | substring | API_KEY |
| `token` | 0.85 | word_boundary | OPAQUE_SECRET |
| `twitter_api_key` | 0.7 | substring | API_KEY |
| `twitter_bearer_token` | 0.7 | substring | API_KEY |
| `twitter_consumer_secret` | 0.7 | substring | API_KEY |
| `twitter_token` | 0.7 | substring | API_KEY |
| `vonage` | 0.7 | substring | API_KEY |
| `wandb` | 0.7 | substring | API_KEY |
| `weights_and_biases` | 0.7 | substring | API_KEY |
| `weightsandbiases` | 0.7 | substring | API_KEY |

### Contextual tier (54 entries)

| Pattern | Score | Match | Subtype |
|---------|-------|-------|---------|
| `algolia_api_key` | 0.65 | substring | API_KEY |
| `asana_token` | 0.65 | substring | API_KEY |
| `beamer_api_key` | 0.6 | substring | API_KEY |
| `bitbucket_token` | 0.65 | substring | API_KEY |
| `bittrex_api_key` | 0.6 | substring | API_KEY |
| `bittrex_secret` | 0.6 | substring | API_KEY |
| `cisco_meraki_api_key` | 0.6 | substring | API_KEY |
| `clickup` | 0.65 | substring | API_KEY |
| `code_verifier` | 0.65 | word_boundary | API_KEY |
| `cohere_api_key` | 0.65 | substring | API_KEY |
| `confluent_api_key` | 0.65 | substring | API_KEY |
| `confluent_secret` | 0.65 | substring | API_KEY |
| `contentful_token` | 0.6 | substring | API_KEY |
| `droneci_token` | 0.6 | substring | API_KEY |
| `dynatrace_token` | 0.65 | substring | API_KEY |
| `etsy_api_key` | 0.6 | substring | API_KEY |
| `fastly_api_key` | 0.6 | substring | API_KEY |
| `finicity_api_key` | 0.6 | substring | API_KEY |
| `finnhub_token` | 0.6 | substring | API_KEY |
| `flickr_token` | 0.6 | substring | API_KEY |
| `freshbooks_token` | 0.65 | substring | API_KEY |
| `gocardless_token` | 0.6 | substring | API_KEY |
| `grok` | 0.65 | word_boundary | API_KEY |
| `hash` | 0.6 | word_boundary | OPAQUE_SECRET |
| `intercom_api_key` | 0.65 | substring | API_KEY |
| `iv` | 0.65 | word_boundary | OPAQUE_SECRET |
| `key` | 0.55 | suffix | OPAQUE_SECRET |
| `kraken_api_key` | 0.6 | substring | API_KEY |
| `kucoin_api_key` | 0.6 | substring | API_KEY |
| `launchdarkly_api_key` | 0.65 | substring | API_KEY |
| `looker_api_key` | 0.65 | substring | API_KEY |
| `mapbox_token` | 0.65 | substring | API_KEY |
| `mattermost_token` | 0.65 | substring | API_KEY |
| `messagebird_api_key` | 0.6 | substring | API_KEY |
| `monday` | 0.65 | word_boundary | API_KEY |
| `nonce` | 0.65 | word_boundary | OPAQUE_SECRET |
| `nytimes_api_key` | 0.6 | substring | API_KEY |
| `plaid_api_key` | 0.65 | substring | API_KEY |
| `plaid_client_id` | 0.65 | substring | API_KEY |
| `plaid_secret` | 0.65 | substring | API_KEY |
| `privateai_api_key` | 0.6 | substring | API_KEY |
| `rapidapi_key` | 0.6 | substring | API_KEY |
| `salt` | 0.6 | word_boundary | OPAQUE_SECRET |
| `segment` | 0.65 | word_boundary | API_KEY |
| `sendbird_token` | 0.6 | substring | API_KEY |
| `snyk_token` | 0.65 | substring | API_KEY |
| `sonar_token` | 0.65 | substring | API_KEY |
| `squarespace_token` | 0.65 | substring | API_KEY |
| `sumologic_access_key` | 0.6 | substring | API_KEY |
| `travisci_token` | 0.6 | substring | API_KEY |
| `twitch_api_token` | 0.65 | substring | API_KEY |
| `xai` | 0.65 | word_boundary | API_KEY |
| `yandex_api_key` | 0.65 | substring | API_KEY |
| `zendesk_api_token` | 0.65 | substring | API_KEY |

---

## Suppression Mechanisms

Several layers suppress false positives:

1. **Placeholder values** — known non-secret values (`YOUR_API_KEY`, `changeme`, etc.)
2. **Placeholder patterns** — regex patterns for template syntax (`${...}`, `{{...}}`)
3. **Stopwords** — global and per-pattern token exclusions
4. **Allowlist patterns** — per-pattern regexes that suppress matches
5. **Anti-indicators** — key/value substrings that suppress secret-scanner findings (`example`, `test`, `mock`)
6. **Config values** — common configuration strings (`true`, `false`, `null`, `none`)
7. **Non-secret compound names** — key suffixes like `_address`, `_type`, `_field` that indicate the key refers to metadata, not a secret
8. **Validators** — post-match functions that reject known false patterns (e.g., `aws_secret_not_hex` rejects all-hex AWS keys)
