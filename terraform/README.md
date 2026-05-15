# Terraform — GridPulse infrastructure

Provisions:
- 1× Hetzner CX32 in `nbg1`, Ubuntu 24.04, Docker pre-installed via cloud-init
- Hetzner firewall (22 admin-only or world, 80/443 world)
- Cloudflare DNS: apex + www (proxied), `dagster.` (unproxied)
- Cloudflare R2 bucket `gridpulse-lake` (Iceberg + backups)

## Prerequisites

- `terraform` ≥ 1.6 on PATH (`brew install hashicorp/tap/terraform`)
- SSH keypair at `~/.ssh/id_ed25519` (override path via `ssh_public_key_path`)
- Cloudflare API token + account ID + zone ID
- Hetzner Cloud API token (Read & Write)
- Cloudflare nameservers active for the domain (check the Cloudflare overview)

## Initial setup

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars and paste your tokens + IDs.
chmod 600 terraform.tfvars

terraform init
terraform plan -out plan.bin
terraform apply plan.bin
```

`terraform apply` typically completes in ~60 seconds:
- 30 s for Hetzner to provision the VM
- 5–10 s for Cloudflare DNS/R2

Once it finishes, `terraform output` shows the public IP, SSH command, and a summary of DNS records.

## After applying

1. Wait for cloud-init to finish (~60 s): `ssh ubuntu@<ip> 'cloud-init status --wait'`.
2. **Run the post-deploy script** to install Docker, ufw, fail2ban, etc:
   ```bash
   make post-deploy IP=<server-ip>
   # or directly: bash terraform/post-deploy.sh <server-ip>
   ```
   This is decoupled from cloud-init so it's debuggable and re-runnable. The
   script is idempotent — safe to run again if it fails halfway.
3. Create R2 S3-compatible access keys via the Cloudflare dashboard
   (R2 → Manage R2 API Tokens → "Object Read & Write" scoped to `gridpulse-lake`).
   Save them in your password manager — they're shown only once.
4. Create `/etc/gridpulse/.env` on the box with the prod secrets (Phase 1D).

## Hetzner gotchas we hit (so you don't)

- **`users: - default` is silently overridden** by Hetzner's image
  (`/etc/cloud/cloud.cfg.d/90-hetznercloud.cfg` resets the user list to
  `[root]`). We define the `ubuntu` user fully in `cloud-init.yml.tpl` and
  inject the SSH public key via `templatefile()`.
- **Cloud-init YAML parse errors are silent.** A heredoc that contains
  unescaped `::` (e.g. `Unattended-Upgrade::Automatic-Reboot`) breaks YAML;
  cloud-init aborts user-data processing without an obvious error. Use
  `write_files:` for any non-trivial file content, never inline heredocs.
- **`cx32` server type is gone.** The closest 2026 equivalent is `cax21`
  (ARM Ampere, 4 vCPU / 8 GB / 80 GB, ~€6.49/mo). Our Docker base images
  are multi-arch so ARM is a no-op for the app.
- **Always validate cloud-init YAML before apply:**
  `python3 -c "import yaml; yaml.safe_load(open('terraform/cloud-init.yml.tpl'))"`

## State

State file is **local** (`terraform.tfstate`), gitignored. A nightly backup
script ships it to R2 (added in Phase 6 alongside Postgres backups). To move
to remote state on R2's S3 API, add a `backend "s3"` block to `main.tf` —
not worth the setup at this scale (solo dev, one box).

## Destroying

```bash
terraform destroy
```

Brings everything down. R2 bucket must be empty first (delete contents
manually if you've already started archiving data).

## Changing the admin SSH CIDR

Default: SSH is open to the world (UK home IPs are dynamic). To restrict:

```hcl
# terraform.tfvars
admin_ip_cidrs = ["203.0.113.42/32"]   # your office IP
```

Pair with key-only SSH (`PasswordAuthentication no` is already set by
cloud-init) and fail2ban for defense in depth.
