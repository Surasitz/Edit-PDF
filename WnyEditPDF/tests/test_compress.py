# -*- coding: utf-8 -*-
"""Regression suite for the PDF compressor.

The feature makes four promises, and each one is a section below:

* the file gets smaller - measurably, on the kind of file people actually
  complain about (a scan);
* the words survive - a Thai document reads back character for character;
* the original is never touched, and neither is the destination when the run
  is cancelled or the rewrite would not have helped;
* pictures that a JPEG round-trip would ruin (transparency, bitonal fax) are
  left exactly as they were.
"""
import os
import shutil

import fitz
import pytest

from wnyeditpdf import compress as cz

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "sample_thai.pdf")


def text_of(path):
    with fitz.open(path) as d:
        return "".join(p.get_text() for p in d)


@pytest.fixture(scope="module")
def scan_pdf(tmp_path_factory):
    """The fixture re-imaged at 300 dpi: a stand-in for a scanned document,
    which is where the megabytes in a real PDF live."""
    out = str(tmp_path_factory.mktemp("scan") / "scan.pdf")
    src = fitz.open(FIXTURE)
    scan = fitz.open()
    for page in src:
        pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
        new = scan.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=pix.tobytes("png"))
    scan.save(out, deflate=True)
    scan.close()
    src.close()
    return out


# --------------------------------------------------------------- it shrinks
class TestShrinks:
    @pytest.mark.parametrize("level", cz.LEVELS)
    def test_scan_gets_smaller_and_still_opens(self, scan_pdf, tmp_path, level):
        dst = str(tmp_path / ("out_%s.pdf" % level))
        with fitz.open(scan_pdf) as d:
            pages = d.page_count
        st = cz.compress_file(scan_pdf, dst, level=level)

        assert st["after"] < st["before"]
        assert not st["unchanged"]
        with fitz.open(dst) as d:
            assert d.page_count == pages
            assert d[0].get_pixmap(dpi=36)          # renders without error

    def test_harder_level_gives_a_smaller_file(self, scan_pdf, tmp_path):
        sizes = []
        for level in cz.LEVELS:
            dst = str(tmp_path / ("step_%s.pdf" % level))
            sizes.append(cz.compress_file(scan_pdf, dst, level=level)["after"])
        assert sizes == sorted(sizes, reverse=True), sizes

    def test_a_scan_loses_most_of_its_weight(self, scan_pdf, tmp_path):
        """The headline promise. A 300 dpi scan on A4 is carrying twice the
        pixels anyone needs; 'balanced' should be cutting it by a third at
        the very least."""
        dst = str(tmp_path / "balanced.pdf")
        st = cz.compress_file(scan_pdf, dst, level="balanced")
        assert st["percent"] > 33, st

    def test_grayscale_beats_colour(self, scan_pdf, tmp_path):
        colour = cz.compress_file(scan_pdf, str(tmp_path / "c.pdf"),
                                  level="balanced")
        grey = cz.compress_file(scan_pdf, str(tmp_path / "g.pdf"),
                                level="balanced", grayscale=True)
        assert grey["after"] < colour["after"]

    def test_reports_add_up(self, scan_pdf, tmp_path):
        dst = str(tmp_path / "stats.pdf")
        st = cz.compress_file(scan_pdf, dst, level="max")
        assert st["before"] == os.path.getsize(scan_pdf)
        assert st["after"] == os.path.getsize(dst)
        assert st["saved"] == st["before"] - st["after"]
        assert st["images"] >= 1


# ------------------------------------------------------------ text survives
class TestTextSurvives:
    @pytest.mark.parametrize("subset", [False, True])
    def test_thai_text_is_unchanged(self, tmp_path, subset):
        dst = str(tmp_path / "text.pdf")
        cz.compress_file(FIXTURE, dst, level="max", subset_fonts=subset)
        assert text_of(dst) == text_of(FIXTURE)

    def test_page_still_renders_the_same(self, tmp_path):
        """Subsetting rewrites the embedded font programs - the one step that
        could silently turn Thai into .notdef boxes. Compare pixels, because
        the text layer would still read correctly if the glyphs were gone."""
        dst = str(tmp_path / "render.pdf")
        cz.compress_file(FIXTURE, dst, level="max", subset_fonts=True)
        with fitz.open(FIXTURE) as a, fitz.open(dst) as b:
            before = a[0].get_pixmap(dpi=72).samples
            after = b[0].get_pixmap(dpi=72).samples
            assert len(before) == len(after)
            differing = sum(1 for x, y in zip(before, after) if abs(x - y) > 24)
            assert differing / len(before) < 0.01


