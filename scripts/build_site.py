"""Rebuild the complete static page through the vendored paperpage generator."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools/paperpage/src'))
from paperpage.config import build_editorial_context
from paperpage.models import PaperManifest, PaperAuthor, PaperSection, PaperAsset
from paperpage.render import build_project_draft
from draw_figures import main as draw_figures


def main():
    draw_figures()
    raw = yaml.safe_load((ROOT/'site/paper.yml').read_text(encoding='utf-8'))
    raw['paper_path'] = str(ROOT/'site')
    raw['source_dir'] = str(ROOT/'site')
    raw['author_entries'] = [PaperAuthor(**a) for a in raw['author_entries']]
    raw['sections'] = [PaperSection(**s) for s in raw['sections']]
    for field in ['figure_assets', 'table_assets']:
        raw[field] = [PaperAsset(**a) for a in raw[field]]
    manifest = PaperManifest(**raw)
    context = build_editorial_context(project_config_path=str(ROOT/'paperpage.yml'))
    results = json.loads((ROOT/'site/results.json').read_text(encoding='utf-8'))
    methods = ['Base','STaR-CTI','DART-CTI','GRPO','LUFFY-CTI','MinervaRL']
    results['methods'] = methods
    results['summary_rows'] = [
        {'backbone': model, 'scores': [next(r['average'] for r in results['rows'] if r['backbone']==model and r['method']==method) for method in methods]}
        for model in results['backbones']
    ]
    assert len(results['rows']) == 24
    assert sum(results['paired_grpo'][k] for k in ['positive','negative','overlap']) == 48
    context['resolved']['results'] = results
    artifact = build_project_draft(manifest, context, ROOT)
    (artifact.docs_dir/'.nojekyll').write_text('',encoding='utf-8')
    data_dir = artifact.docs_dir/'assets/data'
    data_dir.mkdir(parents=True,exist_ok=True)
    (data_dir/'results.json').write_bytes((ROOT/'site/results.json').read_bytes())
    bibtex = context['resolved']['citation']['bibtex'].strip()+'\n'
    (ROOT/'CITATION.bib').write_text(bibtex,encoding='utf-8')
    (data_dir/'citation.bib').write_text(bibtex,encoding='utf-8')
    print(f'Built {artifact.index_path}')


if __name__ == '__main__':
    main()
