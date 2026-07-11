# How qirabot.com/install serves the installer

`qirabot.com` is a static Vite site on S3 behind CloudFront, deployed by
`website/deploy-s3.sh` in the website repo. The one-line installer URLs —

```
https://qirabot.com/install        ← scripts/install.sh   (this repo, main)
https://qirabot.com/install.ps1    ← scripts/install.ps1
```

— are **plain S3 objects, not redirects**: the deploy script fetches both
files from this repo's `main` on every site deploy and uploads them with
`no-cache` and a shell-friendly `Content-Type` (it also excludes them from
the `aws s3 sync --delete` pass so they survive asset syncs, and refuses to
publish anything that doesn't start with `#!/bin/sh`).

## Operational notes

- **Updating the installers**: merge to `main` here, then run the website
  deploy (or just its installer-publishing step). The scripts are
  near-static — they delegate to `uv tool install`, which pulls the latest
  qirabot from PyPI at run time — so lag between a script change and a site
  deploy is harmless in practice.
- **Manual publish** (without a full site build), from this repo's checkout:

  ```bash
  aws s3 cp scripts/install.sh  s3://$WEBSITE_BUCKET/install \
    --cache-control "no-cache, must-revalidate" \
    --content-type "text/x-shellscript; charset=utf-8"
  aws s3 cp scripts/install.ps1 s3://$WEBSITE_BUCKET/install.ps1 \
    --cache-control "no-cache, must-revalidate" \
    --content-type "text/plain; charset=utf-8"
  aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_DISTRIBUTION_ID \
    --paths "/install" "/install.ps1"
  ```

- **Verify**:

  ```bash
  curl -sSf https://qirabot.com/install | head -2       # expect: #!/bin/sh + installer header
  curl -sI  https://qirabot.com/install | grep -i content-type
  ```

- The raw GitHub URLs
  (`https://raw.githubusercontent.com/qirabot/qirabot-python/main/scripts/...`)
  always work as a fallback and are listed in the README's install details
  block.
