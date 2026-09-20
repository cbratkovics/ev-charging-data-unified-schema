# Owner TODO

Steps only the owner can take. Nothing here needs a secret.

1. **Create the GitHub remote and push.** `git remote add origin git@github.com:cbratkovics/ev-charging-data-unified-schema.git && git push -u origin main`. Nothing has been pushed by the assistant.
2. **Make the repository public.** GitHub Pages on a free plan needs a public repository; the licences of all three sources permit publication (docs/DATA_SOURCES.md).
3. **Enable GitHub Pages** with source "GitHub Actions" (Settings, Pages). The `full-build.yml` workflow publishes the dbt docs site and `manifest.json` there; the URL is `https://cbratkovics.github.io/ev-charging-data-unified-schema/`.
4. **Run `full-build.yml` once by hand** (Actions, full-build, Run workflow). The first run downloads the sources (no cache yet), builds, compares with the committed artifacts, publishes the docs, and uploads the fresh artifacts. Expect status `ok` if the publishers have not changed their files since the committed run, otherwise an informational issue.
5. **Issue labels.** The workflow creates `new-source-data` and `full-build-regression` with `--force` when it first needs them; nothing to set up.
6. **Releases are yours.** When an issue says new source data is available, run `make release` locally, review the regenerated artifacts and docs, and commit. The scheduled build never commits.
7. **CI on pull requests.** Once Pages serves `manifest.json`, pull requests build only the modified models and their ancestors; until then they run the full fixture build.
