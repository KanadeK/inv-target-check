"""Bounded inventory parsing and local target verification."""
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urljoin, urlsplit
import zlib

MAX_INPUT = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_HTML = 8 * 1024 * 1024
MAX_ENTRIES = 250_000
MAX_LINE = 16_384


class AuditError(ValueError):
    """Invalid or unsupported input prevents a complete audit."""


@dataclass(frozen=True)
class Entry:
    line: int
    name: str
    role: str
    priority: int
    uri: str
    display_name: str

    @property
    def target(self):
        return self.uri[:-1] + self.name if self.uri.endswith('$') else self.uri


def bounded_read(path, limit):
    path = Path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise AuditError('input is not a regular file')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise AuditError(f'file exceeds {limit} bytes')
    return data


def parse_entry(line, number):
    if len(line) > MAX_LINE:
        raise AuditError(f'inventory line {number} exceeds {MAX_LINE} characters')
    # Scan tokens instead of a backtracking expression over arbitrary object names.
    tokens = list(re.finditer(r'\S+', line))
    for index in range(1, len(tokens) - 1):
        role = tokens[index].group()
        priority = tokens[index + 1].group()
        if ':' not in role or role.startswith(':') or role.endswith(':'):
            continue
        if not re.fullmatch(r'-?[0-9]{1,10}', priority):
            continue
        end = tokens[index + 1].end()
        if end == len(line):
            continue
        # Exactly one delimiter follows priority in Sphinx's emitted format.
        # An additional delimiter indicates an empty URI (dirhtml root page).
        rest = line[end + 1:]
        if rest and rest[0].isspace():
            uri, display = '', rest.strip()
        else:
            parts = rest.split(None, 1)
            if len(parts) != 2:
                continue
            uri, display = parts
        name = line[:tokens[index].start()].rstrip()
        if not display.strip() or name.startswith('#'):
            continue
        return Entry(number, name, role, int(priority), uri, display.strip())
    raise AuditError(f'malformed inventory entry at line {number}')


def read_inventory(path):
    data = bounded_read(path, MAX_INPUT)
    parts = data.split(b'\n', 4)
    if len(parts) != 5 or parts[0].rstrip() != b'# Sphinx inventory version 2':
        raise AuditError('expected Sphinx inventory version 2 with four header lines')
    if not parts[1].startswith(b'# Project: ') or not parts[2].startswith(b'# Version: '):
        raise AuditError('invalid project/version headers')
    if b'zlib' not in parts[3]:
        raise AuditError('inventory does not declare zlib compression')
    try:
        dec = zlib.decompressobj()
        raw = dec.decompress(parts[4], MAX_EXPANDED + 1)
        if len(raw) > MAX_EXPANDED or dec.unconsumed_tail:
            raise AuditError('expanded inventory exceeds size limit')
        if not dec.eof or dec.unused_data:
            raise AuditError('truncated zlib stream or trailing inventory bytes')
        text = raw.decode('utf-8')
        project = parts[1][11:].decode('utf-8').rstrip('\r')
        version = parts[2][11:].decode('utf-8').rstrip('\r')
    except (zlib.error, UnicodeError) as exc:
        raise AuditError('invalid compressed or UTF-8 inventory') from exc
    entries = []
    for number, line in enumerate(text.splitlines(), 5):
        if not line.strip():
            continue
        if len(entries) >= MAX_ENTRIES:
            raise AuditError('inventory exceeds entry limit')
        entries.append(parse_entry(line, number))
    if not entries:
        raise AuditError('empty inventory: no targets were checked')
    return {'project': project, 'version': version}, entries


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value is not None and (key == 'id' or (tag == 'a' and key == 'name')):
                self.values.add(value)


def decoded(value):
    if re.search(r'%(?![0-9A-Fa-f]{2})', value):
        raise AuditError('malformed percent escape')
    try:
        return unquote(value, encoding='utf-8', errors='strict')
    except UnicodeError as exc:
        raise AuditError('invalid percent-encoded UTF-8') from exc


def validate_base(base_url):
    if base_url is None:
        return None
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port
    except ValueError as exc:
        raise AuditError('invalid base URL') from exc
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or not parsed.path.endswith('/')
            or any(ord(c) <= 32 for c in base_url) or '\\' in base_url):
        raise AuditError('base URL must be an absolute HTTP(S) directory URL without credentials/query/fragment')
    return parsed


