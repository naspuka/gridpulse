# Hetzner Cloud resources: SSH key, firewall, server.

resource "hcloud_ssh_key" "admin" {
  name       = "gridpulse-admin"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

# Single firewall attached to the server.
# - 22:   SSH from admin_ip_cidrs only (defaults to anywhere — see variables.tf)
# - 80:   HTTP, world (Caddy + Let's Encrypt HTTP-01 challenge)
# - 443:  HTTPS, world (Caddy)
# Outbound: unrestricted by default (Hetzner doesn't block egress).
resource "hcloud_firewall" "web" {
  name = "gridpulse-web"

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.admin_ip_cidrs
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "app" {
  name        = var.server_name
  image       = "ubuntu-24.04"
  server_type = var.server_type
  location    = var.server_location
  ssh_keys    = [hcloud_ssh_key.admin.id]
  user_data = templatefile("${path.module}/cloud-init.yml.tpl", {
    ssh_pubkey = trimspace(file(pathexpand(var.ssh_public_key_path)))
  })

  firewall_ids = [hcloud_firewall.web.id]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }

  labels = {
    project     = "gridpulse"
    environment = "production"
    managed_by  = "terraform"
  }
}
