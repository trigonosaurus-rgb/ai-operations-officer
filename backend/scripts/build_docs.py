"""Render the company policy PDFs from Jinja + Markdown sources.

    facts.yaml ─┐
                ├─► Jinja (numbers filled in) ─► Markdown ─► HTML ─► PDF (fpdf2)
    *.md.j2 ────┘

Usage (from backend/):  uv run --group docs python -m scripts.build_docs
The generated PDFs are committed, so the runtime never needs this script.
"""

from pathlib import Path

import jinja2
import markdown
import yaml
from fpdf import FPDF
from fpdf.fonts import TextStyle

from app.config import get_settings
from app.domain.facts import get_facts

PINE = (30, 77, 59)
HARBOR = (27, 58, 92)
MUTED = (110, 117, 125)
RULE = (210, 214, 218)

# Core PDF fonts are Latin-1 only; normalise typographic characters just in case.
_LATIN1 = str.maketrans({"—": "-", "–": "-", "‘": "'", "’": "'",
                         "“": '"', "”": '"', "•": "-", "…": "...",
                         "≤": "<=", "≥": ">=", "×": "x"})  # fmt: skip


def usd(value: float) -> str:
    return f"${value:,.2f}"


def usd0(value: float) -> str:
    return f"${value:,.0f}"


class PolicyPDF(FPDF):
    def __init__(self, company: str, doc: dict):
        super().__init__(format="Letter")
        self.company, self.doc = company, doc
        self.set_margins(20, 22, 20)
        self.set_auto_page_break(auto=True, margin=20)
        self.set_title(doc["title"])
        self.set_author(company)
        self.set_subject(doc["summary"])

    def header(self) -> None:
        self.set_y(10)
        self.set_font("helvetica", "B", 8)
        self.set_text_color(*PINE)
        self.cell(0, 5, self.company.upper(), align="L")
        self.set_font("helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.set_x(self.l_margin)
        self.cell(0, 5, f"{self.doc['doc_id']}  |  {self.doc['title']}", align="R")
        self.set_draw_color(*RULE)
        self.line(self.l_margin, 16, self.w - self.r_margin, 16)
        self.set_y(22)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("helvetica", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, "Synthetic demo document - fictional company, not legal advice.", align="L")
        self.set_x(self.l_margin)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    def title_block(self) -> None:
        self.set_font("helvetica", "B", 22)
        self.set_text_color(*HARBOR)
        self.multi_cell(0, 10, self.doc["title"])
        self.ln(1)
        self.set_font("helvetica", "", 9)
        self.set_text_color(*MUTED)
        meta = (
            f"Document {self.doc['doc_id']}   |   Version {self.doc['version']}   |   "
            f"Effective {self.doc['effective']}   |   Owner: {self.doc['owner']}"
        )
        self.multi_cell(0, 5, meta)
        self.ln(2)
        self.set_draw_color(*PINE)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.l_margin + 30, self.get_y())
        self.set_line_width(0.2)
        self.ln(6)


def render_pdf(company: str, doc: dict, body_md: str, out_path: Path) -> int:
    html = markdown.markdown(body_md.translate(_LATIN1), extensions=["tables"])
    pdf = PolicyPDF(company, doc)
    pdf.add_page()
    pdf.title_block()
    pdf.set_text_color(33, 37, 41)
    pdf.set_font("helvetica", size=9)  # base size: applies to table cells
    pdf.write_html(
        html,
        font_family="helvetica",
        table_line_separators=True,
        li_prefix_color=PINE,
        tag_styles={
            "h2": TextStyle(font_family="helvetica", font_style="B", font_size_pt=13,
                            color=PINE, t_margin=5, b_margin=0),
            "h3": TextStyle(font_family="helvetica", font_style="B", font_size_pt=11,
                            color=HARBOR, t_margin=3, b_margin=0),
            "p": TextStyle(font_family="helvetica", font_size_pt=10, t_margin=1, b_margin=1.5),
            "li": TextStyle(font_family="helvetica", font_size_pt=10, l_margin=6),
        },
    )  # fmt: skip
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return pdf.page_no()


def main() -> None:
    settings = get_settings()
    facts = get_facts()
    src_dir = settings.data_dir / "docs_src"
    manifest = yaml.safe_load(settings.manifest_path.read_text(encoding="utf-8"))

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(src_dir),
        undefined=jinja2.StrictUndefined,  # a typo in a template fails loudly
        autoescape=False,
    )
    env.filters.update(usd=usd, usd0=usd0)

    for doc in manifest["documents"]:
        body = env.get_template(f"{doc['slug']}.md.j2").render(f=facts)
        out = settings.docs_dir / f"{doc['slug']}.pdf"
        pages = render_pdf(facts["company"]["name"], doc, body, out)
        print(f"  {doc['doc_id']}  {out.name:<34} {pages} pages")


if __name__ == "__main__":
    main()
