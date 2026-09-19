# The router as an image, because a compiled binary cannot ride a ConfigMap the
# way the Python stub does (../deploy/manifests/overlays/kind/stub/server.py).
# That is the one thing this component costs `kind` that the rest of the stack
# does not: a build step and a `kind load` before the first apply.

# Pinned to the floor the module declares and CI runs, not to `latest`: a
# router that only compiles on the newest toolchain has a requirement nobody
# wrote down (.github/workflows/router.yml).
FROM golang:1.20-alpine AS build
WORKDIR /src

# go.mod has no requires, so there is nothing to download and no cache layer
# worth splitting out. Copying the sources in one step keeps that visible: the
# day this file grows a `go mod download`, the module grew a dependency.
COPY go.mod .
COPY *.go ./

# CGO off is what makes the binary static and therefore what makes the scratch
# stage below legal: with cgo on, the image would need a libc it does not have.
# -trimpath so the build is reproducible from a different checkout path.
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /prefix-router .

# Nothing but the binary. No shell, no package manager, no CA bundle -- the
# router speaks plain HTTP to Pod addresses inside the cluster, so it needs
# none of them, and an image with no shell is one that cannot be exec'd into
# when something goes wrong. That trade is deliberate: the decision is already
# observable from outside through the two response headers (README.md §1).
FROM scratch
COPY --from=build /prefix-router /prefix-router

# No USER line: scratch has no /etc/passwd for a name to resolve against, so
# the numeric UID is set in the Pod's securityContext instead
# (../deploy/router/kind/deployment.yaml).
ENTRYPOINT ["/prefix-router"]
