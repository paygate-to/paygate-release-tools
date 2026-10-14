# PayGate.to release tools

Checks and packages the PayGate.to plugin, module and SDK repositories before a release. For maintainers; merchants do not need it.

## What it checks

For every repository it finds next to this folder:

| Check | Fails when |
|---|---|
| **Keys** | A private key, a test key or any `.pem` other than `paygate_callback_public_v1.pem` is present, or that file is not the published key (md5 `e6a0d8bf66a5d2f9bbdf6a9c9ca694c0`, the same as [paygate.to/docs/paygate_callback_public.pem](https://paygate.to/docs/paygate_callback_public.pem)). |
| **Leftovers** | Shipped files contain a private key, a reference to a test key, a "TEST ONLY" helper or a local test host. Local addresses with a port and debug dumps of request data are warnings. |
| **Syntax** | `php -l` fails on a PHP file, `node --check` fails on a JavaScript file, or a JSON manifest is invalid. |
| **Versions** | The version numbers inside one repository disagree: plugin header and `readme.txt` *Stable tag*, `MODULE_VERSION` and `#[ExtensionMeta]`, `composer.json`/`package.json`/`install.json`, PrestaShop `$this->version`, SDK `VERSION` constants and the top entry of `CHANGELOG.md`. |
| **Links** | (warning) `README.md` links to withoutkyc.to instead of paygate.to, or has no paygate.to link. |

`php` and `node` are used when installed; without them the syntax checks are skipped with a warning.

## Use

Put this folder next to the repositories (for example in `~/Documents/GitHub/`) and run:

```bash
python3 paygate-release-tools/release.py                    # check everything
python3 paygate-release-tools/release.py --only EDD-Instant-Payment-Gateway,paygate-php
python3 paygate-release-tools/release.py --package          # also build dist/*.zip + SHA256SUMS.txt
python3 paygate-release-tools/release.py --root /path/to/repos --package --out /tmp/release
```

The exit code is 1 when anything failed, so it can run before a commit, a tag or in CI.

## Release ZIPs

`--package` builds `dist/<Repository>-<version>.zip` for every repository that passed, plus `SHA256SUMS.txt`.

- The top folder inside each ZIP is `<Repository>-main/`, exactly like GitHub's **Download ZIP**. WordPress uses that folder name for the plugin, so updating from a release ZIP replaces the plugin installed from GitHub instead of adding a second copy.
- `.git`, `.github`, `node_modules`, the root `vendor` folder, editor folders, `composer.lock` and test caches are left out.
- File dates are fixed, so the same sources always give the same ZIP and checksum.

Attach the ZIPs and `SHA256SUMS.txt` to the GitHub release.

## Before publishing

1. `python3 paygate-release-tools/release.py --package` reports 0 failures.
2. The repository's own tests pass (`composer test`, `npm test`).
3. To test a callback endpoint end to end, use `paygate-callback-tester` from [paygate-php](https://github.com/paygate-to/paygate-php#testing-your-callback-endpoint) with a test key you remove afterwards. Never commit that key: this tool fails the release if you do.

## License

MIT.
