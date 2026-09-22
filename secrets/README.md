# secrets/

Holds the SSH key pair the Polaris service account uses to reach the remediation target.
Nothing in this directory is versioned except this file.

Generate the pair once, then authorize the public key on the target host:

```bash
ssh-keygen -t ed25519 -N "" -f secrets/polaris_ed25519 -C "polaris-dss"
# then, on the target host, append secrets/polaris_ed25519.pub to
# /home/polaris/.ssh/authorized_keys
```

The private key is mounted read-only into the API container at `/run/secrets/polaris_ssh_key`.
Only this key is exposed to the container — never the operator's whole `~/.ssh`.

Create `secrets/known_hosts` before starting Compose. Obtain the target host's public key with
`ssh-keyscan -t ed25519 <target-ip>`, compare its `ssh-keygen -lf` fingerprint against the
fingerprint read directly from `/etc/ssh/ssh_host_ed25519_key.pub` on the target, and only then
save the scanned line in `secrets/known_hosts`. This file is mounted read-only at
`/etc/ssh/ssh_known_hosts` in the API container. An unknown or changed host key is rejected.
