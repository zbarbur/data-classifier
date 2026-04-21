# Credential pattern sources — per-entry attribution

> **Scope:** per-entry attribution table for every net-new credential key-name pattern added to `data_classifier/patterns/secret_key_names.json` by the Sprint 10 Kingfisher/gitleaks/Nosey Parker harvest.

> **Companion docs:** `docs/process/LICENSE_AUDIT.md` records the upstream licenses and pinned SHAs; `scripts/ingest_credential_patterns.py` is the script that generated this table.

## Upstream sources (pinned commits)

| Source | License | Pinned SHA | URL |
|---|---|---|---|
| MongoDB Kingfisher (`kingfisher`) | Apache-2.0 | `be0ce3bae0b14240bb2781ab6ee2b5c65e02144b` | <https://github.com/mongodb/kingfisher> |
| gitleaks (`gitleaks`) | MIT | `8863af47d64c3681422523e36837957c74d4af4b` | <https://github.com/gitleaks/gitleaks> |
| Praetorian Nosey Parker (`noseyparker`) | Apache-2.0 | `2e6e7f36ce36619852532bbe698d8cb7a26d2da7` | <https://github.com/praetorian-inc/noseyparker> |

## Excluded upstream sources (license-incompatible)

| Source | License | Reason |
|---|---|---|
| trufflehog | AGPL-3.0 | Copyleft incompatible with MIT downstream. Consulted for gap-identification only; no regex or code was copied. |
| Semgrep Rules | SRL v1.0 | Non-OSI, restricts redistribution. |
| Atlassian SAST | LGPL-2.1 | LGPL linking clauses incompatible with static-library downstream use. |

## Per-entry attribution

