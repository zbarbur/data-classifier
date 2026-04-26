use std::sync::OnceLock;

use fancy_regex::Regex;

use super::{url_decode, KVPair};

/// JDBC: `jdbc:mysql://host?password=xxx` or `jdbc:mysql://host;password=xxx`
static JDBC_RE: OnceLock<Regex> = OnceLock::new();
/// ODBC: `Driver={...};Password=xxx` or `DSN=...;Pwd=xxx`
static ODBC_RE: OnceLock<Regex> = OnceLock::new();
/// URI userinfo: `scheme://user:password@host` (postgresql, mysql, mongodb, etc.)
static URI_USERINFO_RE: OnceLock<Regex> = OnceLock::new();
/// Redis URI: `redis://:password@host` or `redis://user:password@host`
static REDIS_URI_RE: OnceLock<Regex> = OnceLock::new();
/// Generic KV password in semicolon-delimited strings
static CONNSTR_KV_RE: OnceLock<Regex> = OnceLock::new();

fn jdbc_regex() -> &'static Regex {
    JDBC_RE.get_or_init(|| {
        Regex::new(r"(?i)jdbc:[a-z]+://[^?;]*[?;].*?(?:password|pwd)\s*=\s*([^&;]+)")
            .expect("JDBC_RE must compile")
    })
}

fn odbc_regex() -> &'static Regex {
    ODBC_RE.get_or_init(|| {
        Regex::new(r"(?i)(?:Driver|DSN)\s*=.*?(?:Pwd|Password)\s*=\s*([^;]+)")
            .expect("ODBC_RE must compile")
    })
}

fn uri_userinfo_regex() -> &'static Regex {
    URI_USERINFO_RE.get_or_init(|| {
        Regex::new(
            r"(?i)(?:postgresql|postgres|mysql|mariadb|mongodb(?:\+srv)?|amqp|rabbitmq|mssql)://([^:@]+):(.+)@[A-Za-z0-9._\-]+",
        )
        .expect("URI_USERINFO_RE must compile")
    })
}

fn redis_uri_regex() -> &'static Regex {
    REDIS_URI_RE.get_or_init(|| {
        Regex::new(r"(?i)redis://(?::(.+)@|([^:@]+):(.+)@)[A-Za-z0-9._\-]+")
            .expect("REDIS_URI_RE must compile")
    })
}

fn connstr_kv_regex() -> &'static Regex {
    CONNSTR_KV_RE.get_or_init(|| {
        Regex::new(r"(?i)(?:^|;)\s*(?:password|pwd|passwd)\s*=\s*([^;]+)")
            .expect("CONNSTR_KV_RE must compile")
    })
}

