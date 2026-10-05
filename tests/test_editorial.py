"""Regression tests. All approvals and personal records are synthetic temp fixtures."""
import base64
import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('editorial', ROOT / 'scripts/editorial.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.p = self.root / 'sample'
        shutil.copytree(ROOT / 'articles/glaze-and-tea', self.p)

    def tearDown(self):
        self.temp.cleanup()

    def get(self, name):
        return e.read_json(self.p / name)

    def put(self, name, value):
        e.save_json(self.p / name, value)

    def append(self, name, value):
        p = self.p / name
        p.write_text(p.read_text() + '\n\n' + value + '\n')

    def codes(self, release=False):
        return {i['code'] for i in e.check(self.p, release)['issues']}

    def approve_fixture(self):
        """Not a real person or run. Never called against committed article folders."""
        meta = self.get('metadata.json')
        meta['author'] = 'Тестовый автор'
        meta['platform_checks'] = {c: dict(status='pass', reviewer='Синтетическая фикстура',
            reference='Тест программы, не реальная проверка формы', checked_on=date.today().isoformat()) for c in meta['channels']}
        self.put('metadata.json', meta)
        roles = ['writer', 'growth'] + (['art'] if meta['image_policy'] == 'illustrated' else []) + e.route(meta)['required_reviews']
        workflow = dict(revision=0, runs=[dict(id='fixture-' + r, role=r, actor_id='actor-' + r,
            mode='independent', date=date.today().isoformat(), notes='Синтетическая фикстура, не запуск агента') for r in roles])
        self.put('workflow.json', workflow)
        result = e.check(self.p)
        self.assertTrue(result['ok'], result)
        data = e.inspect_package(self.p, e.Report())
        checks = {r: dict(status='pass', reviewer='Тестовый проверяющий ' + r, actor_id='actor-' + r,
            run_id='fixture-' + r, notes='Только синтетическая проверка контракта',
            content_hash=result['version_hash'], public_hash=result['public_hash']) for r in e.route(meta)['required_reviews']}
        checks['evidence']['coverage'] = [dict(passage_id=p['id'], verdict='supported' if p['claims'] else 'editorial',
            claim_ids=p['claims'], note='Синтетическое обоснование фикстуры') for p in e.inventory(data['surfaces'])]
        checks['reader']['sections'] = {r: dict(file='article.md', excerpt=data['surfaces']['article.md'].split('\n')[0],
            note='Синтетический отзыв, не смысловая приёмка') for r in e.READER_SECTIONS}
        checks['reader']['warning_resolutions'] = {i['id']: dict(action='accept_context', reason='Синтетическое решение теста')
                                                    for i in result['issues'] if i['level'] == 'warning'}
        review = dict(checks=checks, human_approval=None)
        self.put('review.json', review)
        review['human_approval'] = dict(name='Фикстура, не человек', date=date.today().isoformat(),
            content_hash=result['version_hash'], public_hash=result['public_hash'], review_hash=e.review_hash(self.p))
        self.put('review.json', review)
        self.assertTrue(e.check(self.p, True)['ok'], e.check(self.p, True))

    def add_asset(self, kind='photograph'):
        meta = self.get('metadata.json'); meta['image_policy'] = 'illustrated'; self.put('metadata.json', meta)
        (self.p / 'media').mkdir(exist_ok=True)
        (self.p / 'media/fixture.png').write_bytes(PNG)
        caption = {'photograph': 'Тестовый предмет', 'diagram': 'Условная схема',
                   'generated': 'Иллюстрация создана ИИ. Условный предмет.'}[kind]
        self.put('assets.json', [dict(id='A1', file='media/fixture.png', kind=kind, documentary=kind == 'photograph',
            creator='Фикстура', rights='Тест', rights_reference='Синтетическая запись прав',
            public_credit='Автор изображения: тестовая фикстура.', caption=caption, alt='Условный предмет')])
        self.append('article.md', '![Условный предмет](media/fixture.png)')

    def add_local_source(self, visibility='private'):
        folder = '.private' if visibility == 'private' else 'evidence'
        (self.p / folder).mkdir(exist_ok=True)
        path = self.p / folder / 'interview.txt'
        path.write_text('PRIVATE_FIXTURE_ORIGINAL — закрытая тестовая запись, не реальная переписка.')
        sources = self.get('sources.json')
        sources.append(dict(id='LOCAL1', title='Синтетическое интервью', public_label='Согласованная заметка мастерской',
            kind='interview', language='ru', access='local', file=folder+'/interview.txt', sha256=e.file_hash(path),
            visibility=visibility, creator='Тестовый собеседник', protocol='Протокол тестовой записи',
            consent_reference='Разрешена только публичная формулировка фикстуры', recorded_on=date.today().isoformat(),
            checked_on=date.today().isoformat()))
        self.put('sources.json', sources)
        claims=self.get('claims.json');claims.append(dict(id='L1', text='Синтетическое утверждение для испытания',
            sources=['LOCAL1'], locator='Тестовый фрагмент', scope='Тест, не публикация', status='verified'))
        self.put('claims.json', claims)
        self.append('article.md', 'Фрагмент с согласованным публичным пересказом для теста. [[L1]]')
        return path

    def test_draft_is_valid_not_approved(self):
        r=e.check(self.p);self.assertTrue(r['ok']);self.assertFalse(r['release_ready'])
        self.assertIsNone(self.get('review.json')['human_approval'])
        self.assertFalse(e.check(self.p, True)['ok'])

    def test_release_fixture_valid(self):
        self.approve_fixture();self.assertTrue(e.check(self.p, True)['release_ready'])

    def test_sample_has_two_distinct_vk_posts(self):
        pubs=self.get('metadata.json')['publications'];vk=[p for p in pubs if p['channel']=='vk']
        self.assertEqual(len(vk),2);self.assertNotEqual((self.p/vk[0]['file']).read_text(), (self.p/vk[1]['file']).read_text())

    def test_changes_in_each_publication_invalidate_all_reviews(self):
        for name in ('article.md','vk-question.md','vk-detail.md','livemaster.md'):
            with self.subTest(name=name):
                self.approve_fixture();old=(self.p/name).read_text();self.append(name,'Уточнение текста.')
                self.assertFalse(e.check(self.p,True)['ok']);(self.p/name).write_text(old)

    def test_metadata_change_invalidates_review(self):
        self.approve_fixture();m=self.get('metadata.json');m['description']+=' Дополнение.';self.put('metadata.json',m)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_review_edit_invalidates_owner_not_content(self):
        self.approve_fixture();before=e.bundle_hash(self.p);r=self.get('review.json')
        r['checks']['reader']['notes']+=' Изменение отзыва.';self.put('review.json',r)
        self.assertEqual(before,e.bundle_hash(self.p));self.assertFalse(e.check(self.p,True)['ok'])

    def test_run_edit_invalidates_owner(self):
        self.approve_fixture();w=self.get('workflow.json');w['runs'][0]['notes']+=' Изменение.';self.put('workflow.json',w)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_owner_field_not_self_hashed(self):
        self.approve_fixture();before=e.review_hash(self.p);r=self.get('review.json')
        r['human_approval']['name']='Другая синтетическая фикстура';self.put('review.json',r)
        self.assertEqual(before,e.review_hash(self.p))

    def test_per_review_content_hash_required(self):
        for role in ('evidence','reader','science'):
            with self.subTest(role=role):
                self.approve_fixture();r=self.get('review.json');r['checks'][role]['content_hash']='0'*64;self.put('review.json',r)
                self.assertFalse(e.check(self.p,True)['ok'])

    def test_per_review_public_hash_required(self):
        self.approve_fixture();r=self.get('review.json');r['checks']['science']['public_hash']='0'*64;self.put('review.json',r)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_creator_cannot_review_any_role(self):
        for role in ('evidence','reader','science'):
            for creator in ('writer','growth','art'):
                with self.subTest(role=role,creator=creator):
                    self.approve_fixture();w=self.get('workflow.json')
                    if creator=='art':w['runs'].append(dict(id='fixture-art',role='art',actor_id='actor-art',mode='independent',date=date.today().isoformat(),notes='Тест'))
                    for run in w['runs']:
                        if run['role']==role:run['actor_id']='actor-'+creator
                    self.put('workflow.json',w);r=self.get('review.json');r['checks'][role]['actor_id']='actor-'+creator;self.put('review.json',r)
                    # Rebind owner in fixture so only the independence rule is exercised.
                    r['human_approval']['review_hash']=e.review_hash(self.p);self.put('review.json',r)
                    self.assertFalse(e.check(self.p,True)['ok'])

    def test_dossier_preparer_cannot_be_evidence_reviewer(self):
        self.approve_fixture();w=self.get('workflow.json')
        w['runs'].append(dict(id='prepare-sources',role='research',actor_id='actor-evidence',mode='independent',date=date.today().isoformat(),notes='Синтетическая подготовка досье'))
        self.put('workflow.json',w);r=self.get('review.json');r['human_approval']['review_hash']=e.review_hash(self.p);self.put('review.json',r)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_preview_contains_all_public_metadata(self):
        out=e.export_packet(self.p,False,self.root);value=(out/'public/preview.html').read_text();meta=self.get('metadata.json')
        self.assertIn(meta['description'],value)
        for p in meta['publications']:
            self.assertIn(p['promise'],value);self.assertIn(p['next_action'],value)

    def test_same_primary_reviewers_rejected(self):
        self.approve_fixture();w=self.get('workflow.json')
        for r in w['runs']:
            if r['role']=='reader':r['actor_id']='actor-evidence'
        self.put('workflow.json',w);r=self.get('review.json');r['checks']['reader']['actor_id']='actor-evidence';self.put('review.json',r)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_author_name_cannot_be_reviewer(self):
        self.approve_fixture();r=self.get('review.json');r['checks']['reader']['reviewer']='ТЕСТОВЫЙ АВТОР';self.put('review.json',r)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_self_review_mode_rejected(self):
        self.approve_fixture();w=self.get('workflow.json');w['runs'][-1]['mode']='sequential_self_review';self.put('workflow.json',w)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_required_production_and_review_runs(self):
        self.approve_fixture();w=self.get('workflow.json');w['runs']=[];self.put('workflow.json',w)
        self.assertIn('PROVENANCE',self.codes(True))

    def test_revision_limit(self):
        self.approve_fixture();w=self.get('workflow.json');w['revision']=3;self.put('workflow.json',w)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_no_automatic_six_reviews_for_note(self):
        m=self.get('metadata.json');m.update(type='guide',risk='normal',profile='note');self.put('metadata.json',m)
        self.assertEqual(e.route(m)['required_reviews'],['evidence','reader']);self.approve_fixture()

    def test_elevated_forces_science_even_note(self):
        m=self.get('metadata.json');m.update(type='guide',risk='elevated',profile='note');self.put('metadata.json',m)
        self.assertIn('science',e.route(m)['required_reviews']);self.approve_fixture()
        r=self.get('review.json');del r['checks']['science'];self.put('review.json',r)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_preparatory_science_run_is_not_final_review(self):
        self.approve_fixture();w=self.get('workflow.json')
        for r in w['runs']:
            if r['role']=='science':r['role']='science-prep'
        self.put('workflow.json',w);self.assertFalse(e.check(self.p,True)['ok'])

    def test_extra_legacy_reviews_rejected(self):
        self.approve_fixture();r=self.get('review.json');r['checks']['seo']={};self.put('review.json',r)
        self.assertIn('EXTRA_REVIEW',self.codes(True))

    def test_coverage_all_passages_required(self):
        self.approve_fixture();r=self.get('review.json');r['checks']['evidence']['coverage'].pop();self.put('review.json',r)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_cited_claim_not_dismissed_as_opinion(self):
        self.approve_fixture();r=self.get('review.json')
        next(c for c in r['checks']['evidence']['coverage'] if c['claim_ids'])['verdict']='opinion';self.put('review.json',r)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_fabricated_fact_requires_semantic_review_not_regex(self):
        self.append('article.md','В древней мастерской каждый вторник обжигали ровно сто чаш.')
        # Intentionally documents the limit: no claim of automatic factual truth.
        self.assertTrue(e.check(self.p)['ok'])
        inv=e.inventory(e.inspect_package(self.p,e.Report())['surfaces'])
        self.assertTrue(any('сто чаш' in row['text'] for row in inv))

    def test_reader_requires_existing_excerpt(self):
        self.approve_fixture();r=self.get('review.json');r['checks']['reader']['sections']['usefulness']['excerpt']='НЕСУЩЕСТВУЮЩАЯ ЦИТАТА';self.put('review.json',r)
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_empty_and_placeholder_review_notes_rejected(self):
        for note in ('','[заполнить обоснование]'):
            self.approve_fixture();r=self.get('review.json');r['checks']['reader']['notes']=note;self.put('review.json',r)
            self.assertFalse(e.check(self.p,True)['ok'])

    def test_platform_check_expires(self):
        self.approve_fixture();m=self.get('metadata.json');m['platform_checks']['vk']['checked_on']=(date.today()-timedelta(days=31)).isoformat();self.put('metadata.json',m)
        self.assertTrue(any('platform_checks.vk' in i['path'] for i in e.check(self.p,True)['issues']))

    def test_placeholder_all_mandatory_meta_fields_aggregate(self):
        m=self.get('metadata.json')
        for key in ('title','description','primary_query','reader_job','added_value'):m[key]='[заполнить]'
        self.put('metadata.json',m);r=e.check(self.p)
        self.assertFalse(r['ok']);self.assertGreaterEqual(sum(i['code']=='TEMPLATE' for i in r['issues']),5)
        self.assertTrue(all(i['path'] and i['owner'] and i['next_step'] for i in r['issues']))

    def test_publication_promises_validated(self):
        m=self.get('metadata.json');m['publications'][0]['promise']='[заполнить]';m['publications'][1]['next_action']='[[X99]]';self.put('metadata.json',m)
        self.assertFalse(e.check(self.p)['ok'])

    def test_meta_citations_rendered_and_covered(self):
        m=self.get('metadata.json');m['description']+=' [[C1]]';m['publications'][0]['promise']+=' [[C1]]';self.put('metadata.json',m)
        self.approve_fixture();out=e.export_packet(self.p,True,self.root)
        public=e.read_json(out/'public/metadata.json');self.assertNotIn('[[',json.dumps(public))

    def test_all_selected_versions_required(self):
        (self.p/'vk-detail.md').unlink();self.assertFalse(e.check(self.p)['ok'])

    def test_duplicate_versions_are_reviewed_not_silently_accepted(self):
        (self.p/'vk-detail.md').write_text((self.p/'vk-question.md').read_text())
        self.assertIn('DUPLICATE_VERSION',self.codes());self.approve_fixture()
        r=self.get('review.json');r['checks']['reader']['warning_resolutions']={};self.put('review.json',r)
        self.assertIn('UNREVIEWED_WARNING',self.codes(True))

    def test_contextual_quote_not_automatic_failure(self):
        self.append('article.md','Выражение «Идеальный подарок» не объясняет задачу покупателя.')
        self.assertTrue(e.check(self.p)['ok']);self.assertIn('S04',self.codes());self.approve_fixture()

    def test_advertising_cliche_needs_reader_resolution(self):
        self.approve_fixture();self.append('vk-question.md','Идеальный подарок для каждого.')
        self.assertFalse(e.check(self.p,True)['ok']);self.assertIn('S04',self.codes())

    def test_case_spaces_and_invisible_characters(self):
        for value in ('УНИКАЛЬНЫЙ\nДИЗАЙН','уникальный\u00a0дизайн','уника\u200bльный дизайн'):
            self.assertIn('S04',[i['code'] for i in e.lint(value,'test')])

    def test_not_a_word_ban(self):
        self.assertEqual(e.lint('Этот объект является музейным экспонатом.','test'),[])

    def test_local_source_passes_without_web_and_raw_never_exported(self):
        self.add_local_source();self.approve_fixture();out=e.export_packet(self.p,True,self.root)
        for path in (out/'public').rglob('*'):
            if path.is_file():self.assertNotIn(b'PRIVATE_FIXTURE_ORIGINAL',path.read_bytes())
        self.assertIn('Согласованная заметка',(out/'public/article.md').read_text())
        self.assertFalse((out/'public/evidence').exists());self.assertFalse((out/'public/.private').exists())

    def test_even_public_local_raw_not_implicitly_exported(self):
        self.add_local_source('public');out=e.export_packet(self.p,False,self.root)
        self.assertFalse((out/'public/evidence').exists())

    def test_local_source_tampering_detected(self):
        path=self.add_local_source();path.write_text('Подменено');self.assertFalse(e.check(self.p)['ok'])

    def test_local_evidence_cannot_hide_in_notes(self):
        path=self.add_local_source();(self.p/'notes').mkdir();shutil.copyfile(path,self.p/'notes/data.txt')
        s=self.get('sources.json');s[-1]['file']='notes/data.txt';self.put('sources.json',s)
        self.assertFalse(e.check(self.p)['ok'])

    def test_abstract_warns_draft_blocks_release(self):
        s=self.get('sources.json');s[0]['access']='abstract';self.put('sources.json',s)
        self.assertTrue(e.check(self.p)['ok']);self.assertIn('SOURCE_DEPTH',self.codes())
        r=e.check(self.p,True);self.assertFalse(r['ok']);self.assertTrue(any(i['code']=='SOURCE_DEPTH' and i['level']=='error' for i in r['issues']))
        self.assertTrue(any(i['path']=='review.json.human_approval' for i in r['issues']))

    def test_ja_zh_translation_required(self):
        for language in ('ja','zh','zh-Hant'):
            s=self.get('sources.json');s[0]['language']=language;self.put('sources.json',s)
            c=self.get('claims.json');c[0]['translation_checked']=False;self.put('claims.json',c)
            self.assertFalse(e.check(self.p)['ok'])

    def test_future_source_date_rejected(self):
        s=self.get('sources.json');s[0]['checked_on']=(date.today()+timedelta(days=1)).isoformat();self.put('sources.json',s)
        self.assertFalse(e.check(self.p)['ok'])

    def test_unknown_claim_and_source(self):
        self.append('vk-detail.md','[[MISSING]]');c=self.get('claims.json');c[0]['sources']=['UNKNOWN'];self.put('claims.json',c)
        r=e.check(self.p);self.assertFalse(r['ok']);self.assertGreaterEqual(len(r['issues']),2)

    def test_empty_records_and_duplicate_ids(self):
        c=self.get('claims.json')
        for bad in ([],[c[0],c[0]],'C1',None):
            self.put('claims.json',bad);self.assertFalse(e.check(self.p)['ok'])

    def test_json_invalid_types_duplicates_nonfinite(self):
        for raw in ('[]','null','"x"','{"schema_version":true}','{"x":1,"x":2}','{"n":NaN}','{bad'):
            (self.p/'metadata.json').write_text(raw);self.assertFalse(e.check(self.p)['ok'])

    def test_malformed_nested_reviews_fail_without_traceback(self):
        for field,value in (('checks',[]),('checks',{'reader':None,'evidence':[]}),('human_approval',True)):
            self.approve_fixture();r=self.get('review.json');r[field]=value;self.put('review.json',r)
            self.assertFalse(e.check(self.p,True)['ok'])

    def test_malformed_channel_and_publication_values(self):
        good=self.get('metadata.json')
        for bad in (None,[],['vk','vk'],[{}],'vk'):
            m=json.loads(json.dumps(good));m['channels']=bad;self.put('metadata.json',m)
            self.assertFalse(e.check(self.p)['ok'])
        for bad in ([],[None],[{'file':[]}],['x']):
            m=json.loads(json.dumps(good));m['publications']=bad;self.put('metadata.json',m)
            self.assertFalse(e.check(self.p)['ok'])

    def test_unsafe_urls_rejected(self):
        s=self.get('sources.json')
        for bad in ('javascript:alert(1)','https://x/a)injection','https://a:b@x/path','https://x/<script>'):
            s[0]['url']=bad;self.put('sources.json',s);self.assertFalse(e.check(self.p)['ok'])

    def test_generated_caption_and_credit_emitted_everywhere(self):
        self.add_asset('generated');self.append('vk-question.md','![Условный предмет](media/fixture.png)');self.approve_fixture()
        out=e.export_packet(self.p,True,self.root)
        for file in ('article.md','vk-question.md','preview.html'):
            value=(out/'public'/file).read_text();self.assertIn('Иллюстрация создана ИИ',value);self.assertIn('Автор изображения:',value)
        self.assertTrue(e.verify_export(out,self.p)['ok'])

    def test_generated_no_label_or_documentary_rejected(self):
        self.add_asset('generated');a=self.get('assets.json');original=json.loads(json.dumps(a))
        for field,value in (('documentary',True),('caption','Изображение предмета')):
            a=json.loads(json.dumps(original));a[0][field]=value;self.put('assets.json',a)
            self.assertFalse(e.check(self.p)['ok'])

    def test_diagram_explicit_not_documentary(self):
        self.add_asset('diagram');self.assertTrue(e.check(self.p)['ok'])
        a=self.get('assets.json');a[0]['documentary']=True;self.put('assets.json',a);self.assertFalse(e.check(self.p)['ok'])

    def test_illustrated_requires_art_brief(self):
        self.add_asset();(self.p/'art-brief.md').unlink();self.assertFalse(e.check(self.p)['ok'])

    def test_text_only_no_art_brief_needed(self):
        (self.p/'art-brief.md').unlink();self.assertTrue(e.check(self.p)['ok']);self.approve_fixture()

    def test_media_hash_and_caption_change_invalidates(self):
        self.add_asset();self.approve_fixture();a=self.get('assets.json');a[0]['caption']+=' Изменено.';self.put('assets.json',a)
        self.assertFalse(e.check(self.p,True)['ok'])
        self.approve_fixture();(self.p/'media/fixture.png').write_bytes(PNG+b'changed')
        self.assertFalse(e.check(self.p,True)['ok'])

    def test_invalid_raster_rights_alt_rejected(self):
        self.add_asset();original=self.get('assets.json')
        for field,value in (('rights_reference',''),('public_credit','[заполнить]'),('alt','Другой')):
            a=json.loads(json.dumps(original));a[0][field]=value;self.put('assets.json',a)
            self.assertFalse(e.check(self.p)['ok'])
        self.put('assets.json',original);(self.p/'media/fixture.png').write_bytes(b'not an image')
        self.assertFalse(e.check(self.p)['ok'])

    def test_images_only_in_body_not_fake_registry_placement(self):
        self.add_asset();p=self.p/'article.md';p.write_text(p.read_text().replace('![Условный предмет](media/fixture.png)',''))
        a=self.get('assets.json');a[0]['caption']='![Условный предмет](media/fixture.png)';self.put('assets.json',a)
        self.assertFalse(e.check(self.p)['ok'])

    def test_external_reference_and_html_images_rejected(self):
        original=(self.p/'vk-question.md').read_text()
        for invalid in ('![x](https://example.org/a.jpg)','![x][ref]','<img src=x>', '<script>alert(1)</script>'):
            (self.p/'vk-question.md').write_text(original+'\n'+invalid);self.assertFalse(e.check(self.p)['ok'])

    def test_policy_includes_skills_and_native_agents(self):
        paths=e.policy_files()
        for folder in ('.agents/skills/','.codex/agents/','.agents/agents/'):
            self.assertTrue(any(p.startswith(folder) for p in paths))
        before=e.bundle_hash(self.p);original=e.file_hash
        with patch.object(e,'file_hash',lambda p:'0'*64 if str(p).endswith('pottery-reader.toml') else original(p)):
            self.assertNotEqual(before,e.bundle_hash(self.p))

    def test_service_notes_do_not_invalidate_but_new_evidence_does(self):
        self.approve_fixture();before=e.bundle_hash(self.p);(self.p/'notes').mkdir();(self.p/'notes/progress.md').write_text('Служебная заметка')
        self.assertEqual(before,e.bundle_hash(self.p));self.assertTrue(e.check(self.p,True)['ok'])
        (self.p/'additional-evidence.md').write_text('Новый факт');self.assertNotEqual(before,e.bundle_hash(self.p))

    def test_path_traversal_and_symlinks(self):
        for name in ('../secret','/etc/passwd','..\\secret','media//x','media/../x'):
            with self.assertRaises(e.Invalid):e.safe_file(self.p,name)
        (self.p/'outside').symlink_to(self.root);self.assertFalse(e.check(self.p)['ok'])

    def test_init_bad_slugs_and_repeat_no_overwrite(self):
        for slug in ('../x','','two words','X','a'*81):
            with self.assertRaises(e.Invalid):e.initialize(slug,self.root)
        p=e.initialize('new-post',self.root);before=e.bundle_hash(p)
        self.assertFalse(e.check(p)['ok']);self.assertEqual(len(e.read_json(p/'metadata.json')['publications']),1)
        with self.assertRaises(e.Invalid):e.initialize('new-post',self.root)
        self.assertEqual(before,e.bundle_hash(p))

    def test_migrate_preserves_original_and_clears_approval(self):
        m=self.get('metadata.json');m['schema_version']=1;self.put('metadata.json',m)
        (self.p/'vk.md').write_text((self.p/'vk-question.md').read_text())
        original={p.relative_to(self.p).as_posix():e.file_hash(p) for p in self.p.rglob('*') if p.is_file()}
        out=e.migrate(self.p,'migrated',self.root)
        self.assertEqual(original,{p.relative_to(self.p).as_posix():e.file_hash(p) for p in self.p.rglob('*') if p.is_file()})
        self.assertTrue((out/'vk-question.md').exists())
        self.assertIsNone(e.read_json(out/'review.json')['human_approval']);self.assertEqual(e.read_json(out/'workflow.json')['runs'],[])
        self.assertFalse(e.check(out)['ok']) # Unknown promises remain unfilled.

    def test_migrate_does_not_overwrite_existing(self):
        m=self.get('metadata.json');m['schema_version']=1;self.put('metadata.json',m)
        out=e.initialize('occupied',self.root);before=e.bundle_hash(out)
        with self.assertRaises(e.Invalid):e.migrate(self.p,'occupied',self.root)
        self.assertEqual(before,e.bundle_hash(out))

    def test_draft_export_clean_public_manifest_not_published(self):
        out=e.export_packet(self.p,False,self.root);m=e.read_json(out/'manifest.json')
        self.assertEqual(m['status'],'draft');self.assertFalse(m['published'])
        self.assertTrue((out/'public/article.md').read_text().startswith('# '))
        self.assertNotIn('[[C1]]',(out/'public/article.md').read_text())
        self.assertTrue((out/'public/vk-detail.md').exists());self.assertTrue(e.verify_export(out,self.p)['ok'])
        self.assertNotIn('sources.json',str(list((out/'public').iterdir())))

    def test_repeated_export_no_overwrite(self):
        out=e.export_packet(self.p,False,self.root);before=e.file_hash(out/'manifest.json')
        with self.assertRaises(e.Invalid):e.export_packet(self.p,False,self.root)
        self.assertEqual(before,e.file_hash(out/'manifest.json'))

    def test_release_export_requires_real_contract(self):
        with self.assertRaises(e.Invalid):e.export_packet(self.p,True,self.root)
        self.assertFalse((self.root/'dist').exists())
        self.approve_fixture();out=e.export_packet(self.p,True,self.root)
        self.assertEqual(e.verify_export(out,self.p)['status'],'accepted_manual_export')

    def test_tampered_export_rejected(self):
        out=e.export_packet(self.p,False,self.root);(out/'public/vk-detail.md').write_text('Изменено')
        with self.assertRaises(e.Invalid):e.verify_export(out,self.p)

    def test_nested_manifest_not_ignored(self):
        out=e.export_packet(self.p,False,self.root);(out/'public/manifest.json').write_text('{}')
        with self.assertRaises(e.Invalid):e.verify_export(out)

    def test_export_manifest_status_and_public_hash_checked(self):
        out=e.export_packet(self.p,False,self.root);m=e.read_json(out/'manifest.json');m['public_hash']='0'*64;e.save_json(out/'manifest.json',m)
        with self.assertRaises(e.Invalid):e.verify_export(out)
        m['published']=True;e.save_json(out/'manifest.json',m)
        with self.assertRaises(e.Invalid):e.verify_export(out)

    def test_source_binding_after_review_changes(self):
        self.approve_fixture();out=e.export_packet(self.p,True,self.root)
        r=self.get('review.json');r['checks']['reader']['notes']+=' Правка.';self.put('review.json',r)
        self.assertTrue(e.verify_export(out)['ok']) # integrity only, not current source approval
        with self.assertRaises(e.Invalid):e.verify_export(out,self.p)

    def test_cli_status_exit_and_structured_errors(self):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/editorial.py'),'status',str(self.p)],capture_output=True,text=True)
        self.assertEqual(result.returncode,1);self.assertFalse(json.loads(result.stdout)['release_ready'])
        self.assertNotIn('Traceback',result.stderr)


class RepositoryTests(unittest.TestCase):
    def test_nine_canonical_skills(self):
        skills=list((ROOT/'.agents/skills').glob('*/SKILL.md'));self.assertEqual(len(skills),9)
        for p in skills:
            value=p.read_text();self.assertTrue(value.startswith('---\nname: '+p.parent.name+'\n'));self.assertIn('\ndescription:',value);self.assertIn('AGENTS.md',value)

    def test_canonical_document_references_exist(self):
        import re
        for path in (ROOT/'.agents/skills').glob('*/SKILL.md'):
            for link in re.findall(r'(?<![\w/])(?:docs/)?(?:QUALITY|WORKFLOW|ART_DIRECTION|DISTRIBUTION|INTEGRATION|RESEARCH)\.md', path.read_text()):
                self.assertTrue((ROOT/link).is_file(), str(path)+': '+link)

    def test_native_codex_reviewers_read_only(self):
        paths=list((ROOT/'.codex/agents').glob('*.toml'));self.assertEqual(len(paths),3)
        for p in paths:
            obj=tomllib.loads(p.read_text());self.assertEqual(obj['name'],p.stem)
            self.assertEqual(obj['sandbox_mode'],'read-only');self.assertTrue(obj['developer_instructions'])

    def test_native_antigravity_no_invented_sandbox(self):
        paths=list((ROOT/'.agents/agents').glob('*.md'));self.assertEqual(len(paths),3)
        for p in paths:
            value=p.read_text();self.assertIn('subagent: true',value);self.assertIn('AGENTS.md',value);self.assertNotIn('sandbox_mode:',value)

    def test_routes_science_final_after_freeze(self):
        r=e.read_json(ROOT/'editorial/routes.json');self.assertEqual(r['max_parallel_readers'],3)
        steps=r['profiles']['research']['steps'];freeze=next(i for i,x in enumerate(steps) if x.startswith('freeze:'))
        final=next(i for i,x in enumerate(steps) if 'финальные независимые' in x)
        self.assertGreater(final,freeze)

    def test_plan_has_distinct_deliverables_and_explicit_dependencies(self):
        p=e.read_json(ROOT/'editorial/plan.json');topics={x['id']:x for x in p['topics']}
        self.assertEqual(len(topics),24);self.assertEqual(len(p['calendar']),12)
        source_ids={x['id'] for x in e.read_json(ROOT/'research/sources.json')};ids=set()
        for t in topics.values():
            self.assertIsNone(t['query_volume']);self.assertTrue(set(t['sources'])<=source_ids);self.assertFalse(t['ready_for_publication'])
            self.assertTrue(t['dependencies']);self.assertTrue(set(t['related'])<=set(topics));self.assertNotIn(t['id'],t['related'])
            for d in t['deliverables']:
                self.assertNotIn(d['id'],ids);ids.add(d['id'])
            self.assertEqual(len({d['promise'] for d in t['deliverables']}),len(t['deliverables']))
        for slot in p['calendar']:
            self.assertIn(slot['topic'],topics);self.assertTrue(set(slot['deliverable_ids'])<=ids)
            self.assertEqual(sum('-vk-' in x for x in slot['deliverable_ids']),slot['vk_posts'])
        self.assertEqual(topics['T21']['merged_into'],'T02');self.assertEqual(topics['T08']['parent_topic'],'T03')

    def test_behavior_cases_have_no_fake_execution(self):
        cases=e.read_json(ROOT/'evals/cases.json');self.assertEqual(len(cases),12)
        self.assertEqual(len({x['id'] for x in cases}),len(cases))
        for row in cases:
            self.assertTrue((ROOT/'.agents/skills'/row['skill']/'SKILL.md').is_file());self.assertTrue(row['expected_verdict']);self.assertTrue(row['rationale'])
        run=e.read_json(ROOT/'evals/run-template.json');self.assertEqual(run['status'],'not_run');self.assertEqual(run['records'],[])

    def test_no_fake_approved_author_voice(self):
        self.assertEqual(e.read_json(ROOT/'editorial/voice/approved.json'),[])

    def test_readme_local_links_exist(self):
        import re
        for link in re.findall(r'\]\(([^)]+)\)',(ROOT/'README.md').read_text()):
            if not link.startswith(('https:','http:','#')):self.assertTrue((ROOT/link).exists(),link)


if __name__=='__main__':
    unittest.main()