| pattern | upstream | license | upstream rule id | our score | our tier | our subtype | category | attribution date |
|---|---|---|---|---|---|---|---|---|
| `datadog_app_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.datadog.3` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `dd_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.datadog.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `dd_application_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.datadog.3` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `pagerduty_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.pagerduty.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `pd_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.pagerduty.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `okta_api_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.okta.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `okta_client_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.okta.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `auth0_client_secret` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.auth0.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `auth0_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.auth0.3` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `notion_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.notion.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `notion_integration_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.notion.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `figma_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.figma.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `figma_pat` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.figma.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `jira_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.jira.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `confluence_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.jira.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `atlassian_token` | Praetorian Nosey Parker | Apache-2.0 | `np.atlassian.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `hubspot_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.hubspot.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `hubspot_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.hubspot.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `intercom_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.intercom.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `zendesk_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.zendesk.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `sentry_auth_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.sentry.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `sentry_org_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.sentry.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `cloudflare_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.cloudflare.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `cloudflare_api_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.cloudflare.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `vercel_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.vercel.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `netlify_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.netlify.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `mailgun_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.mailgun.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `mailgun_signing_key` | gitleaks | MIT | `gitleaks.mailgun-signing-key` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `discord_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.discord.2` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `discord_webhook` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.discord.1` | 0.9 | definitive | API_KEY | saas | 2026-04-21 |
| `newrelic_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.newrelic.1` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `newrelic_license_key` | Praetorian Nosey Parker | Apache-2.0 | `np.newrelic.3` | 0.95 | definitive | API_KEY | saas | 2026-04-21 |
| `digitalocean_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.digitalocean.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `do_pat` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.digitalocean.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `linode_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.linode.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `linode_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.linode.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `vultr_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.vultr.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `scaleway_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.scaleway.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `scaleway_secret_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.scaleway.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `ibm_cloud_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.ibm.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `ibmcloud_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.ibm.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `oci_api_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.oracle.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `oracle_cloud_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.oracle.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `alibaba_access_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.alibabacloud.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `aliyun_access_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.alibabacloud.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `alibaba_access_key_secret` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.alibabacloud.2` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `tencent_cloud_secret` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.tencent.1` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `tencentcloud_secretkey` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.tencent.2` | 0.95 | definitive | API_KEY | cloud | 2026-04-21 |
| `ci_token` | gitleaks | MIT | `gitleaks.gitlab-cicd-job-token` | 0.8 | strong | API_KEY | cicd | 2026-04-21 |
| `deploy_token` | gitleaks | MIT | `gitleaks.gitlab-deploy-token` | 0.85 | strong | API_KEY | cicd | 2026-04-21 |
| `github_actions_token` | gitleaks | MIT | `gitleaks.github-fine-grained-pat` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `gha_token` | gitleaks | MIT | `gitleaks.github-pat` | 0.9 | definitive | API_KEY | cicd | 2026-04-21 |
| `gitlab_ci_token` | gitleaks | MIT | `gitleaks.gitlab-cicd-job-token` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `gitlab_runner_token` | gitleaks | MIT | `gitleaks.gitlab-runner-authentication-token` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `gitlab_deploy_token` | gitleaks | MIT | `gitleaks.gitlab-deploy-token` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `jenkins_token` | Praetorian Nosey Parker | Apache-2.0 | `np.jenkins.1` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `jenkins_api_token` | Praetorian Nosey Parker | Apache-2.0 | `np.jenkins.1` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `circleci_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.circleci.1` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `buildkite_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.buildkite.1` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `drone_token` | gitleaks | MIT | `gitleaks.droneci-access-token` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `teamcity_token` | Praetorian Nosey Parker | Apache-2.0 | `np.teamcity.1` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `artifactory_token` | gitleaks | MIT | `gitleaks.artifactory-api-key` | 0.95 | definitive | API_KEY | cicd | 2026-04-21 |
| `elasticsearch_password` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.elastic.1` | 0.95 | definitive | OPAQUE_SECRET | database | 2026-04-21 |
| `es_password` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.elastic.1` | 0.95 | definitive | OPAQUE_SECRET | database | 2026-04-21 |
| `mssql_password` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.mssql.1` | 0.95 | definitive | OPAQUE_SECRET | database | 2026-04-21 |
| `mariadb_password` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.mariadb.1` | 0.95 | definitive | OPAQUE_SECRET | database | 2026-04-21 |
| `neo4j_password` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.neo4j.1` | 0.95 | definitive | OPAQUE_SECRET | database | 2026-04-21 |
| `rabbitmq_password` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.rabbitmq.1` | 0.95 | definitive | OPAQUE_SECRET | database | 2026-04-21 |
| `couchbase_password` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.couchbase.1` | 0.95 | definitive | OPAQUE_SECRET | database | 2026-04-21 |
| `clickhouse_password` | gitleaks | MIT | `gitleaks.clickhouse-cloud-api-secret-key` | 0.95 | definitive | OPAQUE_SECRET | database | 2026-04-21 |
| `id_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.generic.1` | 0.9 | definitive | API_KEY | oauth | 2026-04-21 |
| `token_secret` | gitleaks | MIT | `gitleaks.twitter-access-secret` | 0.9 | definitive | API_KEY | oauth | 2026-04-21 |
| `saml_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.generic.2` | 0.9 | definitive | API_KEY | oauth | 2026-04-21 |
| `oidc_token` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.generic.3` | 0.9 | definitive | API_KEY | oauth | 2026-04-21 |
| `code_verifier` | Praetorian Nosey Parker | Apache-2.0 | `np.generic.1` | 0.65 | contextual | API_KEY | oauth | 2026-04-21 |
| `state_token` | Praetorian Nosey Parker | Apache-2.0 | `np.generic.2` | 0.8 | strong | API_KEY | oauth | 2026-04-21 |
| `consumer_secret` | gitleaks | MIT | `gitleaks.twitter-api-secret` | 0.95 | definitive | API_KEY | oauth | 2026-04-21 |
| `admin_password` | Praetorian Nosey Parker | Apache-2.0 | `np.generic.1` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `root_password` | Praetorian Nosey Parker | Apache-2.0 | `np.generic.2` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `app_password` | Praetorian Nosey Parker | Apache-2.0 | `np.generic.3` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `session_secret` | Praetorian Nosey Parker | Apache-2.0 | `np.django.1` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `cookie_secret` | Praetorian Nosey Parker | Apache-2.0 | `np.django.1` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `csrf_secret` | Praetorian Nosey Parker | Apache-2.0 | `np.django.1` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `aes_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.generic.4` | 0.9 | definitive | PRIVATE_KEY | pwd_crypto | 2026-04-21 |
| `iv` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.generic.5` | 0.65 | contextual | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `django_secret_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.django.1` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `flask_secret_key` | MongoDB Kingfisher | Apache-2.0 | `kingfisher.generic.6` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `smtp_password` | gitleaks | MIT | `gitleaks.curl-auth-user` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `ftp_password` | gitleaks | MIT | `gitleaks.curl-auth-user` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |
| `ansible_vault_password` | gitleaks | MIT | `gitleaks.hashicorp-tf-password` | 0.95 | definitive | OPAQUE_SECRET | pwd_crypto | 2026-04-21 |

_Regenerated by `python3 scripts/ingest_credential_patterns.py`. Manual edits will be overwritten on next run._
