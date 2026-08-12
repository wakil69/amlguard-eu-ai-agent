# Local secrets

Create `artifact_key.dev` as exactly 32 random bytes (or 64 hexadecimal
characters) before starting the Compose application. The file is ignored by
Git and mounted as a Docker secret. Use an external secret manager for any
non-development deployment.
