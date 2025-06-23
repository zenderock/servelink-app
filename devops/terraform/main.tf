terraform {
  required_providers {
    hcloud = { source = "hetznercloud/hcloud" }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

resource "hcloud_ssh_key" "deploy" {
  name       = "devpush-deploy"
  public_key = file("~/.ssh/id_rsa.pub")
}

resource "hcloud_firewall" "web" {
  name = "devpush-web"
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = ["0.0.0.0/0"]
  }
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = ["0.0.0.0/0"]
  }
  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "443"
    source_ips  = ["0.0.0.0/0"]
  }
}

resource "hcloud_server" "devpush" {
  name         = "devpush-prod-us1"
  server_type  = "cpx31"
  image        = "ubuntu-22.04"
  location     = "hil"
  ssh_keys     = [hcloud_ssh_key.deploy.id]
  firewall_ids = [hcloud_firewall.web.id]
  backups      = true
}

variable "hcloud_token" { type = string }

output "server_ip" {
  value = hcloud_server.devpush.ipv4_address
}

output "server_id" {
  value = hcloud_server.devpush.id
}