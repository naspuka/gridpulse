#cloud-config
# Minimal cloud-init — single job: get the box reachable as `ubuntu` over SSH.
#
# Everything else (Docker, ufw, fail2ban, /opt/gridpulse) is installed via
# terraform/post-deploy.sh after the box is up. That keeps "box boots" and
# "box has apps" as separate, debuggable steps.
#
# Why explicit `name: ubuntu` rather than `- default`:
#   Hetzner's Ubuntu 24.04 image ships with a /etc/cloud/cloud.cfg.d/* that
#   overrides cloud-init's `users:` list to just [root]. Using `- default` is
#   silently no-opped. We define the ubuntu user fully here and Terraform
#   injects the SSH public key via templatefile().

users:
  - name: ubuntu
    gecos: GridPulse Admin
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    groups: [sudo]
    lock_passwd: true
    ssh_authorized_keys:
      - ${ssh_pubkey}

package_update: true
packages:
  - ca-certificates
  - curl

final_message: "gridpulse box ready — uptime $UPTIME"
