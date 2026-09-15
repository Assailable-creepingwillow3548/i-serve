output "ipv4_address" {
  description = "Public address; SSH as root with the registered key."
  value       = digitalocean_droplet.gpu.ipv4_address
}

output "ssh" {
  description = "The login line, copy-paste ready."
  value       = "ssh root@${digitalocean_droplet.gpu.ipv4_address}"
}

output "price_hourly" {
  description = <<-EOT
    The hourly price the API reports for this droplet. $1.99/h is the figure
    under the AMD credits (read from the console at activation); $2.59/h is the
    same card on a paid DigitalOcean account. A figure other than the one the
    run was priced at means a different contract or plan, and the run stops
    there.
  EOT
  value       = digitalocean_droplet.gpu.price_hourly
}

output "size_and_region" {
  description = "What was actually created — read back once, against the sheet."
  value       = "${digitalocean_droplet.gpu.size} in ${digitalocean_droplet.gpu.region}"
}
