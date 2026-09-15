# GPU node

One droplet, one MI300X, created and destroyed around a benchmark run. The
provider is DigitalOcean's, because the AMD Developer Cloud *is* DigitalOcean
GPU Droplets behind AMD's own console and API host — the one AMD-specific line
in the module is the `api_endpoint`, and a token issued by that console is valid
only against it.

| File | What it holds |
|---|---|
| `versions.tf` | Provider pin (`digitalocean/digitalocean ~> 2.100`) and the endpoint override |
| `variables.tf` | Region, plan, image, key name, droplet name, vLLM image tag — each with the source of its default and whether it is verified |
| `main.tf` | The SSH-key lookup and the droplet |
| `cloud-init.yaml` | First boot: the run's directories and the vLLM image pull, so the ~11 GB download runs during the boot instead of on the clock |
| `outputs.tf` | Address, login line, and the hourly price to read back against the one the run was priced at |

## Run it

    export DIGITALOCEAN_TOKEN=...          # from the AMD Developer Cloud console
    cd deploy/terraform
    terraform init
    terraform plan -var ssh_key_name=<key name in the console>
    terraform apply -var ssh_key_name=<key name in the console>
    ssh root@$(terraform output -raw ipv4_address)
    cloud-init status --wait               # on the droplet: blocks until the image is pulled

and when the run's results are copied off:

    terraform destroy -var ssh_key_name=<key name in the console>

Three facts set the shape of this, and two of them are not visible from the
repository:

- **Destroy, never stop.** A powered-off GPU droplet keeps its disk, CPU, RAM and
  address reserved and is billed per second until destroyed — AMD's own guide
  says so and DigitalOcean's billing page agrees. `destroy` is the only exit,
  and everything a run produces is copied off before it.
- **The plan and image slugs are read from the API before the first `apply`.**
  Under the AMD front door the single-card plan is reported as
  `gpu-mi300x1-192gb-devcloud` (a third-party write-up, 2025) and the image
  DigitalOcean calls `gpu-amd-base` is the ROCm base image on its own accounts;
  neither has been checked against `api-amd.digitalocean.com` from this
  repository, because that needs a token and the token comes with the credits.
  On the day, before `apply`:

      doctl compute size  list --api-url https://api-amd.digitalocean.com
      doctl compute image list --public --api-url https://api-amd.digitalocean.com

  and if the slugs differ, pass `-var size=... -var image=...`. The image wanted
  is the console's *Vanilla ROCm*: Ubuntu, ROCm, Docker, nothing running. The
  *Quick Start* images boot with a container already serving AMD's own vLLM
  build, and a second engine on the card is memory noise and a version confusion.
- **The price is an output, not an input.** `price_hourly` comes back from the
  API after `apply`; if it is not the figure the run was priced at, the run
  stops before the first `docker run`.

## What this is not

Not a Kubernetes node. A droplet is a VM with a card, a public address and
Docker — enough for a benchmark run, which is a single vLLM container and a load
generator on the same host. The Kubernetes half of the stack (`deploy/manifests/`,
`deploy/keda/`, `deploy/observability/`) runs on `kind` without a card, and on a
GPU node it needs a device plugin and a scheduler that this module does not
provide. That step is deliberately later than this one.
