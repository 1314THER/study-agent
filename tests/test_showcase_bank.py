"""Check the small public library preserves answers while excluding owner state."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.showcase_bank import verify
from scripts.build_showcase_bank import build

ROOT = Path(__file__).resolve().parents[1]


class ShowcaseBankTests(unittest.TestCase):
    def test_published_library_contains_only_source_verified_national_questions(self):
        root=ROOT/'frontend/showcase/question-bank'
        manifest=verify(root)
        self.assertEqual(manifest['count'],2)
        self.assertEqual(set(manifest['files']),{'index.json','part-0000.json'})
        rows=json.loads((root/'part-0000.json').read_text())
        self.assertEqual(set(rows), {'20230117', '20250116'})
        self.assertTrue(all(row['question'] and row['answer_json']['chunk_results'] for row in rows.values()))
        for row in rows.values():
            self.assertEqual(row['region'], '全国卷')
            self.assertTrue(all('全国' in source['name'] and source['url'].startswith('https://') for source in row['sources']))
            self.assertTrue(all(source['question_no'] in ('16', '17') for source in row['sources']))
        recorded=json.loads((ROOT/'frontend/showcase/pipeline.json').read_text())['examples']
        for identifier,qid in [('national-2023-q17','20230117'),('national-2025-q16','20250116')]:
            original=recorded[identifier]['xuefeng']['answer_json']
            self.assertEqual(rows[qid]['answer'],original['final_answer'])
            for saved,expected in zip(rows[qid]['answer_json']['chunk_results'],original['chunk_results']):
                self.assertEqual(saved['steps'],expected['steps'])
        text=json.dumps(rows,ensure_ascii=False)
        for private in ('user_id','last_viewed_at','last_exam_at','practice_records','api_key','"owner"','/Users/'):
            self.assertNotIn(private,text)

    def test_export_reads_only_content_and_does_not_copy_private_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);database=root/'study_agent.db'
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE questions(id INTEGER,content TEXT,answer_json TEXT,category_level1 TEXT,question_type TEXT,source_type TEXT,source_meta TEXT,difficulty_level TEXT,user_id TEXT)')
                answer={'final_answer':'2','chunk_results':[{'chunk_id':1,'steps':[{'step_number':1,'title':'计算','standard_writing':'1+1=2','detailed_writing':'相加','user_id':'private-user'}]}],'source_meta':{'owner':'private-owner'},'api_key':'private-key'}
                db.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?)',(9,'1+1=?',json.dumps(answer),'集合','填空题','精选母题','{"owner":"private-owner","pattern":"计算"}','容易','private-user'))
                db.execute('CREATE TABLE practice_records(content TEXT)');db.execute('INSERT INTO practice_records VALUES (?)',('private practice',))
            before=database.read_bytes()
            build(database,root/'public',root/'images')
            result=verify(root/'public')
            self.assertEqual(result['count'],1)
            self.assertEqual(before,database.read_bytes())
            text=(root/'public/part-0000.json').read_text()
            for value in ('private-user','private-owner','private-key','private practice'):
                self.assertNotIn(value,text)
            self.assertEqual(json.loads(text)['9']['answer'],'2')

    def test_extra_file_and_damaged_question_content_are_rejected(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'bank';shutil.copytree(ROOT/'frontend/showcase/question-bank',root)
            (root/'settings.json').write_text('{"api_key":"private"}')
            with self.assertRaises(ValueError):verify(root)
            (root/'settings.json').unlink();(root/'part-0000.json').write_text('{}')
            with self.assertRaises(ValueError):verify(root)
