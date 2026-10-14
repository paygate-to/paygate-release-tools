#!/usr/bin/env python3
"""PayGate.to release checks and packaging for the plugin, module and SDK repositories.

Run it from (or point it at) the folder that holds the repositories, before you commit or tag:

    python3 release.py                          # check every known repository next to this one
    python3 release.py --only WHMCS-Instant-Payment-Gateway,paygate-php
    python3 release.py --package --out dist     # also build release ZIPs and SHA256SUMS.txt

Checks, per repository:
  * keys: only the published PayGate.to public key ships (paygate_callback_public_v1.pem with the
    published fingerprint); no private keys and no test keys anywhere;
  * leftovers: no local test hosts, "TEST ONLY" helpers or debug dumps in shipped files;
  * syntax: php -l for PHP files, node --check for JavaScript, valid JSON for manifests;
  * versions: the version numbers inside one repository agree (plugin header and readme.txt,
    composer.json or package.json and CHANGELOG.md, module constants and manifests);
  * links: READMEs link to paygate.to.

Exit code 0 when nothing failed (warnings allowed), 1 otherwise. Python 3.8+, standard library only;
php and node are used when they are installed.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

PUBLISHED_KEY_MD5 = 'e6a0d8bf66a5d2f9bbdf6a9c9ca694c0'  # https://paygate.to/docs/paygate_callback_public.pem
PUBLISHED_KEY_NAME = 'paygate_callback_public_v1.pem'

# Repository => kind. Unknown folders are skipped unless named with --only.
KNOWN = {
    'WooCommerce-Instant-Payment-Gateway': 'wordpress',
    'WooCommerce-Crypto-Payment-Gateway': 'wordpress',
    'EDD-Instant-Payment-Gateway': 'wordpress',
    'EDD-Crypto-Payment-Gateway': 'wordpress',
    'WHMCS-Instant-Payment-Gateway': 'whmcs',
    'WHMCS-Crypto-Payment-Gateway': 'whmcs',
    'FOSSBilling-Instant-Payment-Gateway': 'fossbilling',
    'FOSSBilling-Crypto-Payment-Gateway': 'fossbilling',
    'Paymenter-Instant-Payment-Gateway': 'paymenter',
    'Paymenter-Crypto-Payment-Gateway': 'paymenter',
    'OpenCart-Instant-Payment-Gateway': 'opencart',
    'opencart-crypto-payment-gateway': 'opencart',
    'PrestaShop-Instant-Payment-Gateway': 'prestashop',
    'prestashop-crypto-payment-gateway': 'prestashop',
    'Magento-Instant-Payment-Gateway': 'magento',
    'Magento-Crypto-Payment-Gateway': 'magento',
    'paygate-php': 'composer',
    'paygate-laravel': 'composer',
    'paygate-node': 'npm',
}

# Never shipped in release ZIPs (GitHub's own "Download ZIP" may still contain some of them).
EXCLUDE_DIRS = {'.git', '.github', 'node_modules', '.idea', '.vscode', '.phpunit.cache', 'dist'}
EXCLUDE_FILES = {'.DS_Store', 'Thumbs.db', '.phpunit.result.cache', 'composer.lock'}
TEXT_EXT = {'.php', '.js', '.mjs', '.cjs', '.ts', '.json', '.md', '.txt', '.xml', '.html', '.twig', '.tpl', '.css', '.yml', '.yaml', '.ini', '.neon', '.phtml', '.csv', '.pem'}

LEFTOVERS = [
    (re.compile(r'-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----'), 'FAIL', 'private key'),
    (re.compile(r'callback_test_private|keys/paygate_callback_public_test'), 'FAIL', 'reference to a test key'),
    (re.compile(r'\bTEST ONLY\b'), 'FAIL', '"TEST ONLY" helper'),
    (re.compile(r'\b(?:fb|fb72|pm|lv|edd|m2|oc4[01]|ps8|wc)\.test\b'), 'FAIL', 'local test host'),
    (re.compile(r'127\.0\.0\.1:\d{4}'), 'WARN', 'local address with a port'),
    (re.compile(r'\b(?:var_dump|print_r)\s*\(\s*\$_(?:GET|POST|SERVER|REQUEST)'), 'WARN', 'debug dump of request data'),
]

RESULTS = []  # (repo, level, message)


def report(repo, level, message):
    RESULTS.append((repo, level, message))


def walk(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS and not (d == 'vendor' and base == root))
        for name in sorted(files):
            yield os.path.join(base, name)


def rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, '/')


def read_text(path):
    with open(path, 'rb') as fh:
        data = fh.read()
    if b'\0' in data[:4096]:
        return None
    return data.decode('utf-8', errors='replace')


# ---------------------------------------------------------------- checks
def check_keys(repo, root):
    found_published = False
    for path in walk(root):
        name = os.path.basename(path)
        if not name.endswith('.pem'):
            continue
        text = read_text(path) or ''
        if 'PRIVATE KEY' in text:
            report(repo, 'FAIL', '%s is a private key' % rel(path, root))
        elif name != PUBLISHED_KEY_NAME:
            report(repo, 'FAIL', '%s: only %s may ship (test or unknown key)' % (rel(path, root), PUBLISHED_KEY_NAME))
        else:
            md5 = hashlib.md5(open(path, 'rb').read()).hexdigest()
            if md5 != PUBLISHED_KEY_MD5:
                report(repo, 'FAIL', '%s does not match the published key (md5 %s)' % (rel(path, root), md5))
            else:
                found_published = True
    return found_published


def check_leftovers(repo, root):
    for path in walk(root):
        if os.path.splitext(path)[1].lower() not in TEXT_EXT or path.endswith('.pem'):
            continue
        text = read_text(path)
        if text is None:
            continue
        for pattern, level, label in LEFTOVERS:
            match = pattern.search(text)
            if match:
                line = text.count('\n', 0, match.start()) + 1
                report(repo, level, '%s:%d: %s' % (rel(path, root), line, label))


def check_syntax(repo, root):
    php = shutil.which('php')
    node = shutil.which('node')
    php_files, js_files = [], []
    for path in walk(root):
        ext = os.path.splitext(path)[1].lower()
        if ext == '.php' or (ext == '' and (read_text(path) or '').startswith('#!/usr/bin/env php')):
            php_files.append(path)
        elif ext in ('.js', '.mjs', '.cjs') and '/assets/' not in path.replace(os.sep, '/') and '.min.' not in path:
            js_files.append(path)
        elif ext == '.json':
            try:
                json.load(open(path, encoding='utf-8'))
            except ValueError as exc:
                report(repo, 'FAIL', '%s: invalid JSON (%s)' % (rel(path, root), exc))
    if php_files and not php:
        report(repo, 'WARN', 'php not installed: %d PHP files not linted' % len(php_files))
    for path in php_files if php else []:
        out = subprocess.run([php, '-l', path], capture_output=True, text=True)
        if out.returncode != 0:
            report(repo, 'FAIL', '%s: %s' % (rel(path, root), (out.stdout + out.stderr).strip().splitlines()[0]))
    for path in js_files if node else []:
        out = subprocess.run([node, '--check', path], capture_output=True, text=True)
        if out.returncode != 0:
            report(repo, 'FAIL', '%s: %s' % (rel(path, root), (out.stderr.strip().splitlines() or ['syntax error'])[-1]))
    return len(php_files), len(js_files)


def first(pattern, text, flags=0):
    match = re.search(pattern, text or '', flags)
    return match.group(1).strip() if match else None


def changelog_version(root):
    path = os.path.join(root, 'CHANGELOG.md')
    if not os.path.exists(path):
        return None
    return first(r'^##\s*\[?v?(\d+\.\d+(?:\.\d+)?)\]?', read_text(path), re.M)


def collect_versions(kind, root):
    """Version numbers found in one repository: {source: version}."""
    found = {}
    if kind == 'wordpress':
        for name in sorted(os.listdir(root)):
            if name.endswith('.php'):
                text = read_text(os.path.join(root, name)) or ''
                if re.search(r'^\s*\*?\s*Plugin Name:', text, re.M):
                    found[name + ' header'] = first(r'^\s*\*?\s*Version:\s*([0-9.]+)', text, re.M)
        if os.path.exists(os.path.join(root, 'readme.txt')):
            found['readme.txt Stable tag'] = first(r'^Stable tag:\s*([0-9.]+)', read_text(os.path.join(root, 'readme.txt')), re.M)
    elif kind in ('fossbilling', 'paymenter', 'whmcs', 'magento', 'opencart', 'prestashop'):
        for path in walk(root):
            if not path.endswith(('.php', '.json', '.xml')):
                continue
            text = read_text(path) or ''
            name = rel(path, root)
            v = first(r"MODULE_VERSION\s*=\s*'([0-9.]+)'", text)
            if v:
                found[name + ' MODULE_VERSION'] = v
            v = first(r"#\[ExtensionMeta\([^)]*?version:\s*'([0-9.]+)'", text, re.S)
            if v:
                found[name + ' ExtensionMeta'] = v
            if name in ('composer.json', 'install.json'):
                v = json.loads(text).get('version') if text.strip() else None
                if v:
                    found[name] = str(v)
            if kind == 'prestashop':
                v = first(r"\$this->version\s*=\s*'([0-9.]+)'", text)
                if v:
                    found[name + ' $this->version'] = v
    elif kind == 'composer':
        data = json.load(open(os.path.join(root, 'composer.json'), encoding='utf-8'))
        if data.get('version'):
            found['composer.json'] = data['version']
        for path in walk(os.path.join(root, 'src')):
            v = first(r"const VERSION\s*=\s*'([0-9.]+)'", read_text(path))
            if v:
                found[rel(path, root) + ' VERSION'] = v
    elif kind == 'npm':
        found['package.json'] = json.load(open(os.path.join(root, 'package.json'), encoding='utf-8')).get('version')
        for path in walk(os.path.join(root, 'src')):
            v = first(r"VERSION\s*=\s*'([0-9.]+)'", read_text(path))
            if v:
                found[rel(path, root) + ' VERSION'] = v
    cl = changelog_version(root)
    if cl:
        found['CHANGELOG.md'] = cl
    return {k: v for k, v in found.items() if v}


def check_versions(repo, kind, root):
    versions = collect_versions(kind, root)
    distinct = sorted(set(versions.values()))
    if not versions:
        report(repo, 'WARN', 'no version number found')
        return None
    if len(distinct) > 1:
        report(repo, 'FAIL', 'version numbers disagree: ' + ', '.join('%s=%s' % kv for kv in sorted(versions.items())))
    return max(distinct, key=lambda v: [int(x) for x in v.split('.')])


def check_links(repo, root):
    path = os.path.join(root, 'README.md')
    if not os.path.exists(path):
        report(repo, 'WARN', 'no README.md')
        return
    text = read_text(path) or ''
    if 'withoutkyc.to' in text:
        report(repo, 'WARN', 'README.md links to withoutkyc.to; repositories link to paygate.to')
    if 'paygate.to' not in text:
        report(repo, 'WARN', 'README.md has no paygate.to link')


def detect_kind(root):
    """Best guess for a folder that is not in KNOWN."""
    if os.path.exists(os.path.join(root, 'readme.txt')):
        return 'wordpress'
    if os.path.exists(os.path.join(root, 'package.json')):
        return 'npm'
    if os.path.exists(os.path.join(root, 'composer.json')):
        kind = json.load(open(os.path.join(root, 'composer.json'), encoding='utf-8')).get('type', '')
        return 'magento' if kind.startswith('magento2') else 'composer'
    if os.path.isdir(os.path.join(root, 'modules', 'gateways')):
        return 'whmcs'
    return 'unknown'


# ---------------------------------------------------------------- packaging
def package(repo, root, version, out_dir):
    """<repo>-<version>.zip with the same top folder as GitHub's "Download ZIP" (<repo>-main/),
    so WordPress keeps updating the same plugin folder."""
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, '%s-%s.zip' % (repo, version or 'unversioned'))
    top = repo + '-main'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in walk(root):
            if os.path.basename(path) in EXCLUDE_FILES:
                continue
            info = zipfile.ZipInfo(top + '/' + rel(path, root), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            with open(path, 'rb') as fh:
                zf.writestr(info, fh.read())
    return target


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description='PayGate.to release checks and packaging.')
    parser.add_argument('--root', default=os.path.dirname(here), help='folder that holds the repositories (default: the parent of this tool)')
    parser.add_argument('--only', default='', help='comma-separated repository folder names')
    parser.add_argument('--package', action='store_true', help='build release ZIPs and SHA256SUMS.txt')
    parser.add_argument('--out', default=os.path.join(here, 'dist'), help='output folder for --package (default: ./dist)')
    args = parser.parse_args()

    names = [n.strip() for n in args.only.split(',') if n.strip()] or [n for n in KNOWN if os.path.isdir(os.path.join(args.root, n))]
    if not names:
        print('No repositories found in %s. Use --root.' % args.root)
        return 1
    built = []
    for repo in names:
        root = os.path.join(args.root, repo)
        if not os.path.isdir(root):
            report(repo, 'FAIL', 'folder not found')
            continue
        kind = KNOWN.get(repo) or detect_kind(root)
        has_key = check_keys(repo, root)
        if kind not in ('npm', 'composer', 'unknown') and not has_key:
            report(repo, 'WARN', 'no %s found (callbacks cannot be verified without it)' % PUBLISHED_KEY_NAME)
        check_leftovers(repo, root)
        n_php, n_js = check_syntax(repo, root)
        version = check_versions(repo, kind, root)
        check_links(repo, root)
        report(repo, 'INFO', '%s, version %s, %d PHP and %d JS files checked' % (kind, version or '?', n_php, n_js))
        failed = any(r == repo and level == 'FAIL' for r, level, _ in RESULTS)
        if args.package and not failed:
            built.append(package(repo, root, version, args.out))

    width = max(len(n) for n in names)
    for level in ('FAIL', 'WARN', 'INFO'):
        for repo, lv, message in RESULTS:
            if lv == level:
                print('%-4s  %-*s  %s' % (lv, width, repo, message))
    if built:
        sums = os.path.join(args.out, 'SHA256SUMS.txt')
        with open(sums, 'w') as fh:
            for path in sorted(built):
                fh.write('%s  %s\n' % (sha256(path), os.path.basename(path)))
        print('\nBuilt %d ZIPs in %s (checksums in SHA256SUMS.txt).' % (len(built), args.out))
    fails = sum(1 for _, level, _ in RESULTS if level == 'FAIL')
    warns = sum(1 for _, level, _ in RESULTS if level == 'WARN')
    print('\n%d failure(s), %d warning(s) in %d repositories.' % (fails, warns, len(names)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
