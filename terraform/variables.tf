# Variables — populated from terraform.tfvars (gitignored).
# See terraform.tfvars.example for the template.

# ---- Credentials ----------------------------------------------------------

variable "hcloud_token" {
  description = "Hetzner Cloud API token (Read & Write)."
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token with Zone:DNS:Edit on gridpulse.uk and Account:Workers R2 Storage:Edit."
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID that owns the gridpulse.uk zone."
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for gridpulse.uk."
  type        = string
}

# ---- Box config -----------------------------------------------------------

variable "server_name" {
  description = "Hetzner server name."
  type        = string
  default     = "gridpulse-app"
}

variable "server_type" {
  description = <<-EOT
    Hetzner instance type. As of 2026, the Intel CX series has been retired
    in some configurations; CAX21 (ARM Ampere) is the closest equivalent and
    a slight upgrade: 4 vCPU / 8 GB RAM / 80 GB SSD (~€6.49/mo).
    Our Docker images are multi-arch so ARM is safe.
  EOT
  type        = string
  default     = "cax21"
}

variable "server_location" {
  description = "Hetzner DC. nbg1=Nuremberg, fsn1=Falkenstein, hel1=Helsinki."
  type        = string
  default     = "nbg1"
}

variable "ssh_public_key_path" {
  description = "Absolute path to the SSH public key uploaded to Hetzner and authorised for the ubuntu user."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "admin_ip_cidrs" {
  description = <<-EOT
    CIDRs allowed to SSH (:22) to the box. Defaults to anywhere (0.0.0.0/0)
    because UK home IPs are typically dynamic; pair with key-only SSH
    (no passwords) and fail2ban configured by cloud-init.
    Lock down to your home/office CIDR if you have a static IP.
  EOT
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

# ---- Domain / R2 ---------------------------------------------------------

variable "domain" {
  description = "Root domain. DNS records hang off this."
  type        = string
  default     = "gridpulse.uk"
}

variable "r2_bucket_name" {
  description = "Cloudflare R2 bucket for the Iceberg lakehouse + backups."
  type        = string
  default     = "gridpulse-lake"
}

variable "r2_location" {
  description = "R2 bucket location hint. WEUR=Western Europe."
  type        = string
  default     = "WEUR"
}
