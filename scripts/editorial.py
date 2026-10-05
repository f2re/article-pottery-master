#!/usr/bin/env python3
"""Offline editorial packets, schema 2. No model calls, approval or publishing.

Hashes attest to bytes, not to truth, rights, identity or reviewer independence.
Python 3.11+, standard library only. See docs/QUALITY.md for the trust boundary.
"""
import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = ('vk', 'livemaster')
PRIMARY_CHECKS = ('evidence', 'reader')
READER_SECTIONS = ('promise', 'usefulness', 'clarity', 'interest', 'voice', 'seo', 'channels', 'art')
POLICY = ('AGENTS.md', 'GEMINI.md', 'AUTOR_STYLE.md', 'AUTOR_STYLE_QUICK_REF.md', 'docs/QUALITY.md', 'docs/WORKFLOW.md',
          'docs/RESEARCH.md', 'docs/ART_DIRECTION.md', 'docs/DISTRIBUTION.md',
          'editorial/routes.json')
MAX_TEXT = 2 * 1024 * 1024
MAX_REVISIONS = 2
MARKER = re.compile(r'\[\[([A-Z][A-Z0-9_-]*)\]\]')
IMAGE = re.compile(r'!\[([^\]\n]*)\]\(([^)\s]+)\)')
PLACEHOLDER = re.compile(r'\b(?:todo|tbd)\b|\[(?:заполнить|вставить|уточнить)', re.I)
SLOP = {
    'S01': r'в (?:современном )?мире,? где',
    'S02': r'не просто[^.!?]{0,90}(?:а |это )',
    'S03': r'погрузимся в|погрузитесь в',
    'S04': r'уникальный дизайн|идеальный подарок|высочайшее качество',
    'S05': r'философия тишины|душа (?:глины|чаши)|магия (?:глины|раку)',
    'S06': r'в (?:этой|данной) статье мы рассмотрим',
    'S07': r'напишите в комментариях|не оставит равнодушным',
}


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def normalize(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    return re.sub(r'\s+', ' ', ''.join(c for c in value if unicodedata.category(c) != 'Cf')).strip()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file(root, name):
    require(text(name) and '\\' not in name, 'Нужен относительный путь без обратных слешей')
    parts = PurePosixPath(name)
    require(not parts.is_absolute() and '..' not in parts.parts and str(parts) == name,
            'Ненормализованный путь или выход за пределы пакета')
    result = root
    for part in parts.parts:
        result = result / part
        require(not result.is_symlink(), 'Символические ссылки запрещены')
    require(root.resolve() in result.resolve().parents, 'Путь вне пакета')
    return result


def read_text(path):
    require(path.is_file() and not path.is_symlink(), 'Нет обычного файла: ' + str(path))
    require(path.stat().st_size <= MAX_TEXT, 'Слишком большой текстовый файл')
    return path.read_text(encoding='utf-8')


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Повтор ключа JSON: ' + key)
        result[key] = value
    return result


def read_json(path):
    def bad_constant(value):
        raise Invalid('Недопустимая константа JSON: ' + value)
    return json.loads(read_text(path), object_pairs_hook=unique_keys, parse_constant=bad_constant)


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def valid_date(value):
    require(text(value) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'Нужна дата YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    require(parsed <= date.today(), 'Дата проверки находится в будущем')
    return parsed


def url_ok(value):
    if not text(value) or re.search(r'[\s<>()"\\]', value):
        return False
    p = urlparse(value)
    return p.scheme in ('https', 'http') and bool(p.netloc) and p.username is None


def objects(value, name):
    require(isinstance(value, list), name + ': ожидается массив')
    require(all(isinstance(x, dict) for x in value), name + ': нужны объекты')
    ids = [x.get('id') for x in value]
    require(all(text(x) and re.fullmatch(r'[A-Z][A-Z0-9_-]{0,39}', x) for x in ids), name + ': неверный ID')
    require(len(ids) == len(set(ids)), name + ': повтор ID')
    return {x['id']: x for x in value}


def raster_header(path):
    with path.open('rb') as stream:
        head = stream.read(32)
    if path.suffix.lower() == '.png':
        return (head.startswith(b'\x89PNG\r\n\x1a\n') and len(head) >= 24 and head[12:16] == b'IHDR'
                and int.from_bytes(head[16:20], 'big') > 0 and int.from_bytes(head[20:24], 'big') > 0)
    if path.suffix.lower() in ('.jpg', '.jpeg'):
        return head.startswith(b'\xff\xd8\xff')
    return path.suffix.lower() == '.webp' and head[:4] == b'RIFF' and head[8:12] == b'WEBP'


def policy_files():
    return sorted(set(POLICY) | {p.relative_to(ROOT).as_posix() for folder, pattern in
        (('.agents/skills', '*/SKILL.md'), ('.codex/agents', '*.toml'),
         ('.agents/agents', '*.md'), ('editorial/voice', '*.json'), ('editorial/voice', '*.md'), ('scripts', '*.py')) for p in (ROOT / folder).glob(pattern)})


def bundle_hash(package):
    package = Path(package)
    require(package.is_dir() and not package.is_symlink(), 'Нет обычной папки пакета')
    files = {}
    for p in sorted(package.rglob('*')):
        require(not p.is_symlink(), 'Символические ссылки запрещены: ' + str(p))
        relative = p.relative_to(package).as_posix()
        # Review/run records bind separately; only this named notes area is non-evidence.
        if p.is_file() and relative not in ('review.json', 'workflow.json') and not relative.startswith('notes/'):
            files[relative] = file_hash(p)
    require(files, 'Пакет пуст')
    return sha(canonical({'files': files, 'policy': {n: file_hash(ROOT / n) for n in policy_files()}}))


def review_hash(package):
    review = read_json(Path(package) / 'review.json')
    require(isinstance(review, dict), 'review.json: ожидается объект')
    return sha(canonical({'review': {k: v for k, v in review.items() if k != 'human_approval'},
                          'workflow': read_json(Path(package) / 'workflow.json')}))


class Report:
    def __init__(self):
        self.issues = []

    def add(self, code, path, message, level='error', owner='pottery-editor', excerpt=''):
        identity = sha(canonical([code, path, message, excerpt]))[:16]
        self.issues.append(dict(id=identity, code=code, path=path, message=message, level=level,
                                owner=owner, next_step='Исправить указанное поле и повторить проверку' if level == 'error'
                                else 'Разобрать контекст в отзыве reader', excerpt=excerpt))

    @contextmanager
    def guard(self, path, owner='pottery-editor'):
        try:
            yield
        except (Invalid, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self.add('CONTRACT', path, str(exc), owner=owner)

    def load(self, package, name, expected, default):
        with self.guard(name):
            value = read_json(safe_file(package, name))
            require(isinstance(value, expected), 'Неверный тип JSON')
            return value
        return default

    def strings(self, obj, fields, path):
        for key in fields:
            value = obj.get(key)
            if not text(value):
                self.add('REQUIRED', path + '.' + key, 'Не заполнено обязательное поле')
            elif PLACEHOLDER.search(normalize(value)):
                self.add('TEMPLATE', path + '.' + key, 'Осталась заглушка')

    @property
    def ok(self):
        return not any(x['level'] == 'error' for x in self.issues)


def lint(value, path):
    report = Report()
    normalized = normalize(value)
    if PLACEHOLDER.search(normalized):
        report.add('TEMPLATE', path, 'Осталась заглушка')
    for code, pattern in SLOP.items():
        for match in re.finditer(pattern, normalized):
            report.add(code, path, 'Речевая формула: проверить контекст, цитату и собственное содержание',
                       'warning', 'pottery-style', match.group())
    for paragraph in re.split(r'\n\s*\n', value):
        if len(paragraph.split()) > 130:
            report.add('RHYTHM', path, 'Проверить ход мысли длинного абзаца', 'warning', 'pottery-style', paragraph[:80])
    return report.issues


def route(meta):
    profile = 'research' if meta.get('type') == 'research' or meta.get('risk') == 'elevated' else meta.get('profile', 'standard')
    routes = read_json(ROOT / 'editorial/routes.json')
    require(profile in routes['profiles'], 'Неизвестный профиль')
    result = dict(routes['profiles'][profile], profile=profile, max_revision_rounds=MAX_REVISIONS)
    result['required_reviews'] = list(PRIMARY_CHECKS) + (['science'] if profile == 'research' else [])
    if meta.get('image_policy') == 'illustrated':
        result['conditional_roles'] = list(result.get('conditional_roles', [])) + ['pottery-art']
    return result


def inventory(surfaces):
    result = []
    for name, value in surfaces.items():
        for index, paragraph in enumerate(re.split(r'\n\s*\n', value.strip())):
            if paragraph.strip():
                result.append(dict(id=sha(canonical([name, index, paragraph]))[:16], file=name,
                                   text=paragraph, claims=MARKER.findall(paragraph)))
    return result


def inspect_package(package, report):
    """Collect independent field/record failures instead of stopping at first error."""
    meta = report.load(package, 'metadata.json', dict, {})
    with report.guard('metadata.json.schema_version'):
        require(type(meta.get('schema_version')) is int and meta['schema_version'] == 2,
                'Нужна схема 2; migrate создаёт отдельную копию схемы 1 без переноса согласований')
    report.strings(meta, ('title', 'description', 'primary_query', 'reader_job', 'added_value'), 'metadata.json')
    for key, choices in {'type': ('research', 'guide', 'studio'), 'risk': ('normal', 'elevated'),
                         'profile': ('note', 'standard', 'research'), 'image_policy': ('text_only', 'illustrated')}.items():
        if meta.get(key) not in choices:
            report.add('ENUM', 'metadata.json.' + key, 'Недопустимое значение')
    source_list = report.load(package, 'sources.json', list, [])
    claim_list = report.load(package, 'claims.json', list, [])
    asset_list = report.load(package, 'assets.json', list, [])
    sources, claims, assets = {}, {}, {}
    with report.guard('sources.json'):
        sources = objects(source_list, 'sources'); require(sources, 'Нет источников')
    with report.guard('claims.json'):
        claims = objects(claim_list, 'claims'); require(claims, 'Нет утверждений')
    with report.guard('assets.json'):
        assets = objects(asset_list, 'assets')
    for sid, s in sources.items():
        path = 'sources.json.' + sid
        report.strings(s, ('title', 'language', 'kind', 'public_label'), path)
        with report.guard(path, 'pottery-research'):
            valid_date(s.get('checked_on'))
            require(s.get('access') in ('fulltext', 'object', 'abstract', 'lead', 'local'), 'Неверный уровень доступа')
            if s.get('kind') in ('publication', 'museum'):
                require(url_ok(s.get('url')), 'Неверный URL')
                require(s['access'] != 'local', 'Веб-источник не имеет доступа local')
            else:
                require(s.get('kind') in ('measurement', 'interview', 'product_record', 'observation'), 'Неизвестный вид источника')
                require(s['access'] == 'local', 'Для собственного источника нужен local')
                report.strings(s, ('file', 'sha256', 'creator', 'protocol', 'consent_reference'), path)
                name = s.get('file', '')
                require(name.startswith(('evidence/', '.private/')), 'Локальный источник хранится в evidence/ или .private/')
                local = safe_file(package, name)
                require(local.is_file() and file_hash(local) == s.get('sha256'), 'Нет исходника или его хэш изменён')
                require(s.get('visibility') in ('private', 'public'), 'Укажите visibility')
                valid_date(s.get('recorded_on'))
    for cid, c in claims.items():
        path = 'claims.json.' + cid
        report.strings(c, ('text', 'locator', 'scope'), path)
        with report.guard(path, 'pottery-research'):
            require(c.get('status') == 'verified', 'Утверждение ещё не проверено исследователем')
            refs = c.get('sources')
            require(isinstance(refs, list) and refs and all(isinstance(s, str) and s in sources for s in refs), 'Нет связанного источника')
            require(len(set(refs)) == len(refs), 'Повтор источника')
            if any(sources[s].get('language', '').split('-')[0] in ('ja', 'zh') for s in refs):
                require(c.get('translation_checked') is True, 'Перевод не проверен')
    surfaces = {k: meta.get(k.split('.')[1], '') for k in ('metadata.title', 'metadata.description')}
    surfaces = {k: v for k, v in surfaces.items() if isinstance(v, str)}
    with report.guard('article.md', 'pottery-writer'):
        value = read_text(package / 'article.md'); surfaces['article.md'] = value
        require(len(value.strip()) >= 80, 'Статья пуста')
        require(re.findall(r'^# (.+)$', value, re.M) == [meta.get('title')], 'Нужен один H1, совпадающий с title')
    publications = meta.get('publications', [])
    if not isinstance(publications, list) or not publications:
        report.add('REQUIRED', 'metadata.json.publications', 'Нужны отдельные выходные публикации')
        publications = []
    known_ids, known_files = set(), {'article.md', 'art-brief.md'}
    channels = set()
    for index, p in enumerate(publications):
        path = 'metadata.json.publications.' + str(index)
        with report.guard(path, 'pottery-growth'):
            require(isinstance(p, dict), 'Нужна запись публикации')
            report.strings(p, ('id', 'channel', 'format', 'file', 'promise', 'next_action'), path)
            require(text(p.get('id')) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', p['id']), 'Неверный ID публикации')
            require(p['id'] not in known_ids, 'Повтор ID публикации'); known_ids.add(p['id'])
            require(p.get('channel') in CHANNELS, 'Неподдерживаемый канал'); channels.add(p['channel'])
            require(p.get('format') in ('note', 'card', 'article'), 'Неизвестный формат')
            name = p.get('file', '')
            require(isinstance(name, str) and re.fullmatch(r'[a-z0-9-]+\.md', name), 'Нужен простой путь Markdown')
            require(name not in known_files, 'Повтор или служебный путь публикации'); known_files.add(name)
            value = read_text(safe_file(package, name)); surfaces[name] = value
            for field in ('promise', 'next_action'):
                if isinstance(p.get(field), str):
                    surfaces['publication.' + p['id'] + '.' + field] = p[field]
            require(len(value.strip()) >= 40, 'Публикация пуста')
    declared_channels = meta.get('channels')
    if (not isinstance(declared_channels, list) or not declared_channels
            or not all(isinstance(c, str) and c in CHANNELS for c in declared_channels)
            or len(set(declared_channels)) != len(declared_channels)
            or channels != set(declared_channels)):
        report.add('CHANNELS', 'metadata.json.channels', 'Нужны уникальные каналы, совпадающие со списком публикаций')
    published_surfaces = [(p.get('file'), surfaces.get(p.get('file'), '')) for p in publications if isinstance(p, dict)]
    for i, (name, value) in enumerate(published_surfaces):
        if value:
            for other_name, other_value in published_surfaces[:i]:
                if normalize(value) == normalize(other_value):
                    report.add('DUPLICATE_VERSION', name, 'Текст совпадает с ' + str(other_name), 'warning', 'pottery-style')
    if meta.get('image_policy') == 'illustrated':
        if not assets:
            report.add('ASSETS', 'assets.json', 'Иллюстрированному материалу нужны файлы')
        with report.guard('art-brief.md', 'pottery-art'):
            require(len(read_text(package / 'art-brief.md').strip()) >= 40, 'Нет задания на изображения')
    elif assets:
        report.add('ASSETS', 'metadata.json.image_policy', 'Изображения требуют illustrated')
    asset_files = set()
    for aid, a in assets.items():
        path = 'assets.json.' + aid
        report.strings(a, ('file', 'creator', 'rights', 'rights_reference', 'public_credit', 'caption', 'alt'), path)
        with report.guard(path, 'pottery-art'):
            name = a.get('file', '')
            require(isinstance(name, str) and re.fullmatch(r'media/[A-Za-z0-9_/-]+\.(?:png|jpg|jpeg|webp)', name), 'Изображения: media/<имя>.png/jpg/webp')
            require(name not in asset_files, 'Повтор файла'); asset_files.add(name)
            image = safe_file(package, name)
            require(image.is_file() and raster_header(image), 'Нет растрового файла с корректной сигнатурой')
            require(a.get('kind') in ('photograph', 'diagram', 'generated'), 'Неверный вид изображения')
            require(type(a.get('documentary')) is bool, 'Нужен флаг documentary')
            if a['kind'] == 'generated':
                require(not a['documentary'], 'Генерация не документальное свидетельство')
                require('иллюстрация создана ии' in normalize(a.get('caption', '')), 'Нет маркировки ИИ')
            if a['kind'] == 'diagram':
                require(not a['documentary'] and 'схема' in normalize(a.get('caption', '')), 'Укажите условную схему')
            for field in ('caption', 'alt', 'public_credit'):
                surfaces[aid + '.' + field] = a[field]
    illustrated, used = set(), set()
    for path, value in surfaces.items():
        report.issues.extend(lint(value, path))
        with report.guard(path, 'pottery-verifier'):
            require(not re.search(r'<\s*/?\s*[A-Za-z][^>]*>', value), 'HTML в исходном тексте не поддерживается')
            images = IMAGE.findall(value)
            require(not images or path.endswith('.md'), 'Изображения допускаются только в тексте публикации')
            require(value.count('![') == len(images), 'Неподдерживаемая форма изображения')
            for alt, filename in images:
                require(filename in asset_files, 'Изображение не включено в реестр прав')
                require(alt == next(a['alt'] for a in assets.values() if a['file'] == filename), 'Alt расходится с реестром')
                illustrated.add(filename)
            ids = MARKER.findall(value)
            require(len(ids) == value.count('[[') == value.count(']]'), 'Повреждённый маркер утверждения')
            for cid in ids:
                require(cid in claims, 'Неизвестное утверждение ' + cid); used.add(cid)
    if illustrated != asset_files:
        report.add('ASSET_PLACEMENT', 'assets.json', 'Не все изображения использованы в тексте')
    for sid, source in sources.items():
        path = 'sources.json.' + sid + '.public_label'
        label = source.get('public_label')
        if isinstance(label, str):
            report.issues.extend(lint(label, path))
            if '[[' in label or '![' in label or re.search(r'<\s*/?\s*[A-Za-z][^>]*>', label):
                report.add('LABEL', path, 'Подпись источника должна быть обычным текстом')
    if isinstance(meta.get('author'), str):
        surfaces['metadata.author'] = meta['author']
        report.issues.extend(lint(meta['author'], 'metadata.author'))
        if '[[' in meta['author'] or '![' in meta['author'] or '<' in meta['author']:
            report.add('LABEL', 'metadata.author', 'Имя автора должно быть обычным текстом')
    if not used:
        report.add('COVERAGE', 'article.md', 'Нет маркеров подтверждённых утверждений')
    for cid in set(claims) - used:
        report.add('UNUSED_CLAIM', 'claims.json.' + cid, 'Утверждение нигде не используется', 'warning', 'pottery-verifier')
    workflow = report.load(package, 'workflow.json', dict, {})
    with report.guard('workflow.json'):
        require(type(workflow.get('revision')) is int and workflow['revision'] >= 0, 'Нужен номер цикла исправлений')
        require(isinstance(workflow.get('runs'), list), 'Нужен журнал реальных запусков')
    return dict(meta=meta, sources=sources, claims=claims, assets=assets, surfaces=surfaces, workflow=workflow)


def public_payload(package, data):
    """One renderer for review and export. Never copies private research or reviews."""
    sources, claims, assets, meta = (data[k] for k in ('sources', 'claims', 'assets', 'meta'))
    def citation(match):
        cid = match.group(1)
        values = []
        for sid in claims[cid]['sources']:
            s = sources[sid]
            label = re.sub(r'[\[\]\n]', '', s['public_label'])
            values.append('[' + label + '](' + s['url'] + ')' if s['kind'] in ('publication', 'museum')
                          else '(Источник: ' + label + ')')
        return ' '.join(values)
    def cited(value):
        return MARKER.sub(citation, value)
    def image(match):
        alt, path = match.groups()
        a = next(a for a in assets.values() if a['file'] == path)
        return ('![' + alt + '](' + path + ')\n\n' + a['caption'] + '\n\n' + a['public_credit'])
    payload = {}
    for name in ['article.md'] + [p['file'] for p in meta['publications']]:
        payload[name] = cited(IMAGE.sub(image, data['surfaces'][name])).encode('utf-8')
    public_meta = {k: cited(meta[k]) if isinstance(meta.get(k), str) else None
                   for k in ('title', 'description', 'author')}
    public_meta['publications'] = [{k: cited(p[k]) for k in ('id', 'channel', 'format', 'file', 'promise', 'next_action')}
                                   for p in meta['publications']]
    payload['metadata.json'] = canonical(public_meta)
    for a in assets.values():
        payload[a['file']] = safe_file(package, a['file']).read_bytes()
    # Restricted Markdown renderer: no raw HTML, JS, remote images, or web fonts.
    def inline(value):
        safe = html.escape(value)
        safe = re.sub(r'!\[([^\]]*)\]\((media/[^)]+)\)', r'<img alt="\1" src="\2" loading="lazy">', safe)
        safe = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2" rel="noreferrer">\1</a>', safe)
        return re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', safe)
    def markdown(value):
        out = []
        for block in re.split(r'\n\s*\n', value):
            h = re.match(r'^(#{1,3}) (.+)$', block)
            if h:
                n = len(h[1]); out.append(f'<h{n}>' + inline(h[2]) + f'</h{n}>')
            else:
                out.append('<p>' + inline(block).replace('\n', '<br>') + '</p>')
        return '\n'.join(out)
    metadata_view = '<section><h2>Поля публикации</h2>' + ''.join(
        '<p><strong>' + label + ':</strong> ' + inline(public_meta[key] or 'Не задано') + '</p>'
        for key, label in (('title', 'Название'), ('description', 'Описание'), ('author', 'Автор')))
    for publication in public_meta['publications']:
        metadata_view += ('<h3>' + html.escape(publication['id']) + '</h3><p>'
                          + inline(publication['promise']) + '</p><p><strong>Следующий шаг:</strong> '
                          + inline(publication['next_action']) + '</p>')
    metadata_view += '</section>'
    sections = metadata_view + ''.join('<section><p class="label">' + html.escape(name) + '</p>' + markdown(value.decode('utf-8')) + '</section>'
                       for name, value in payload.items() if name.endswith('.md'))
    preview = ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
               '<meta name="robots" content="noindex,nofollow"><meta http-equiv="Content-Security-Policy" '
               'content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
               '<title>Редакционное превью</title><style>body{font:18px/1.65 Georgia,serif;margin:0 auto;padding:24px;max-width:780px;background:#f5f1e8;color:#202721}'
               'img{max-width:100%;height:auto}section{border-top:1px solid #aaa;padding:24px 0}a{color:#85492f;overflow-wrap:anywhere}'
               '.label,header{font:14px/1.5 sans-serif}p{overflow-wrap:anywhere}h1{font-size:2em}</style>'
               '<header>Редакционное превью. Не опубликовано. Статус проверки — в manifest.json.</header><main>' + sections + '</main></html>')
    payload['preview.html'] = preview.encode('utf-8')
    return payload


def payload_hash(payload):
    return sha(canonical({name: sha(value) for name, value in sorted(payload.items())}))


def validate_reviews(package, data, report, digest, rendered_hash):
    meta, workflow = data['meta'], data['workflow']
    review = report.load(package, 'review.json', dict, {})
    report.strings(meta, ('author',), 'metadata.json')
    with report.guard('workflow.json.revision'):
        require(workflow.get('revision', MAX_REVISIONS + 1) <= MAX_REVISIONS, 'Превышены два цикла исправлений: нужен разбор владельца, а не ещё один автоматический цикл')
    runs = {}
    for i, run in enumerate(workflow.get('runs', [])):
        with report.guard('workflow.json.runs.' + str(i)):
            require(isinstance(run, dict), 'Нужна запись запуска')
            report.strings(run, ('id', 'actor_id', 'role', 'mode', 'notes'), 'workflow.json.runs.' + str(i))
            require(all(text(run.get(k)) for k in ('id', 'actor_id', 'role', 'mode', 'notes')), 'Неполная запись запуска')
            require(run['role'] in ('writer', 'growth', 'art', 'research', 'science-prep', 'editor', 'evidence', 'reader', 'science'), 'Неизвестная роль запуска')
            require(run.get('id') not in runs and text(run.get('id')), 'Повтор или отсутствие run ID')
            require(run.get('mode') in ('independent', 'human', 'sequential_self_review'), 'Неизвестный способ выполнения')
            valid_date(run.get('date')); runs[run['id']] = run
    creators = [r for r in runs.values() if r['role'] in ('writer', 'growth', 'art')]
    if not any(r['role'] == 'writer' for r in creators):
        report.add('PROVENANCE', 'workflow.json.runs', 'Нет записи реального авторского прохода')
    if not any(r['role'] == 'growth' for r in creators):
        report.add('PROVENANCE', 'workflow.json.runs', 'Нет записи подготовки версий для каналов')
    creator_ids = {normalize(r['actor_id']) for r in creators} | {normalize(meta.get('author', '') or '')}
    checks = review.get('checks', {})
    if not isinstance(checks, dict):
        report.add('REQUIRED', 'review.json.checks', 'Нужны отдельные отзывы'); checks = {}
    expected = route(meta)['required_reviews']
    if set(checks) - set(expected):
        report.add('EXTRA_REVIEW', 'review.json.checks', 'Лишний или устаревший тип отзыва; актуальные: ' + ', '.join(expected))
    for role in expected:
        path = 'review.json.checks.' + role
        with report.guard(path, 'pottery-' + ('verifier' if role == 'evidence' else 'style' if role == 'reader' else 'science')):
            item = checks.get(role)
            require(isinstance(item, dict), 'Нет обязательного отзыва')
            report.strings(item, ('reviewer', 'actor_id', 'run_id', 'notes'), path)
            require(all(text(item.get(k)) for k in ('reviewer', 'actor_id', 'run_id', 'notes')), 'Неполные данные проверяющего')
            require(item.get('status') == 'pass', 'Есть замечания или проверка не завершена')
            require(item.get('content_hash') == digest, 'Отзыв относится к другой версии содержания или правил')
            require(item.get('public_hash') == rendered_hash, 'Отзыв не подтверждает окончательное публичное представление')
            run = runs.get(item.get('run_id'), {})
            require(run.get('role') == role and run.get('actor_id') == item.get('actor_id'), 'Нет соответствующего реального запуска проверяющего')
            require(run.get('mode') in ('independent', 'human'), 'Повторная самопроверка не является независимой приёмкой')
            require(normalize(item['actor_id']) not in creator_ids and normalize(item['reviewer']) not in creator_ids,
                    'Автор/адаптатор/создатель изображений не принимает собственный пакет')
            require(item['run_id'] not in {r['id'] for r in creators}, 'Авторский запуск нельзя использовать как проверку')
            if role == 'evidence':
                preparers = {normalize(r['actor_id']) for r in runs.values() if r['role'] in ('research', 'science-prep')}
                require(normalize(item['actor_id']) not in preparers, 'Создатель досье не может независимо проверить собственные доказательства')
    with report.guard('review.json.checks.independence'):
        a, b = checks.get('evidence', {}), checks.get('reader', {})
        require(a.get('actor_id') and b.get('actor_id') and normalize(a['actor_id']) != normalize(b['actor_id'])
                and a.get('run_id') != b.get('run_id'), 'Нужны два разных основных проверяющих')
    # Invalid objects are already reported above; keep independent checks running.
    checks = {k: v if isinstance(v, dict) else {} for k, v in checks.items()}
    passages = inventory(data['surfaces'])
    with report.guard('review.json.checks.evidence.coverage', 'pottery-verifier'):
        coverage = checks.get('evidence', {}).get('coverage')
        require(isinstance(coverage, list), 'Нет независимого разбора абзацев и метаданных')
        rows = {c.get('passage_id'): c for c in coverage if isinstance(c, dict)}
        require(len(rows) == len(coverage) and set(rows) == {p['id'] for p in passages}, 'Разбор должен охватывать каждый фрагмент текущей версии, без повторов')
        for p in passages:
            c = rows[p['id']]
            report.strings(c, ('note',), 'review.json.checks.evidence.coverage.' + p['id'])
            require(c.get('verdict') in ('supported', 'editorial', 'opinion') and text(c.get('note')), 'Нет вердикта и обоснования: ' + p['id'])
            ids = c.get('claim_ids', [])
            require(isinstance(ids, list) and all(isinstance(x, str) and x in data['claims'] for x in ids), 'Неверные ссылки в разборе')
            require(set(p['claims']) <= set(ids), 'Не проверены маркеры фрагмента ' + p['id'])
            if p['claims']:
                require(c['verdict'] == 'supported', 'Факт с источником нельзя списать как мнение')
    with report.guard('review.json.checks.reader.sections', 'pottery-style'):
        sections = checks.get('reader', {}).get('sections', {})
        require(isinstance(sections, dict), 'Нет читательской оценки')
        for name in READER_SECTIONS:
            entry = sections.get(name, {})
            require(isinstance(entry, dict) and text(entry.get('note')), 'Нет обоснования раздела ' + name)
            report.strings(entry, ('note',), 'review.json.checks.reader.sections.' + name)
            if name == 'art' and meta['image_policy'] == 'text_only':
                continue
            file = entry.get('file'); excerpt = entry.get('excerpt')
            require(text(excerpt) and file in data['surfaces'] and excerpt in data['surfaces'][file],
                    'Нужен реальный фрагмент статьи/версии для ' + name)
    resolutions = checks.get('reader', {}).get('warning_resolutions', {})
    warnings = [x for x in report.issues if x['level'] == 'warning']
    for warning in warnings:
        resolved = resolutions.get(warning['id']) if isinstance(resolutions, dict) else None
        if not isinstance(resolved, dict) or resolved.get('action') != 'accept_context' or not text(resolved.get('reason')) or PLACEHOLDER.search(normalize(resolved.get('reason', ''))):
            report.add('UNREVIEWED_WARNING', warning['path'], 'Нет мотивированного решения по ' + warning['id'], owner='pottery-style')
    with report.guard('review.json.human_approval', 'owner'):
        approval = review.get('human_approval')
        require(isinstance(approval, dict), 'Нет решения владельца')
        report.strings(approval, ('name',), 'review.json.human_approval')
        require(approval.get('content_hash') == digest and approval.get('public_hash') == rendered_hash, 'Решение относится к другому материалу или превью')
        require(approval.get('review_hash') == review_hash(package), 'Состав отзывов/журнала изменён после решения владельца')
        valid_date(approval.get('date'))
    for channel in meta.get('channels', []):
        path = 'metadata.json.platform_checks.' + channel
        with report.guard(path, 'pottery-growth'):
            item = meta.get('platform_checks', {}).get(channel)
            require(isinstance(item, dict) and item.get('status') == 'pass', 'Не проверена актуальная форма площадки')
            report.strings(item, ('reviewer', 'reference'), path)
            require((date.today() - valid_date(item.get('checked_on'))).days <= 30, 'Проверка формы старше 30 дней')


def check(package, release=False):
    package = Path(package)
    report = Report(); digest = rendered_hash = reviews_hash = None; data = None
    with report.guard(str(package)):
        digest = bundle_hash(package)
        data = inspect_package(package, report)
    with report.guard('review.json'):
        reviews_hash = review_hash(package)
    # Do not render structurally invalid material. Still report independent missing approvals.
    if data:
        if report.ok:
            with report.guard('public/'):
                rendered_hash = payload_hash(public_payload(package, data))
        for cid, c in data['claims'].items():
            for sid in c.get('sources', []) if isinstance(c.get('sources'), list) else []:
                if isinstance(sid, str) and data['sources'].get(sid, {}).get('access') in ('abstract', 'lead'):
                    report.add('SOURCE_DEPTH', 'claims.json.' + cid, 'Нужен полный источник, а не только аннотация',
                               'error' if release else 'warning', 'pottery-research')
        if release and rendered_hash:
            with report.guard('review.json'):
                validate_reviews(package, data, report, digest, rendered_hash)
        elif release:
            report.add('REVIEW_BLOCKED', 'review.json', 'Сначала исправьте структуру; проверка отзывов и выпуска заблокирована')
    return dict(ok=report.ok, mode='release' if release else 'draft', version_hash=digest,
                public_hash=rendered_hash, review_hash=reviews_hash, release_ready=bool(release and report.ok), issues=report.issues)


def initialize(slug, root=ROOT):
    require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) and len(slug) <= 80, 'Неверное имя пакета')
    parent = Path(root) / 'articles'; require(not parent.is_symlink(), 'articles не может быть ссылкой')
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / slug; require(not target.exists() and not target.is_symlink(), 'Пакет уже существует')
    temporary = Path(tempfile.mkdtemp(prefix='.new-', dir=parent))
    try:
        publications = [dict(id='vk-question', channel='vk', format='note', file='vk-question.md',
                             promise='[заполнить обещание]', next_action='[заполнить следующий шаг]')]
        save_json(temporary / 'metadata.json', dict(schema_version=2, title='[заполнить название]', description='[заполнить описание]',
                  primary_query='[заполнить вопрос]', reader_job='[заполнить задачу]', added_value='[заполнить пользу]',
                  author=None, type='guide', risk='normal', profile='note', channels=['vk'], publications=publications,
                  image_policy='text_only', platform_checks={}))
        for name in ('sources', 'claims', 'assets'):
            save_json(temporary / (name + '.json'), [])
        save_json(temporary / 'review.json', dict(checks={}, human_approval=None))
        save_json(temporary / 'workflow.json', dict(revision=0, runs=[]))
        for name in ('article.md', 'vk-question.md'):
            (temporary / name).write_text('# [заполнить]\n', encoding='utf-8')
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True); raise
    return target