/// Extract credential values from database / service connection strings.
///
/// Covers:
/// - JDBC URLs: `jdbc:mysql://host?password=secret`
/// - ODBC/DSN strings: `Driver={SQL Server};Password=secret;`
/// - URI userinfo: `postgresql://user:secret@host/db`
/// - Redis: `redis://:secret@host` or `redis://user:secret@host`
/// - Generic semicolon-delimited: `Server=x;Password=secret;`
///
/// Passwords are URL-decoded. The `key` field indicates the context
/// (`"password"`, `"jdbc_password"`, `"odbc_password"`, `"redis_password"`).
/// Offsets point to the value content in the original text.
pub fn parse_connection_str_with_spans(text: &str) -> Vec<KVPair> {
    let mut results: Vec<KVPair> = Vec::new();

    // 1. JDBC
    if let Ok(Some(caps)) = jdbc_regex().captures(text) {
        if let Some(g) = caps.get(1) {
            let raw = g.as_str().trim().to_string();
            let decoded = url_decode(&raw);
            if !decoded.is_empty() {
                results.push(KVPair {
                    key: "jdbc_password".to_string(),
                    value: decoded,
                    value_start: g.start(),
                    value_end: g.end(),
                });
                return results;
            }
        }
    }

    // 2. ODBC / DSN
    if let Ok(Some(caps)) = odbc_regex().captures(text) {
        if let Some(g) = caps.get(1) {
            let raw = g.as_str().trim().to_string();
            let decoded = url_decode(&raw);
            if !decoded.is_empty() {
                results.push(KVPair {
                    key: "odbc_password".to_string(),
                    value: decoded,
                    value_start: g.start(),
                    value_end: g.end(),
                });
                return results;
            }
        }
    }

    // 3. Redis URI (before generic URI — more specific pattern)
    if let Ok(Some(caps)) = redis_uri_regex().captures(text) {
        // group 1 = password-only (`:pass@`), group 3 = `user:pass@` style
        let group = caps.get(1).or_else(|| caps.get(3));
        if let Some(g) = group {
            let raw = g.as_str().to_string();
            let decoded = url_decode(&raw);
            if !decoded.is_empty() {
                results.push(KVPair {
                    key: "redis_password".to_string(),
                    value: decoded,
                    value_start: g.start(),
                    value_end: g.end(),
                });
                return results;
            }
        }
    }

    // 4. Generic URI userinfo: scheme://user:password@host
    if let Ok(Some(caps)) = uri_userinfo_regex().captures(text) {
        if let Some(g) = caps.get(2) {
            let raw = g.as_str().to_string();
            let decoded = url_decode(&raw);
            if !decoded.is_empty() {
                results.push(KVPair {
                    key: "password".to_string(),
                    value: decoded,
                    value_start: g.start(),
                    value_end: g.end(),
                });
                return results;
            }
        }
    }

    // 5. Generic semicolon-delimited password=xxx
    if let Ok(Some(caps)) = connstr_kv_regex().captures(text) {
        if let Some(g) = caps.get(1) {
            let raw = g.as_str().trim().to_string();
            let decoded = url_decode(&raw);
            // Only fire when there's clear connection-string structure
            if !decoded.is_empty() && text.contains(';') && text.contains('=') {
                results.push(KVPair {
                    key: "password".to_string(),
                    value: decoded,
                    value_start: g.start(),
                    value_end: g.end(),
                });
            }
        }
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_conn_uri_userinfo() {
        let text = "postgresql://admin:s3cret@db.host:5432/mydb";
        let pairs = parse_connection_str_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "s3cret"),
            "expected s3cret in {:?}",
            pairs
        );
    }

    #[test]
    fn test_conn_mysql() {
        let text = "mysql://root:MyP@ss!@db.local/app";
        let pairs = parse_connection_str_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "MyP@ss!"),
            "expected MyP@ss! in {:?}",
            pairs
        );
    }

    #[test]
    fn test_conn_redis_password_only() {
        let text = "redis://:mypassword@redis.host:6379";
        let pairs = parse_connection_str_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "mypassword"),
            "expected mypassword in {:?}",
            pairs
        );
    }

    #[test]
    fn test_conn_redis_with_user() {
        let text = "redis://default:redispassword@cache.example.com:6379";
        let pairs = parse_connection_str_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "redispassword"),
            "expected redispassword in {:?}",
            pairs
        );
    }

    #[test]
    fn test_conn_odbc() {
        let text = "Driver={SQL Server};Server=myserver;Password=P@ssw0rd;Database=mydb;";
        let pairs = parse_connection_str_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "P@ssw0rd"),
            "expected P@ssw0rd in {:?}",
            pairs
        );
    }

    #[test]
    fn test_conn_jdbc() {
        let text = "jdbc:mysql://db.host:3306/mydb?user=admin&password=secretpass";
        let pairs = parse_connection_str_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "secretpass"),
            "expected secretpass in {:?}",
            pairs
        );
    }

    #[test]
    fn test_conn_url_encoded() {
        let text = "mysql://user:p%40ss@host/db";
        let pairs = parse_connection_str_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "p@ss"),
            "expected p@ss (url-decoded) in {:?}",
            pairs
        );
    }

    #[test]
    fn test_conn_semicolon_delimited() {
        let text = "Server=tcp:myserver.database.windows.net,1433;Password=MyPass123;";
        let pairs = parse_connection_str_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "MyPass123"),
            "expected MyPass123 in {:?}",
            pairs
        );
    }

    #[test]
    fn test_conn_empty() {
        let pairs = parse_connection_str_with_spans("");
        assert!(pairs.is_empty());
    }

    #[test]
    fn test_conn_no_password() {
        let text = "https://example.com/path?foo=bar";
        let pairs = parse_connection_str_with_spans(text);
        // No password-like pattern should fire
        assert!(
            !pairs.iter().any(|p| p.key == "password"),
            "should not detect password in plain URL: {:?}",
            pairs
        );
    }
}
