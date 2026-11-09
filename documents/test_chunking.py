from django.test import SimpleTestCase

from .chunking import MAX_CHUNK_CHARS, OVERLAP_CHARS, build_chunks, split_text


class SplitTextTests(SimpleTestCase):
    def test_short_text_stays_in_one_chunk(self):
        self.assertEqual(split_text("One rule.\nAnother rule."), ["One rule.\nAnother rule."])

    def test_blank_text_produces_no_chunks(self):
        self.assertEqual(split_text("  \n\n "), [])

    def test_no_chunk_exceeds_the_limit(self):
        text = "\n".join(f"Rule {n}: " + "word " * 40 for n in range(50))
        self.assertTrue(all(len(c) <= MAX_CHUNK_CHARS for c in split_text(text)))

    def test_one_very_long_line_is_broken_up(self):
        chunks = split_text("Sentence number one is here. " * 200)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= MAX_CHUNK_CHARS for c in chunks))

    def test_neighbouring_chunks_share_text(self):
        lines = [f"Rule {n} applies to students here." for n in range(100)]
        first, second = split_text("\n".join(lines))[:2]
        last_line = first.splitlines()[-1]
        self.assertLess(len(last_line), OVERLAP_CHARS)
        self.assertIn(last_line, second)

    def test_no_text_is_lost(self):
        lines = [f"Rule {n}." for n in range(400)]
        joined = "\n".join(split_text("\n".join(lines)))
        self.assertTrue(all(line in joined for line in lines))


class BuildChunksTests(SimpleTestCase):
    def test_chunks_keep_their_page_number(self):
        drafts = build_chunks(["First page", "", "Third page"])
        self.assertEqual([d.page_number for d in drafts], [1, 3])

    def test_section_carries_over_to_the_next_page(self):
        drafts = build_chunks(["Section 2: Exams\nRule one.", "Rule two."])
        self.assertEqual(drafts[0].section, "Section 2: Exams")
        self.assertEqual(drafts[1].section, "Section 2: Exams")

    def test_recognizes_russian_and_uzbek_headings(self):
        self.assertEqual(build_chunks(["Раздел 1: Экзамены\nТекст"])[0].section, "Раздел 1: Экзамены")
        self.assertEqual(build_chunks(["Boʻlim 3\nMatn"])[0].section, "Boʻlim 3")

    def test_ordinary_sentence_is_not_a_heading(self):
        self.assertEqual(build_chunks(["Attendance is required."])[0].section, "")