def migrate(package, slug, root=ROOT):
    """Copy v1 into a new v2 packet. Never carry approvals or invent missing data."""
    package = Path(package); meta = read_json(package / 'metadata.json')
    require(meta.get('schema_version') == 1, 'Миграция предназначена для схемы 1')
    require(package.is_dir() and not package.is_symlink(), 'Нет обычной папки источника')
    parent = (Path(root) / 'articles').resolve()
    require(parent != package.resolve() and package.resolve() not in parent.parents, 'Нельзя мигрировать внутрь источника')
    target = initialize(slug, root)
    try:
        (target / 'vk-question.md').unlink()  # Remove only our own template, before copying.
        for p in package.rglob('*'):
            require(not p.is_symlink(), 'Миграция не переносит ссылки')
            if p.is_file() and p.relative_to(package).as_posix() not in ('review.json', 'workflow.json'):
                dest = safe_file(target, p.relative_to(package).as_posix()); dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dest)
        meta.update(schema_version=2, profile='research' if meta.get('type') == 'research' else 'standard')
        meta['publications'] = [dict(id=ch + '-main', channel=ch, format='article' if ch == 'livemaster' else 'note',
            file=ch + '.md', promise='[заполнить обещание]', next_action='[заполнить следующий шаг]') for ch in meta['channels']]
        save_json(target / 'metadata.json', meta)
        sources = read_json(target / 'sources.json')
        for source in sources:
            source.setdefault('kind', 'museum' if source.get('access') == 'object' else 'publication')
            source.setdefault('public_label', source.get('title', '[заполнить источник]'))
        save_json(target / 'sources.json', sources)
        return target
    except Exception:
        shutil.rmtree(target, ignore_errors=True); raise


