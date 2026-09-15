# The key is looked up, never created: it must already be in the console
# before `apply`. A wrong name fails at `plan`, before anything is billed.
data "digitalocean_ssh_key" "operator" {
  name = var.ssh_key_name
}

resource "digitalocean_droplet" "gpu" {
  name   = var.name
  region = var.region
  size   = var.size
  image  = var.image

  ssh_keys = [data.digitalocean_ssh_key.operator.id]

  # First-boot script, rendered from cloud-init.yaml with the image tag baked
  # in. Changing it forces a new droplet — correct here, because a droplet is
  # a run's disposable host and never lives past the run.
  user_data = templatefile("${path.module}/cloud-init.yaml", {
    vllm_image = var.vllm_image
  })

  # DigitalOcean's own agents are not needed for a machine that lives ~2 h and
  # is watched over SSH; fewer moving parts on the boot the clock is counting.
  monitoring    = false
  droplet_agent = false
  backups       = false

  tags = ["i-serve", var.name]
}
