"""Offline tests for the parsing/filtering logic (no network required).

Run:  python3 test_job_tracker.py
These feed realistic sample payloads to each source parser and assert the
keyword filter, location filter, de-duplication and CSV round-trip behave.
"""

import os
import tempfile

import job_tracker as jt

KW = jt.KEYWORDS


def test_keyword_matcher():
    assert jt.matches_keywords("Remote Project Coordinator", ["remote coordinator"])
    assert jt.matches_keywords("Senior Data Analyst", ["data analyst"])
    assert jt.matches_keywords("Customer Support Specialist", ["customer support"])
    assert jt.matches_keywords("Software Engineer", ["data analyst"]) is None


def test_title_excluded():
    assert jt.title_excluded("Senior Quality Engineer")
    assert jt.title_excluded("Staff Product Engineer")
    assert jt.title_excluded("Engineering Manager")
    assert not jt.title_excluded("Customer Support Specialist")
    assert not jt.title_excluded("Remote Coordinator")


def test_relevance_filter():
    # Mimics main()'s central filter on the kind of junk Remotive returned.
    scraped = [
        jt.Job("Senior Quality Engineer", "LawnStarter", "https://x/1"),     # senior -> drop
        jt.Job("Staff Product Engineer", "LawnStarter", "https://x/2"),       # senior -> drop
        jt.Job("Frontend Developer", "Quinncia", "https://x/3"),              # no keyword -> drop
        jt.Job("Customer Support Specialist", "Acme", "https://x/4"),         # keep
        jt.Job("Remote Coordinator", "Beta", "https://x/5"),                  # keep
    ]
    kept = [j for j in scraped
            if jt.matches_keywords(j.title, KW) and not jt.title_excluded(j.title)]
    assert [j.title for j in kept] == ["Customer Support Specialist", "Remote Coordinator"]


def test_location_filter():
    assert jt.location_ok("Canada")
    assert jt.location_ok("Anywhere in the World")
    assert jt.location_ok("")              # unknown -> keep
    assert jt.location_ok("Toronto, ON")
    assert not jt.location_ok("USA Only")
    assert not jt.location_ok("Europe only")


def test_remotive():
    data = {"jobs": [
        {"title": "Customer Support Specialist", "company_name": "Acme",
         "url": "https://remotive.com/remote-jobs/support/acme-123",
         "candidate_required_location": "Canada"},
        {"title": "Sales Engineer", "company_name": "USOnlyCo",
         "url": "https://remotive.com/remote-jobs/x/456",
         "candidate_required_location": "USA Only"},
    ]}
    jobs = jt.parse_remotive(data)
    # second one is dropped on location, but parse_remotive doesn't keyword-filter
    # (Remotive searches server-side); location filter still applies.
    assert len(jobs) == 1
    assert jobs[0].company == "Acme" and jobs[0].source == "Remotive"


def test_remoteok():
    data = [
        {"legal": "RemoteOK legal notice"},  # leading element, skipped
        {"position": "Virtual Assistant", "company": "VA Co",
         "tags": ["admin", "non-tech"], "location": "Worldwide",
         "url": "https://remoteok.com/remote-jobs/va-co-100"},
        {"position": "Rust Engineer", "company": "RustCo",
         "tags": ["rust"], "location": "Worldwide",
         "url": "https://remoteok.com/remote-jobs/rust-200"},
        {"position": "Data Entry Clerk", "company": "EU Co",
         "tags": [], "location": "Europe only",
         "url": "/remote-jobs/data-300"},  # relative url + blocked location
    ]
    jobs = jt.parse_remoteok(data, KW)
    titles = [j.title for j in jobs]
    assert "Virtual Assistant" in titles      # keyword + location ok
    assert "Rust Engineer" not in titles       # no keyword match
    assert "Data Entry Clerk" not in titles     # blocked location
    assert jobs[0].url.startswith("https://remoteok.com")


def test_weworkremotely():
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>BigCo: Remote Customer Support Agent</title>
        <link>https://weworkremotely.com/remote-jobs/bigco-support</link>
        <region>Anywhere in the World</region>
      </item>
      <item>
        <title>DevShop: Senior Backend Engineer</title>
        <link>https://weworkremotely.com/remote-jobs/devshop-backend</link>
        <region>USA Only</region>
      </item>
    </channel></rss>"""
    jobs = jt.parse_wwr(xml, KW)
    assert len(jobs) == 1
    assert jobs[0].company == "BigCo"
    assert jobs[0].title == "Remote Customer Support Agent"
    assert jobs[0].source == "WeWorkRemotely"


def test_adzuna():
    data = {"results": [
        {"title": "Operations Coordinator", "company": {"display_name": "OpsCo"},
         "redirect_url": "https://www.adzuna.ca/land/ad/123?utm=x",
         "location": {"display_name": "Toronto, Ontario"}},
    ]}
    jobs = jt.parse_adzuna(data)
    assert len(jobs) == 1
    assert jobs[0].company == "OpsCo" and jobs[0].location == "Toronto, Ontario"
    # tracking query is stripped in the dedup key
    assert jobs[0].key == "https://www.adzuna.ca/land/ad/123"


def test_themuse():
    data = {"results": [
        {"name": "Customer Success Associate", "company": {"name": "Muse Inc"},
         "locations": [{"name": "Flexible / Remote"}],
         "refs": {"landing_page": "https://www.themuse.com/jobs/museinc/csa"}},
        {"name": "Principal Architect", "company": {"name": "Muse Inc"},
         "locations": [{"name": "New York, NY"}],
         "refs": {"landing_page": "https://www.themuse.com/jobs/museinc/arch"}},
    ]}
    jobs = jt.parse_themuse(data, KW)
    assert len(jobs) == 1
    assert jobs[0].title == "Customer Success Associate"


def test_dedup_and_csv_roundtrip():
    jobs = [
        jt.Job("Customer Support", "Acme", "https://remotive.com/remote-jobs/a-1",
               source="Remotive"),
        # same job, different source/url -> collapsed by (title, company)
        jt.Job("Customer Support", "Acme", "https://remoteok.com/remote-jobs/a-1",
               source="RemoteOK"),
        jt.Job("Data Analyst", "DataCo", "https://remotive.com/remote-jobs/d-2",
               source="Remotive"),
    ]
    # simulate main()'s within-run dedup
    unique, seen = {}, set()
    for job in jobs:
        if job.key in unique:
            continue
        tc = (job.title.lower(), job.company.lower())
        if tc in seen:
            continue
        unique[job.key] = job
        seen.add(tc)
    assert len(unique) == 2, "title+company duplicate across sources should collapse"

    tmp = tempfile.mktemp(suffix=".csv")
    try:
        jt.append_jobs(tmp, list(unique.values()))
        keys = jt.load_existing_keys(tmp)
        assert len(keys) == 2
        # re-loading the same job is recognised as not-new
        assert jt.Job("", "", "https://remotive.com/remote-jobs/d-2").key in keys
        # header columns present and ordered
        with open(tmp) as fh:
            header = fh.readline().strip()
        assert header == ",".join(jt.CSV_COLUMNS)
    finally:
        os.remove(tmp)


def run():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"ALL {len(tests)} TESTS PASSED")


if __name__ == "__main__":
    run()
