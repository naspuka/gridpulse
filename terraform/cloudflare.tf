# Cloudflare resources: DNS records + R2 bucket.

# Apex — proxied through Cloudflare so we get edge cache, DDoS, WAF.
resource "cloudflare_record" "apex" {
  zone_id = var.cloudflare_zone_id
  name    = "@"
  type    = "A"
  content = hcloud_server.app.ipv4_address
  proxied = true
  ttl     = 1 # auto when proxied
  comment = "Managed by terraform — gridpulse production"
}

resource "cloudflare_record" "apex_aaaa" {
  zone_id = var.cloudflare_zone_id
  name    = "@"
  type    = "AAAA"
  content = hcloud_server.app.ipv6_address
  proxied = true
  ttl     = 1
  comment = "Managed by terraform — gridpulse production"
}

resource "cloudflare_record" "www" {
  zone_id = var.cloudflare_zone_id
  name    = "www"
  type    = "A"
  content = hcloud_server.app.ipv4_address
  proxied = true
  ttl     = 1
  comment = "Managed by terraform — gridpulse production"
}

# Dagster admin — NOT proxied. Two reasons:
#   1. Caddy needs to complete ACME HTTP-01 challenge directly (no Cloudflare in the way)
#   2. Admin traffic shouldn't traverse the public edge for no benefit
# Auth is via Caddy basic_auth, set in the prod Caddyfile (Phase 1D).
resource "cloudflare_record" "dagster" {
  zone_id = var.cloudflare_zone_id
  name    = "dagster"
  type    = "A"
  content = hcloud_server.app.ipv4_address
  proxied = false
  ttl     = 300
  comment = "Managed by terraform — Dagster admin UI (basic-auth)"
}

# R2 bucket — Iceberg lakehouse warehouse + nightly Postgres backups.
resource "cloudflare_r2_bucket" "lake" {
  account_id = var.cloudflare_account_id
  name       = var.r2_bucket_name
  location   = var.r2_location
}

# Note: R2 S3-compatible access keys for application use (the values that go
# into R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY in .env) are NOT provisioned via
# Terraform. Cloudflare exposes them via the dashboard:
#   R2 → Manage R2 API Tokens → Create API token → "Object Read & Write" → bucket scope
# Save once into your password manager; the secret is shown only at creation time.
