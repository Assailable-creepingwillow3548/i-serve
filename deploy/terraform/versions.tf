# Terraform for the one GPU node this repository runs on: a single MI300X
# droplet under the AMD Developer Cloud front door of DigitalOcean.
#
# The provider is DigitalOcean's own. The AMD front door is the same API at a
# different host, so the only AMD-specific line in this module is the
# `api_endpoint` below; everything else is a plain DigitalOcean droplet.

terraform {
  required_version = ">= 1.7"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.100" # 2.100.0 released 2026-08-18; `~>` allows 2.100.x only
    }
  }
}

provider "digitalocean" {
  # No `token` argument on purpose: the provider reads DIGITALOCEAN_TOKEN from
  # the environment, so the token never lands in a file this repository tracks.
  api_endpoint = var.api_endpoint
}
