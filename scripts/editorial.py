#!/usr/bin/env python3
"""Offline editorial checks and file export. Python 3.11+, standard library only.

This validates declarations and review freshness, not factual truth or identity.
It deliberately has no approval, login, network, or social publishing command.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = ('vk', 'livemaster')
CHECKS = ('evidence', 'science', 'style', 'art', 'seo', 'channels')
POLICY = ('AGENTS.md', 'AUTOR_STYLE.md', 'docs/QUALITY.md', 'docs/RESEARCH.md',
          'docs/ART_DIRECTION.md', 'docs/DISTRIBUTION.md', 'scripts/editorial.py')
MAX_TEXT = 2 * 1024 * 1024
SLOP = {
    'S01': r'в (?:современном )?мире,? где',
    'S02': r'не просто[^.!?\n]{0,90}(?:а |это )',
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
    value = ''.join(c for c in value if unicodedata.category(c) != 'Cf')
    return re.sub(r'\s+', ' ', value)


def safe_file(root, name):
    require(text(name) and '\\' not in name, 'Некорректный относительный путь')
    p = PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts, 'Выход за пределы пакета')
    candidate = root.joinpath(*p.parts)
    require(not candidate.is_symlink(), 'Символические ссылки запрещены')
    require(root.resolve() in candidate.resolve().parents, 'Путь вне пакета')
    return candidate


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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def valid_date(value):
    require(text(value) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'Нужна дата YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    require(parsed <= date.today(), 'Дата проверки находится в будущем')
    return parsed


def url_ok(value):
    if not text(value):
        return False
    if re.search(r'[\s<>()"\\]', value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc) and parsed.username is None


def objects(value, name):
    require(isinstance(value, list), name + ': ожидается массив')
    require(all(isinstance(x, dict) for x in value), name + ': элементы должны быть объектами')
    ids = [x.get('id') for x in value]
    require(all(text(x) and re.fullmatch(r'[A-Z][A-Z0-9_-]{0,39}', x) for x in ids),
            name + ': неверный идентификатор')
    require(len(ids) == len(set(ids)), name + ': повтор идентификатора')
    return {x['id']: x for x in value}


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def raster_header(path):
    """Check a raster signature only; full visual/decoder review remains manual."""
    with path.open('rb') as stream:
        head = stream.read(32)
    suffix = path.suffix.lower()
    if suffix == '.png':
        return (head.startswith(b'\x89PNG\r\n\x1a\n') and len(head) >= 24
                and head[12:16] == b'IHDR' and int.from_bytes(head[16:20], 'big') > 0
                and int.from_bytes(head[20:24], 'big') > 0)
    if suffix in ('.jpg', '.jpeg'):
        return head.startswith(b'\xff\xd8\xff')
    return suffix == '.webp' and head[:4] == b'RIFF' and head[8:12] == b'WEBP'


def bundle_hash(package):
    package = Path(package)
    require(package.is_dir() and not package.is_symlink(), 'Нет обычной папки пакета')
    items = []
    for p in sorted(package.rglob('*')):
        require(not p.is_symlink(), 'Символические ссылки запрещены: ' + str(p))
        if p.is_file() and p.relative_to(package).as_posix() != 'review.json':
            items.append((p.relative_to(package).as_posix(), file_hash(p)))
    require(items, 'Пакет пуст')
    policies = [(name, file_hash(ROOT / name)) for name in POLICY]
    raw = json.dumps({'files': items, 'policy': policies}, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def lint(value, path):
    issues = []
    normalized = normalize(value)
    for code, pattern in SLOP.items():
        for match in re.finditer(pattern, normalized):
            issues.append({'level': 'error', 'code': code, 'path': path,
                           'message': 'Редакционный шаблон; требуется содержательная правка',
                           'excerpt': match.group(0)[:180]})
    if re.search(r'\b(?:todo|tbd)\b|\[(?:заполнить|вставить|уточнить)', normalized):
        issues.append({'level': 'error', 'code': 'TEMPLATE', 'path': path,
                       'message': 'Незаполненное поле'})
    for paragraph in re.split(r'\n\s*\n', value):
        if len(paragraph.split()) > 130:
            issues.append({'level': 'warning', 'code': 'RHYTHM', 'path': path,
                           'message': 'Длинный абзац: проверить ход мысли, не резать автоматически'})
    return issues


def check(package, release=False):
    """Return a fail-closed, JSON-serializable report; never mutate the package."""
    package = Path(package)
    issues = []
    digest = None
    def issue(code, message, level='error', path=''):
        issues.append(dict(level=level, code=code, path=path, message=message))
    try:
        digest = bundle_hash(package)
        meta = read_json(package / 'metadata.json')
        require(isinstance(meta, dict), 'metadata.json: ожидается объект')
        require(meta.get('schema_version') == 1 and type(meta.get('schema_version')) is int,
                'Неизвестная версия схемы')
        for key in ('title', 'description', 'primary_query', 'reader_job', 'added_value'):
            require(text(meta.get(key)), 'metadata.json: не заполнено ' + key)
        require(meta.get('type') in ('research', 'guide', 'studio'), 'Неизвестный тип статьи')
        require(meta.get('risk') in ('normal', 'elevated'), 'Неизвестный уровень риска')
        require(meta.get('image_policy') in ('text_only', 'illustrated'), 'Неизвестная политика изображений')
        channels = meta.get('channels')
        require(isinstance(channels, list) and channels and all(x in CHANNELS for x in channels),
                'channels: нужен непустой список поддерживаемых каналов')
        require(len(set(channels)) == len(channels), 'Повтор канала')
        sources = objects(read_json(package / 'sources.json'), 'sources')
        claims = objects(read_json(package / 'claims.json'), 'claims')
        assets = objects(read_json(package / 'assets.json'), 'assets')
        require(sources and claims, 'Нужны источники и проверяемые утверждения')
        for sid, source in sources.items():
            require(all(text(source.get(k)) for k in ('title', 'language')), sid + ': неполный источник')
            require(url_ok(source.get('url')), sid + ': неверный URL источника')
            require(source.get('access') in ('fulltext', 'object', 'abstract', 'lead'), sid + ': неверный доступ')
            valid_date(source.get('checked_on'))
        for cid, claim in claims.items():
            require(all(text(claim.get(k)) for k in ('text', 'locator', 'scope')), cid + ': неполная запись')
            require(claim.get('status') == 'verified', cid + ': утверждение не проверено исследователем')
            refs = claim.get('sources')
            require(isinstance(refs, list) and refs and all(isinstance(x, str) and x in sources for x in refs),
                    cid + ': отсутствующий источник')
            require(len(set(refs)) == len(refs), cid + ': повтор источника')
            if any(sources[s]['access'] not in ('fulltext', 'object') for s in refs):
                issue('SOURCE_DEPTH', cid + ': доступна только аннотация или поисковая зацепка',
                      'error' if release else 'warning')
            if any(sources[s]['language'] in ('ja', 'zh') for s in refs):
                require(claim.get('translation_checked') is True, cid + ': перевод не проверен')
        surfaces = [('metadata.title', meta['title']), ('metadata.description', meta['description'])]
        article = read_text(package / 'article.md')
        require(len(article.strip()) >= 80, 'Статья пуста или не заполнена')
        headings = re.findall(r'^# (.+)$', article, re.MULTILINE)
        require(headings == [meta['title']], 'Нужен один H1, совпадающий с названием')
        surfaces.append(('article.md', article))
        for channel in channels:
            value = read_text(package / (channel + '.md'))
            require(len(value.strip()) >= 40, channel + ': версия пуста')
            surfaces.append((channel + '.md', value))
        if meta['image_policy'] == 'illustrated':
            require(assets, 'Иллюстрированный материал не содержит изображений')
        if meta['image_policy'] == 'text_only':
            require(not assets, 'Для изображений установите image_policy=illustrated')
        asset_files = set()
        for aid, asset in assets.items():
            require(all(text(asset.get(k)) for k in ('file', 'creator', 'rights', 'rights_reference', 'caption', 'alt')),
                    aid + ': нет подписи, альтернативного текста или сведений о правах')
            require(asset.get('kind') in ('photograph', 'diagram', 'generated'), aid + ': неверный тип изображения')
            require(type(asset.get('documentary')) is bool, aid + ': documentary должен быть true/false')
            path = safe_file(package, asset['file'])
            require(path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'), aid + ': нет растрового изображения')
            require(asset['file'] not in asset_files, aid + ': повтор файла изображения')
            asset_files.add(asset['file'])
            require(raster_header(path), aid + ': неверная сигнатура изображения')
            if asset['kind'] == 'generated':
                require(not asset['documentary'], aid + ': ИИ не может быть документальным свидетельством')
                require('иллюстрация создана ии' in normalize(asset['caption']), aid + ': нужна маркировка ИИ')
            if asset['kind'] == 'diagram':
                require(not asset['documentary'] and 'схема' in normalize(asset['caption']), aid + ': схема должна быть обозначена')
            surfaces.extend([(aid + '.caption', asset['caption']), (aid + '.alt', asset['alt'])])
        used = set()
        illustrated = set()
        for path, value in surfaces:
            issues.extend(lint(value, path))
            require(not re.search(r'<\s*/?\s*[A-Za-z][^>]*>', value), path + ': HTML в публикации не поддерживается')
            images = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', value)
            require(value.count('![') == len(images), path + ': неподдерживаемая ссылка на изображение')
            for alternative, filename in images:
                require(filename in asset_files, path + ': изображение отсутствует в реестре прав')
                asset = next(a for a in assets.values() if a['file'] == filename)
                require(alternative == asset['alt'], path + ': alt не совпадает с принятым реестром')
                illustrated.add(filename)
            refs = re.findall(r'\[\[([^\]\n]+)\]\]', value)
            for cid in refs:
                require(cid in claims, path + ': неизвестный маркер ' + cid)
                used.add(cid)
        require(illustrated == asset_files, 'Не все изображения привязаны к тексту')
        require(used, 'Нет ссылок [[C1]] на проверяемые утверждения')
        for cid in set(claims) - used:
            issue('UNUSED_CLAIM', cid + ': запись не используется', 'warning')
        if len(meta['title']) > 110:
            issue('TITLE_LENGTH', 'Длинный заголовок: проверить читаемость; это не лимит площадки', 'warning')
        review = read_json(package / 'review.json')
        require(isinstance(review, dict), 'review.json: ожидается объект')
        if release:
            require(text(meta.get('author')), 'Перед выпуском нужно подтверждённое имя автора')
            require(review.get('version_hash') == digest, 'Отзывы отсутствуют или относятся к другой версии')
            checks = review.get('checks')
            require(isinstance(checks, dict), 'Нет проверок редакции')
            for role in CHECKS:
                item = checks.get(role)
                require(isinstance(item, dict), 'Нет отзыва: ' + role)
                require(text(item.get('reviewer')) and text(item.get('notes')), 'Нет автора/основания отзыва: ' + role)
                allowed = {'pass'}
                if role == 'science' and meta['type'] != 'research' and meta['risk'] == 'normal':
                    allowed.add('not_applicable')
                require(item.get('status') in allowed, 'Проверка не принята: ' + role)
            require(normalize(checks['evidence']['reviewer']) != normalize(meta['author']),
                    'Автор не может быть единственным проверяющим факты')
            approval = review.get('human_approval')
            require(isinstance(approval, dict) and text(approval.get('name')), 'Нет решения владельца')
            require(approval.get('version_hash') == digest, 'Решение владельца устарело')
            valid_date(approval.get('date'))
            platform = meta.get('platform_checks')
            require(isinstance(platform, dict), 'Нет проверки актуальных форм площадок')
            for channel in channels:
                item = platform.get(channel)
                require(isinstance(item, dict) and item.get('status') == 'pass', 'Не проверена форма: ' + channel)
                require(text(item.get('reviewer')) and text(item.get('reference')), 'Нет основания проверки: ' + channel)
                require((date.today() - valid_date(item.get('checked_on'))).days <= 30,
                        'Проверка площадки старше 30 дней: ' + channel)
    except (Invalid, OSError, ValueError, TypeError, KeyError) as exc:
        issue('CONTRACT', str(exc))
    ok = not any(x['level'] == 'error' for x in issues)
    return {'ok': ok, 'mode': 'release' if release else 'draft', 'version_hash': digest,
            'release_ready': bool(ok and release), 'issues': issues}


def initialize(slug, root=ROOT):
    require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) and len(slug) <= 80, 'Неверное имя пакета')
    parent = Path(root) / 'articles'
    require(not parent.is_symlink(), 'Папка articles не может быть ссылкой')
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / slug
    require(not target.exists() and not target.is_symlink(), 'Пакет уже существует; перезапись запрещена')
    temporary = Path(tempfile.mkdtemp(prefix='.new-', dir=parent))
    try:
        save_json(temporary / 'metadata.json', dict(schema_version=1, title='[заполнить название]',
                  description='[заполнить описание]', primary_query='[заполнить запрос]',
                  reader_job='[заполнить задачу]', added_value='[заполнить пользу]', author=None,
                  type='guide', risk='normal', channels=list(CHANNELS), image_policy='text_only', platform_checks={}))
        for name in ('sources', 'claims', 'assets'):
            save_json(temporary / (name + '.json'), [])
        save_json(temporary / 'review.json', dict(version_hash=None, checks={}, human_approval=None))
        for name in ('article', 'vk', 'livemaster', 'art-brief'):
            (temporary / (name + '.md')).write_text('# [заполнить]\n', encoding='utf-8')
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def export_packet(package, release=False, root=ROOT):
    package = Path(package)
    report = check(package, release)
    require(report['ok'], 'Экспорт заблокирован: ' + json.dumps(report['issues'], ensure_ascii=False))
    meta = read_json(package / 'metadata.json')
    sources = {s['id']: s for s in read_json(package / 'sources.json')}
    claims = {c['id']: c for c in read_json(package / 'claims.json')}
    def cite(match):
        cid = match.group(1)
        return ' '.join('[Источник ' + cid + ': ' + sid + '](' + sources[sid]['url'] + ')'
                        for sid in claims[cid]['sources'])
    destination = Path(root) / 'dist'
    require(not destination.is_symlink(), 'Папка dist не может быть ссылкой')
    destination.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', package.name)
    target = destination / (safe_name + '-' + report['version_hash'][:12] + ('-release' if release else '-draft'))
    require(not target.exists() and not target.is_symlink(), 'Такой экспорт уже существует; он не перезаписан')
    temporary = Path(tempfile.mkdtemp(prefix='.export-', dir=destination))
    try:
        label = 'ПРИНЯТО ДЛЯ РУЧНОГО РАЗМЕЩЕНИЯ' if release else 'ЧЕРНОВИК — НЕ ПУБЛИКОВАТЬ'
        for name in ('article', *meta['channels']):
            body = read_text(package / (name + '.md'))
            body = re.sub(r'\[\[([^\]\n]+)\]\]', cite, body)
            (temporary / (name + '.md')).write_text(label + '\n\n' + body, encoding='utf-8')
        def rendered(value):
            if isinstance(value, str):
                return re.sub(r'\[\[([^\]\n]+)\]\]', cite, value)
            if isinstance(value, list):
                return [rendered(x) for x in value]
            if isinstance(value, dict):
                return {k: rendered(v) for k, v in value.items()}
            return value
        save_json(temporary / 'metadata.json', rendered(meta))
        save_json(temporary / 'assets.json', rendered(read_json(package / 'assets.json')))
        evidence = temporary / 'evidence'
        evidence.mkdir()
        for name in ('sources.json', 'claims.json', 'review.json'):
            shutil.copyfile(package / name, evidence / name)
        for asset in read_json(package / 'assets.json'):
            dest = safe_file(temporary, asset['file'])
            dest.parent.mkdir(parents=True, exist_ok=True)
            require(not dest.exists(), 'Изображение конфликтует с файлом экспорта')
            shutil.copyfile(safe_file(package, asset['file']), dest)
        save_json(temporary / 'manifest.json', dict(version_hash=report['version_hash'],
                  status='accepted_manual_export' if release else 'draft', published=False,
                  files={p.relative_to(temporary).as_posix(): file_hash(p) for p in temporary.rglob('*') if p.is_file()}))
        require(bundle_hash(package) == report['version_hash'], 'Пакет изменился во время экспорта')
        require(check(package, release)['ok'], 'Приёмка изменилась во время экспорта')
        temporary.rename(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='Проверка и ручной экспорт редакционного пакета')
    parser.add_argument('command', choices=('init', 'check', 'digest', 'export'))
    parser.add_argument('target', help='Имя нового пакета или путь существующего')
    parser.add_argument('--release', action='store_true', help='Требовать свежую приёмку человеком')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            print(initialize(args.target))
        elif args.command == 'digest':
            print(bundle_hash(Path(args.target)))
        elif args.command == 'export':
            print(export_packet(Path(args.target), args.release))
        else:
            result = check(Path(args.target), args.release)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['ok'] else 1
    except (Invalid, OSError, ValueError, TypeError) as exc:
        print('Ошибка: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
