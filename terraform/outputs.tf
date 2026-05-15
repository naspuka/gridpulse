# Useful info surfaced after `terraform apply`.

output "server_ipv4" {
  description = "Hetzner CX32 public IPv4 — what DNS A records point at."
  value       = hcloud_server.app.ipv4_address
}

output "server_ipv6" {
  description = "Hetzner CX32 public IPv6."
  value       = hcloud_server.app.ipv6_address
}

output "ssh_command" {
  description = "Drop in a terminal to SSH into the box."
  value       = "ssh ubuntu@${hcloud_server.app.ipv4_address}"
}

output "r2_bucket" {
  description = "R2 bucket name (Iceberg warehouse + backups)."
  value       = cloudflare_r2_bucket.lake.name
}

output "dns_records" {
  description = "DNS records managed by this stack."
  value = {
    apex    = "${var.domain} → ${hcloud_server.app.ipv4_address} (proxied)"
    www     = "www.${var.domain} → ${hcloud_server.app.ipv4_address} (proxied)"
    dagster = "dagster.${var.domain} → ${hcloud_server.app.ipv4_address} (unproxied)"
  }
}
