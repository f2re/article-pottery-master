"""Synthetic approvals exist only in temporary test folders, never in articles/."""
import base64
import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('editorial', ROOT / 'scripts/editorial.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.p = self.root / 'sample'
        shutil.copytree(ROOT / 'articles/glaze-and-tea', self.p)

    def tearDown(self):
        self.temp.cleanup()

    def get(self, filename):
        return e.read_json(self.p / filename)

    def put(self, filename, value):
        e.save_json(self.p / filename, value)

    def ready_metadata(self):
        meta = self.get('metadata.json')
        meta['author'] = 'Тестовый автор'
        meta['platform_checks'] = {ch: dict(status='pass', reviewer='Тестовая фикстура',
            reference='Только проверка программы, не реальная приёмка', checked_on=date.today().isoformat())
            for ch in e.CHANNELS}
        self.put('metadata.json', meta)

    def approve_fixture(self):
        digest = e.bundle_hash(self.p)
        self.put('review.json', dict(version_hash=digest,
            checks={r: dict(status='pass', reviewer='Тестовый проверяющий', notes='Синтетическая тестовая фикстура') for r in e.CHECKS},
            human_approval=dict(name='Фикстура, не человек', date=date.today().isoformat(), version_hash=digest)))

    def test_draft_valid_and_not_release_ready(self):
        result = e.check(self.p)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['release_ready'])

    def test_real_sample_not_approved(self):
        self.assertIsNone(self.get('review.json')['human_approval'])
        self.assertFalse(e.check(self.p, True)['ok'])

    def test_synthetic_release_positive(self):
        self.ready_metadata(); self.approve_fixture()
        self.assertTrue(e.check(self.p, True)['release_ready'])

    def test_stale_review_after_every_surface_changes(self):
        for name in ('article.md', 'vk.md', 'livemaster.md', 'art-brief.md'):
            with self.subTest(name=name):
                self.ready_metadata(); self.approve_fixture()
                path = self.p / name
                old = path.read_text()
                path.write_text(old + '\nДополнительное пояснение.\n')
                self.assertFalse(e.check(self.p, True)['ok'])
                path.write_text(old)

    def test_metadata_change_invalidates_review(self):
        self.ready_metadata(); self.approve_fixture()
        m = self.get('metadata.json'); m['description'] += ' Дополнение.'
        self.put('metadata.json', m)
        self.assertFalse(e.check(self.p, True)['ok'])

    def test_untracked_file_is_in_hash(self):
        old = e.bundle_hash(self.p)
        (self.p / 'new-note.txt').write_text('Запись')
        self.assertNotEqual(old, e.bundle_hash(self.p))

    def test_policy_is_in_hash(self):
        before = e.bundle_hash(self.p)
        with patch.object(e, 'POLICY', e.POLICY + ('GEMINI.md',)):
            self.assertNotEqual(before, e.bundle_hash(self.p))

    def test_reviews_excluded_from_content_hash(self):
        old = e.bundle_hash(self.p)
        self.put('review.json', dict(version_hash=None, checks={}, human_approval=None, note='Пока не принято'))
        self.assertEqual(old, e.bundle_hash(self.p))

    def test_json_types_fail_closed(self):
        for value in ([], None, 'metadata', {'schema_version': True}):
            with self.subTest(value=value):
                self.put('metadata.json', value)
                self.assertFalse(e.check(self.p)['ok'])

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        for value in ('{"title":"a","title":"b"}', '{"n":NaN}', '{bad'):
            with self.subTest(value=value):
                (self.p / 'metadata.json').write_text(value)
                self.assertFalse(e.check(self.p)['ok'])

    def test_missing_required_file(self):
        (self.p / 'vk.md').unlink()
        self.assertFalse(e.check(self.p)['ok'])

    def test_missing_claims_and_duplicate_ids(self):
        claims = self.get('claims.json')
        for value in ([], [claims[0], claims[0]], 'C1'):
            self.put('claims.json', value)
            self.assertFalse(e.check(self.p)['ok'])

    def test_unknown_citation_in_metadata(self):
        m = self.get('metadata.json'); m['description'] += ' [[C999]]'
        self.put('metadata.json', m)
        self.assertFalse(e.check(self.p)['ok'])

    def test_unknown_source(self):
        c = self.get('claims.json'); c[0]['sources'] = ['S999']
        self.put('claims.json', c)
        self.assertFalse(e.check(self.p)['ok'])

    def test_invalid_source_url(self):
        s = self.get('sources.json'); s[0]['url'] = 'javascript:alert(1)'
        self.put('sources.json', s)
        self.assertFalse(e.check(self.p)['ok'])

    def test_abstract_is_not_release_evidence(self):
        s = self.get('sources.json'); s[0]['access'] = 'abstract'
        self.put('sources.json', s)
        self.assertTrue(e.check(self.p)['ok'])
        self.ready_metadata(); self.approve_fixture()
        result = e.check(self.p, True)
        self.assertFalse(result['ok'])
        self.assertIn('SOURCE_DEPTH', [x['code'] for x in result['issues']])

    def test_translation_required_for_ja_and_zh(self):
        for language in ('ja', 'zh'):
            s = self.get('sources.json'); s[0]['language'] = language
            self.put('sources.json', s)
            c = self.get('claims.json'); c[0]['translation_checked'] = False
            self.put('claims.json', c)
            self.assertFalse(e.check(self.p)['ok'])

    def test_future_source_date_rejected(self):
        s = self.get('sources.json'); s[0]['checked_on'] = (date.today() + timedelta(days=1)).isoformat()
        self.put('sources.json', s)
        self.assertFalse(e.check(self.p)['ok'])

    def test_science_required_for_research(self):
        self.ready_metadata(); self.approve_fixture()
        r = self.get('review.json'); r['checks']['science']['status'] = 'not_applicable'
        self.put('review.json', r)
        self.assertFalse(e.check(self.p, True)['ok'])

    def test_same_author_and_verifier_rejected(self):
        self.ready_metadata(); self.approve_fixture()
        r = self.get('review.json'); r['checks']['evidence']['reviewer'] = 'Тестовый автор'
        self.put('review.json', r)
        self.assertFalse(e.check(self.p, True)['ok'])

    def test_review_needs_reason(self):
        self.ready_metadata(); self.approve_fixture()
        r = self.get('review.json'); r['checks']['style']['notes'] = ''
        self.put('review.json', r)
        self.assertFalse(e.check(self.p, True)['ok'])

    def test_platform_check_expires(self):
        self.ready_metadata()
        m = self.get('metadata.json')
        m['platform_checks']['vk']['checked_on'] = (date.today() - timedelta(days=31)).isoformat()
        self.put('metadata.json', m); self.approve_fixture()
        self.assertFalse(e.check(self.p, True)['ok'])

    def test_slop_on_all_text_surfaces(self):
        for name in ('vk.md', 'livemaster.md', 'article.md'):
            path = self.p / name; original = path.read_text()
            path.write_text(original + '\nИдеальный подарок.\n')
            self.assertFalse(e.check(self.p)['ok'])
            path.write_text(original)
        m = self.get('metadata.json'); m['description'] = 'Уникальный дизайн'
        self.put('metadata.json', m)
        self.assertFalse(e.check(self.p)['ok'])

    def test_normalization_and_linebreaks(self):
        for value in ('УНИКАЛЬНЫЙ\nДИЗАЙН', 'уникальный\u00a0дизайн', 'уника\u200bльный дизайн'):
            self.assertTrue(e.lint(value, 'test'))

    def test_not_an_ai_detector_or_word_ban(self):
        self.assertEqual(e.lint('Этот объект является музейным экспонатом.', 'test'), [])

    def test_unregistered_images_and_html_rejected(self):
        path = self.p / 'vk.md'; original = path.read_text()
        for value in ('![Предмет](https://example.org/photo.jpg)', '![Предмет][img]', '<img src="x">'):
            path.write_text(original + '\n' + value)
            self.assertFalse(e.check(self.p)['ok'])

    def add_asset(self):
        m = self.get('metadata.json'); m['image_policy'] = 'illustrated'
        self.put('metadata.json', m)
        (self.p / 'image.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII='))
        self.put('assets.json', [dict(id='A1', file='image.png', kind='photograph', documentary=True,
            creator='Тест', rights='Тестовая фикстура', rights_reference='Не реальная лицензия',
            caption='Тестовый предмет', alt='Предмет')])
        p = self.p / 'article.md'; p.write_text(p.read_text() + '\n![Предмет](image.png)\n')

    def test_asset_contract_and_bytes_are_hashed(self):
        self.add_asset()
        self.assertTrue(e.check(self.p)['ok'])
        self.ready_metadata(); self.approve_fixture()
        (self.p / 'image.png').write_bytes(b'changed')
        self.assertFalse(e.check(self.p, True)['ok'])

    def test_invalid_raster_signature(self):
        self.add_asset()
        (self.p / 'image.png').write_bytes(b'not an image')
        self.assertFalse(e.check(self.p)['ok'])

    def test_generated_cannot_be_documentary(self):
        self.add_asset()
        a = self.get('assets.json'); a[0]['kind'] = 'generated'
        self.put('assets.json', a)
        self.assertFalse(e.check(self.p)['ok'])

    def test_generated_needs_label(self):
        self.add_asset()
        a = self.get('assets.json'); a[0].update(kind='generated', documentary=False)
        self.put('assets.json', a)
        self.assertFalse(e.check(self.p)['ok'])
        a[0]['caption'] = 'Иллюстрация создана ИИ. Условный предмет.'
        self.put('assets.json', a)
        self.assertTrue(e.check(self.p)['ok'])

    def test_missing_rights_and_alt_mismatch(self):
        self.add_asset()
        original = self.get('assets.json')
        for field, value in (('rights_reference', ''), ('alt', 'Другой текст')):
            a = json.loads(json.dumps(original)); a[0][field] = value
            self.put('assets.json', a)
            self.assertFalse(e.check(self.p)['ok'])

    def test_path_traversal_rejected(self):
        for name in ('../secret.png', '/etc/passwd', '..\\secret.png'):
            with self.assertRaises(e.Invalid):
                e.safe_file(self.p, name)

    def test_symlink_rejected(self):
        (self.p / 'outside').symlink_to(self.root)
        self.assertFalse(e.check(self.p)['ok'])

    def test_init_refuses_bad_names_and_existing_package(self):
        for value in ('../escape', '', 'two words', 'X', 'a' * 81):
            with self.assertRaises(e.Invalid):
                e.initialize(value, self.root)
        path = e.initialize('new-article', self.root)
        before = e.read_json(path / 'review.json')
        self.assertFalse(e.check(path)['ok'])
        with self.assertRaises(e.Invalid):
            e.initialize('new-article', self.root)
        self.assertEqual(before, e.read_json(path / 'review.json'))

    def test_draft_export_marked_and_not_published(self):
        out = e.export_packet(self.p, root=self.root)
        body = (out / 'vk.md').read_text()
        self.assertTrue(body.startswith('ЧЕРНОВИК'))
        self.assertNotIn('[[C1]]', body)
        manifest = e.read_json(out / 'manifest.json')
        self.assertFalse(manifest['published'])
        for name, digest in manifest['files'].items():
            self.assertEqual(digest, e.file_hash(out / name))
        with self.assertRaises(e.Invalid):
            e.export_packet(self.p, root=self.root)

    def test_export_resolves_metadata_citations(self):
        m = self.get('metadata.json'); m['description'] += ' [[C1]]'
        self.put('metadata.json', m)
        out = e.export_packet(self.p, root=self.root)
        self.assertNotIn('[[C1]]', e.read_json(out / 'metadata.json')['description'])
        self.assertTrue((out / 'evidence/sources.json').is_file())

    def test_release_export_blocked_without_approval(self):
        with self.assertRaises(e.Invalid):
            e.export_packet(self.p, release=True, root=self.root)
        self.assertFalse((self.root / 'dist').exists())

    def test_release_export_positive_fixture(self):
        self.ready_metadata(); self.approve_fixture()
        out = e.export_packet(self.p, release=True, root=self.root)
        self.assertEqual(e.read_json(out / 'manifest.json')['status'], 'accepted_manual_export')
        self.assertFalse(e.read_json(out / 'manifest.json')['published'])


class RepositoryTests(unittest.TestCase):
    def test_skill_names_and_frontmatter(self):
        skills = list((ROOT / '.agents/skills').glob('*/SKILL.md'))
        self.assertEqual(len(skills), 9)
        for path in skills:
            value = path.read_text()
            self.assertTrue(value.startswith('---\nname: ' + path.parent.name + '\n'))
            self.assertIn('\ndescription: ', value)
            self.assertIn('AGENTS.md', value)

    def test_plan_sources_and_calendar(self):
        plan = e.read_json(ROOT / 'editorial/plan.json')
        topics = {x['id']: x for x in plan['topics']}
        sources = {s['id'] for s in e.read_json(ROOT / 'research/sources.json')}
        self.assertEqual(len(topics), 24)
        self.assertEqual(len(plan['calendar']), 12)
        for item in plan['calendar']:
            self.assertIn(item['topic'], topics)
            date.fromisoformat(item['week_of'])
        for topic in topics.values():
            self.assertIsNone(topic['query_volume'])
            self.assertTrue(set(topic['sources']) <= sources)
            self.assertTrue(set(topic['related']) <= set(topics))
            self.assertNotIn(topic['id'], topic['related'])


if __name__ == '__main__':
    unittest.main()