def origin(parsed):
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
    return parsed.scheme.lower(), parsed.hostname, port


def local_target(target, base):
    if any(ord(c) < 32 for c in target) or '\\' in target:
        raise AuditError('control characters or backslashes in URI')
    try:
        uri = urlsplit(target)
        _ = uri.port
    except ValueError as exc:
        raise AuditError('invalid URI') from exc
    if uri.scheme or uri.netloc:
        if base is None or origin(uri) != origin(base):
            return None, None, 'external'
        if uri.username or uri.password:
            raise AuditError('credential URL is unsupported')
    if base is None:
        if uri.path.startswith('/'):
            raise AuditError('root-relative target requires --base-url')
        path = uri.path
    else:
        absolute = urlsplit(urljoin(base.geturl(), target))
        base_path = decoded(base.path)
        absolute_path = decoded(absolute.path)
        if not absolute_path.startswith(base_path):
            raise AuditError('target is outside mapped base URL')
        path = absolute.path
        # Slice after decoding so encoded base paths work correctly.
        path = decoded(path)[len(base_path):]
    if re.search(r'%2[fF]|%5[cC]', uri.path):
        raise AuditError('encoded path separators need server-specific handling')
    if base is None:
        path = decoded(path)
    if any(c in path for c in '\\:*?"<>|\x00') or path.startswith('/'):
        raise AuditError('target is not a portable local path')
    normalized = []
    for part in path.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not normalized:
                raise AuditError('target escapes documentation root')
            normalized.pop()
        else:
            normalized.append(part)
    fragment = decoded(uri.fragment)
    local = '/'.join(normalized)
    if path.endswith('/') and local:
        local += '/'
    return local, fragment, 'local'


def audit(inventory, root, *, base_url=None, allow_external=False):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise AuditError('HTML root must be a directory')
    base = validate_base(base_url)
    metadata, entries = read_inventory(inventory)

    @lru_cache(maxsize=128)
    def child_names(directory):
        if not directory.resolve().is_relative_to(root):
            raise AuditError('directory symlink escapes documentation root')
        return {child.name for child in directory.iterdir()}

    def exact_file(path):
        current = root
        for part in path.relative_to(root).parts:
            if not current.is_dir() or part not in child_names(current):
                return False
            current = current / part
        return current.is_file()

    @lru_cache(maxsize=32)
    def anchors(path):
        try:
            html = bounded_read(path, MAX_HTML).decode('utf-8-sig')
        except UnicodeError as exc:
            raise AuditError('HTML is not UTF-8') from exc
        parser = Anchors()
        parser.feed(html)
        parser.close()
        return parser.values

    results = []
    for entry in entries:
        result = asdict(entry)
        result['target'] = entry.target
        try:
            relative, fragment, kind = local_target(entry.target, base)
            if kind == 'external':
                result.update(status='unverified', code='external-target')
            else:
                path = root.joinpath(*relative.split('/'))
                # A directory URL maps to index.html for Sphinx dirhtml output.
                if not relative or relative.endswith('/') or path.is_dir():
                    path = path / 'index.html'
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    raise AuditError('symlink or target escapes documentation root')
                result['file'] = path.relative_to(root).as_posix()
                result['fragment'] = fragment
                if not exact_file(path):
                    result.update(status='failed', code='missing-file')
                elif fragment and path.suffix.lower() not in ('.html', '.htm'):
                    result.update(status='failed', code='non-html-fragment')
                elif fragment and fragment not in anchors(resolved) and fragment.lower() != 'top':
                    result.update(status='failed', code='missing-anchor')
                else:
                    result.update(status='ok', code='verified')
        except (OSError, RuntimeError, AuditError) as exc:
            result.update(status='failed', code='unreadable-or-unsupported', detail=str(exc))
        results.append(result)
    counts = Counter(item['status'] for item in results)
    return {'schema_version': 1, **metadata, 'entries': len(results),
            'summary': {key: counts[key] for key in ('ok', 'failed', 'unverified')},
            'allow_external': allow_external,
            'passed': counts['failed'] == 0 and (allow_external or counts['unverified'] == 0),
            'results': results}
