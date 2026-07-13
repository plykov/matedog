"""End-to-end API tests: project -> upload -> matches -> confirm (learn) -> QA -> export."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# Point the app at a throwaway database before importing the server.
_tmp = tempfile.mkdtemp()
os.environ["MATEDOG_DB"] = os.path.join(_tmp, "test.db")

from matedog.server import app  # noqa: E402

client = TestClient(app)

XLIFF = """<?xml version="1.0" encoding="UTF-8"?>
<xliff xmlns="urn:oasis:names:tc:xliff:document:1.2" version="1.2">
 <file original="doc.txt" source-language="en" target-language="ru" datatype="plaintext">
  <body>
   <trans-unit id="1"><source>The cat sleeps.</source></trans-unit>
   <trans-unit id="2"><source>The dog eats meat.</source></trans-unit>
  </body>
 </file>
</xliff>"""

TMX = """<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4">
 <header creationtool="x" creationtoolversion="1" segtype="sentence"
         o-tmf="x" adminlang="en" srclang="en" datatype="plaintext"/>
 <body>
  <tu><tuv xml:lang="en"><seg>The cat sleeps.</seg></tuv>
      <tuv xml:lang="ru"><seg>Кот спит.</seg></tuv></tu>
 </body>
</tmx>"""


@pytest.fixture(scope="module")
def project():
    r = client.post("/api/projects",
                    json={"name": "Demo", "src_lang": "en", "tgt_lang": "ru"})
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def file_id(project):
    r = client.post(f"/api/projects/{project['id']}/files",
                    files={"file": ("doc.xliff", XLIFF, "application/xml")})
    assert r.status_code == 200, r.text
    assert r.json()["segments"] == 2
    return r.json()["file_id"]


def test_unsupported_pair_rejected():
    r = client.post("/api/projects",
                    json={"name": "Bad", "src_lang": "en", "tgt_lang": "de"})
    assert r.status_code == 400


def test_tmx_import_and_match(project, file_id):
    r = client.post("/api/tm/import",
                    data={"src_lang": "en", "tgt_lang": "ru", "both_directions": "true"},
                    files={"file": ("mem.tmx", TMX, "application/xml")})
    assert r.status_code == 200 and r.json()["pairs_found"] == 1

    segs = client.get(f"/api/files/{file_id}/segments").json()
    m = client.get(f"/api/segments/{segs[0]['id']}/matches").json()
    assert m["tm"] and m["tm"][0]["percent"] == 100
    assert m["mt"]["text"] == "Кот спит."


def test_confirm_learns_into_tm(project, file_id):
    segs = client.get(f"/api/files/{file_id}/segments").json()
    seg = segs[1]
    r = client.patch(f"/api/segments/{seg['id']}",
                     json={"target": "Собака ест мясо.", "state": "translated"})
    assert r.status_code == 200
    # The confirmed pair must now be an exact TM match.
    m = client.get(f"/api/segments/{seg['id']}/matches").json()
    assert m["tm"][0]["percent"] == 100
    assert m["tm"][0]["origin"] == "editor"


def test_qa_endpoint(project, file_id):
    segs = client.get(f"/api/files/{file_id}/segments").json()
    r = client.patch(f"/api/segments/{segs[0]['id']}",
                     json={"target": 'Кот  "спит"', "state": "draft"})
    issues = {i["code"] for i in r.json()["qa"]}
    assert "double_space" in issues
    assert "ru_quotes" in issues
    assert "punct_end" in issues


def test_export_xliff(project, file_id):
    r = client.get(f"/api/files/{file_id}/export")
    assert r.status_code == 200
    assert "Собака ест мясо." in r.text
    assert 'state="translated"' in r.text


def test_pair_import_and_ml(project):
    src = "the cat sleeps\nthe dog sleeps\nthe cat eats fish\nthe dog eats meat\n"
    tgt = "кот спит\nсобака спит\nкот ест рыбу\nсобака ест мясо\n"
    r = client.post("/api/tm/pair-import",
                    data={"src_lang": "en", "tgt_lang": "ru", "train": "true"},
                    files={"src_file": ("s.txt", src, "text/plain"),
                           "tgt_file": ("t.txt", tgt, "text/plain")})
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["aligned_pairs"] == 4
    assert body["lexicon_entries"] > 0


def test_analysis(project, file_id):
    r = client.get(f"/api/projects/{project['id']}/analysis")
    assert r.status_code == 200
    body = r.json()
    assert body["total_words"] > 0


def test_txt_upload(project):
    r = client.post(f"/api/projects/{project['id']}/files",
                    files={"file": ("plain.txt", "First sentence. Second sentence!", "text/plain")})
    assert r.status_code == 200 and r.json()["segments"] == 2


def test_pdf_upload(project):
    from tests.pdf_fixture import make_pdf
    pdf = make_pdf(["First pdf sentence.", "Second pdf sentence!"])
    r = client.post(f"/api/projects/{project['id']}/files",
                    files={"file": ("scan.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["segments"] == 2
    segs = client.get(f"/api/files/{r.json()['file_id']}/segments").json()
    assert segs[0]["source"] == "First pdf sentence."


def test_pdf_password_or_garbage_rejected(project):
    r = client.post(f"/api/projects/{project['id']}/files",
                    files={"file": ("bad.pdf", b"garbage", "application/pdf")})
    assert r.status_code == 400


def test_ui_served():
    r = client.get("/")
    assert r.status_code == 200 and "MateDog" in r.text
