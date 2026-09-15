variable "api_endpoint" {
  description = <<-EOT
    Base URL of the API. The AMD Developer Cloud is DigitalOcean GPU Droplets
    behind AMD's own host: the console at amd.digitalocean.com, the API at
    api-amd.digitalocean.com. A token from that console is valid only there;
    pointing it at api.digitalocean.com (a paid DigitalOcean account, $2.59/h
    for the same card) is a different contract, and this default keeps the
    credits' one.
  EOT
  type        = string
  default     = "https://api-amd.digitalocean.com"
}

variable "region" {
  description = <<-EOT
    Datacenter slug. ATL1 (Atlanta) is the only region DigitalOcean's
    regional-availability table marks for the MI300X (read 2026-09-08), and the
    one AMD's own tutorials name.
  EOT
  type        = string
  default     = "atl1"
}

variable "size" {
  description = <<-EOT
    Droplet plan slug: one MI300X, 192 GB HBM3, 20 vCPU, 240 GiB RAM, 720 GiB
    disk. Under the AMD front door the slug carries a `-devcloud` suffix; on
    DigitalOcean proper the same plan is `gpu-mi300x1-192gb`. UNVERIFIED against
    the API until a token exists: confirm on the run morning with
    `doctl compute size list --api-url <api_endpoint>` before `apply`.
    The 8-card plan (`gpu-mi300x8-1536gb`, $15.92/h under the credits) answers a
    question run 1 does not ask (see README.md here).
  EOT
  type        = string
  default     = "gpu-mi300x1-192gb-devcloud"
}

variable "image" {
  description = <<-EOT
    Image slug. The run wants the *Vanilla ROCm* image — Ubuntu with ROCm and
    Docker and nothing running — not a Quick Start image, which boots with a
    container named `rocm` already serving AMD's own vLLM build. On DigitalOcean
    proper that image is `gpu-amd-base` (ROCm 7.14, amdgpu-dkms 6.19.14, read
    2026-09-08). UNVERIFIED under the AMD front door: confirm with
    `doctl compute image list --public --api-url <api_endpoint>` and set this
    variable to the slug the console's "Vanilla ROCm" maps to.
  EOT
  type        = string
  default     = "gpu-amd-base"
}

variable "ssh_key_name" {
  description = <<-EOT
    Name of an SSH key ALREADY registered in the console. The module looks it
    up and never uploads one: a droplet created without a key has no way in,
    and registration is a console step this module cannot do for you.
  EOT
  type        = string
}

variable "name" {
  description = "Droplet name; also the hostname the run's logs will carry."
  type        = string
  default     = "mi300x-run-1"
}

variable "vllm_image" {
  description = <<-EOT
    The vLLM image cloud-init pre-pulls on first boot, so the ~11 GB download
    runs while the operator is still on the way in over SSH. Pinned to the tag
    runs 1–3 used; `docs/SLO.md` and the sheets are calibrated against it.
  EOT
  type        = string
  default     = "vllm/vllm-openai-rocm:v0.27.1"
}