def export_packet(package, release=False, root=ROOT):
    package = Path(package); report = check(package, release)
    require(report['ok'], 'Экспорт заблокирован: ' + json.dumps(report['issues'], ensure_ascii=False))
    data = inspect_package(package, Report()); payload = public_payload(package, data)
    require(payload_hash(payload) == report['public_hash'], 'Публичная версия изменилась во время подготовки')
    destination = Path(root) / 'dist'; require(not destination.is_symlink(), 'dist не может быть ссылкой')
    destination.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^a-zA-Z0-9_-]', '-', package.name)
    target = destination / (name + '-' + report['version_hash'][:12] + '-' + report['review_hash'][:8] + ('-release' if release else '-draft'))
    require(not target.exists() and not target.is_symlink(), 'Экспорт существует; он не перезаписан')
    temporary = Path(tempfile.mkdtemp(prefix='.export-', dir=destination))
    try:
        for name, value in payload.items():
            dest = safe_file(temporary, 'public/' + name); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(value)
        save_json(temporary / 'manifest.json', dict(schema_version=2, content_hash=report['version_hash'],
            review_hash=report['review_hash'], public_hash=report['public_hash'], published=False,
            status='accepted_manual_export' if release else 'draft',
            files={'public/' + k: sha(v) for k, v in payload.items()}))
        current = check(package, release)
        require(current['ok'] and all(current[k] == report[k] for k in ('version_hash', 'public_hash', 'review_hash')), 'Пакет или отзывы изменились во время экспорта')
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True); raise
    return target


