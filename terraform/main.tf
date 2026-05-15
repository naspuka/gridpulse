# GridPulse infrastructure.
#
# Two providers: Hetzner Cloud (the VM) and Cloudflare (DNS + R2 bucket).
# Both pinned to a known-good major to avoid drift surprises.
#
# State backend: local file, gitignored. A small script (added later in
# Phase 6 alongside backups) ships the state file to R2 nightly. Remote
# state via R2's S3 API is V2 work — solo dev, one box, not worth the
# yak-shaving yet. See docs/infra-design.md.

terraform {
  required_version = ">= 1.6, < 2.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.48"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.50"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