# ------------------------------------------------------------------- safety
class TestSafety:
    def test_source_is_never_written_to(self, scan_pdf, tmp_path):
        before = open(scan_pdf, "rb").read()
        cz.compress_file(scan_pdf, str(tmp_path / "o.pdf"), level="max")
        assert open(scan_pdf, "rb").read() == before

    def test_already_small_file_is_copied_through(self, tmp_path):
        """A file we cannot improve comes back byte-identical, flagged, rather
        than as a re-encoded 'compressed' file that is actually bigger."""
        src = str(tmp_path / "tiny.pdf")
        doc = fitz.open()
        doc.new_page()
        doc.save(src, garbage=4, deflate=True, clean=True)
        doc.close()

        dst = str(tmp_path / "tiny_out.pdf")
        st = cz.compress_file(src, dst, level="max")
        assert st["unchanged"]
        assert st["after"] == st["before"]
        assert open(dst, "rb").read() == open(src, "rb").read()

    def test_cancel_leaves_no_output(self, scan_pdf, tmp_path):
        dst = str(tmp_path / "cancelled.pdf")
        calls = []

        def stop(done, total):
            calls.append(done)
            return len(calls) < 2          # give up almost immediately

        with pytest.raises(cz.CompressCancelled):
            cz.compress_file(scan_pdf, dst, level="max", progress=stop)
        assert not os.path.exists(dst)
        assert not os.path.exists(dst + ".partial")

    def test_progress_runs_from_zero_to_the_end(self, scan_pdf, tmp_path):
        seen = []
        cz.compress_file(scan_pdf, str(tmp_path / "p.pdf"), level="light",
                         progress=lambda d, t: seen.append((d, t)) or True)
        assert seen[0][0] == 0
        assert seen[-1][0] == seen[-1][1]
        assert [d for d, _ in seen] == sorted(d for d, _ in seen)

    def test_a_locked_file_is_reported_not_mangled(self, tmp_path):
        src = str(tmp_path / "locked.pdf")
        doc = fitz.open()
        doc.new_page()
        doc.save(src, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret")
        doc.close()
        dst = str(tmp_path / "locked_out.pdf")
        with pytest.raises(cz.CompressError):
            cz.compress_file(src, dst, level="max")
        assert not os.path.exists(dst)

    def test_in_place_keeps_a_working_file(self, scan_pdf, tmp_path):
        """Compressing onto the source path is allowed, but only ever swaps in
        a file that opened cleanly."""
        work = str(tmp_path / "inplace.pdf")
        shutil.copyfile(scan_pdf, work)
        st = cz.compress_file(work, work, level="max")
        assert st["after"] == os.path.getsize(work)
        assert not os.path.exists(work + ".partial")
        with fitz.open(work) as d:
            assert d.page_count > 0


# ------------------------------------------------------- pictures left alone
class TestPicturesLeftAlone:
    def _pdf_with_transparent_image(self, path):
        w = h = 200                                # a diagonal opaque wedge
        samples = bytearray()
        for y in range(h):
            for x in range(w):
                samples += bytes((255, 0, 0, 255 if x > y else 0))
        pix = fitz.Pixmap(fitz.csRGB, w, h, bytes(samples), True)
        doc = fitz.open()
        page = doc.new_page()
        page.insert_image(fitz.Rect(50, 50, 250, 250), pixmap=pix)
        doc.save(path, deflate=True)
        doc.close()

    def test_transparency_is_not_flattened(self, tmp_path):
        src = str(tmp_path / "alpha.pdf")
        self._pdf_with_transparent_image(src)
        dst = str(tmp_path / "alpha_out.pdf")
        cz.compress_file(src, dst, level="max")
        with fitz.open(dst) as d:
            masks = [d.xref_get_key(img[0], "SMask")[0]
                     for img in d[0].get_images(full=True)]
        assert masks and all(m != "null" for m in masks), masks

    def test_bitonal_scan_is_left_alone(self, tmp_path):
        """1 bit per pixel under CCITT/flate is already smaller than any JPEG
        of the same page - re-encoding it would grow the file and smear the
        letters."""
        src = str(tmp_path / "bw.pdf")
        doc = fitz.open()
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 1200, 1600), False)
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
        doc.save(src, deflate=True)
        doc.close()

        with fitz.open(src) as d:
            for xref, *_ in d[0].get_images(full=True):
                d.xref_set_key(xref, "BitsPerComponent", "1")
                assert cz._skip_reason(d, xref) == "bitonal"


# -------------------------------------------------------------- housekeeping
class TestHelpers:
    @pytest.mark.parametrize("n, out", [
        (12, "12 B"), (2048, "2.0 KB"), (1024 * 1024 * 3, "3.0 MB"),
    ])
    def test_human_size(self, n, out):
        assert cz.human_size(n) == out

    def test_output_path_never_collides(self, tmp_path):
        src = str(tmp_path / "doc.pdf")
        open(src, "wb").write(b"%PDF-1.4\n")
        first = cz.output_path(src)
        assert os.path.basename(first) == "doc_compressed.pdf"
        open(first, "wb").write(b"%PDF-1.4\n")
        second = cz.output_path(src)
        assert second != first
        assert not os.path.exists(second)

    def test_output_path_honours_a_chosen_folder(self, tmp_path):
        src = str(tmp_path / "doc.pdf")
        open(src, "wb").write(b"%PDF-1.4\n")
        other = tmp_path / "out"
        other.mkdir()
        assert os.path.dirname(cz.output_path(src, str(other))) == str(other)
