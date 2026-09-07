"""Parsing and sandboxing. No model, no network."""

import pytest

from driftcheck import tools

RENAME_DIFF = """diff --git a/old/name.py b/new/name.py
similarity index 90%
rename from old/name.py
rename to new/name.py
@@ -1,2 +1,2 @@
-a
+b
diff --git a/gone.py b/dev/null
deleted file mode 100644
@@ -1 +0,0 @@
-x
diff --git a/kept.py b/kept.py
@@ -3,3 +3,4 @@
 ctx
+added
"""


def test_split_diff_keys_on_destination_path():
    parts = tools.split_diff(RENAME_DIFF)
    assert set(parts) == {"new/name.py", "gone.py", "kept.py"}
    assert "+added" in parts["kept.py"]
    # A rename must not leak the next file's hunks into this one.
    assert "kept.py" not in parts["new/name.py"]


def test_split_diff_on_junk_is_empty_not_an_exception():
    assert tools.split_diff("") == {}
    assert tools.split_diff("Binary files differ\n") == {}


@pytest.mark.parametrize(
    "body,expected",
    [
        ("Fixes #12", [12]),
        ("closes #7 and Resolves #8", [7, 8]),
        ("Fixed #5\nfixes #5", [5]),  # deduped, order kept
        ("See #99 for context", []),  # a mention is not a claim
        ("Follow-up to #1636, which merged before this fix landed", []),
        ("", []),
        (None, []),
    ],
)
def test_issue_refs_only_counts_closing_keywords(body, expected):
    assert tools.issue_refs(body) == expected


def test_read_source_refuses_to_escape_the_checkout(tmp_path):
    (tmp_path / "in.py").write_text("one\ntwo\nthree\n")
    secret = tmp_path.parent / "outside.txt"
    secret.write_text("do not read me")
    tools.configure("owner/repo", tmp_path)

    assert "two" in tools.read_source("in.py", 1, 3)
    assert "Refused" in tools.read_source("../outside.txt")
    assert "No such file" in tools.read_source("nope.py")


def test_read_source_without_a_checkout_says_so():
    tools.configure("owner/repo", None)
    assert "diff alone" in tools.read_source("anything.py")


def test_clip_marks_truncation():
    out = tools._clip("x" * 100, limit=10)
    assert out.startswith("x" * 10)
    assert "truncated" in out