def verify_export(directory, package=None):
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), 'Нет обычной папки экспорта')
    m = read_json(directory / 'manifest.json')
    require(isinstance(m, dict) and type(m.get('schema_version')) is int and m['schema_version'] == 2
            and isinstance(m.get('files'), dict) and m['files'], 'Неверный манифест')
    require(m.get('status') in ('draft', 'accepted_manual_export') and m.get('published') is False, 'Неверный статус экспорта')
    for key in ('content_hash', 'public_hash', 'review_hash'):
        require(text(m.get(key)) and re.fullmatch(r'[0-9a-f]{64}', m[key]), 'Неверный хэш ' + key)
    for name, digest in m['files'].items():
        safe_file(directory, name)
        require(name.startswith('public/') and isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest), 'Неверная запись файла')
    actual = {}
    for p in directory.rglob('*'):
        require(not p.is_symlink(), 'Ссылка в экспорте')
        if p.is_file() and p.relative_to(directory).as_posix() != 'manifest.json':
            actual[p.relative_to(directory).as_posix()] = file_hash(p)
    require(actual == m['files'], 'Файлы, подписи или состав экспорта изменились')
    require(sha(canonical({k.removeprefix('public/'): v for k, v in actual.items()})) == m['public_hash'],
            'Публичный хэш не соответствует файлам')
    if package is not None:
        current = check(Path(package), m['status'] == 'accepted_manual_export')
        require(current['ok'] and current['version_hash'] == m['content_hash'] and current['public_hash'] == m['public_hash']
                and current['review_hash'] == m['review_hash'], 'Экспорт не соответствует исходному пакету и его приёмке')
    return dict(ok=True, status=m['status'], published=False, source_checked=package is not None)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Редакционный пакет: проверка, превью и ручной экспорт')
    parser.add_argument('command', choices=('init', 'migrate', 'check', 'status', 'digest', 'inventory', 'route', 'export', 'verify-export'))
    parser.add_argument('target'); parser.add_argument('--release', action='store_true')
    parser.add_argument('--new-slug'); parser.add_argument('--package')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            print(initialize(args.target)); return 0
        if args.command == 'migrate':
            require(args.new_slug, 'Укажите --new-slug'); print(migrate(args.target, args.new_slug)); return 0
        if args.command == 'export':
            print(export_packet(args.target, args.release)); return 0
        if args.command == 'verify-export':
            result = verify_export(args.target, args.package)
        elif args.command == 'route':
            result = route(read_json(Path(args.target) / 'metadata.json'))
        elif args.command == 'inventory':
            report = Report(); data = inspect_package(Path(args.target), report)
            require(report.ok, json.dumps(report.issues, ensure_ascii=False)); result = inventory(data['surfaces'])
        else:
            result = check(args.target, args.release or args.command == 'status')
            if args.command == 'digest':
                result = {k: result[k] for k in ('ok', 'version_hash', 'public_hash', 'review_hash', 'issues')}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(result, dict) and result.get('ok') is False else 0
    except (Invalid, OSError, ValueError, TypeError, KeyError) as exc:
        print('Ошибка: ' + str(exc), file=sys.stderr); return 2


if __name__ == '__main__':
    sys.exit(main())
