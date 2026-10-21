"""Draw original, editable SVG illustrations from the paper's reported data."""
from pathlib import Path
from html import escape
import json

ROOT = Path(__file__).resolve().parents[1]


def draw_overview():
    return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 510" role="img" aria-labelledby="title desc">
<title id="title">From public CTI knowledge to verifiable learning</title>
<desc id="desc">Public vulnerability descriptions, detection rules, and threat behaviors become canonical training targets. GRPO samples and verifies answers. For hard prompts, MinervaRL generates answer-conditioned teacher traces, verifies and filters them, and distills on the original prompts.</desc>
<defs>
 <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#d9ded8"/></pattern>
 <marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="none" stroke="#64796e" stroke-width="1.5"/></marker>
 <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#1c382b" flood-opacity=".06"/></filter>
</defs>
<rect width="1200" height="510" rx="24" fill="#f0f3ed"/>
<rect width="1200" height="510" rx="24" fill="url(#grid)"/>
<g font-family="Arial, sans-serif" fill="#223b32">
 <text x="38" y="43" font-size="13" font-weight="700" letter-spacing="2.4">THE MINERVA LEARNING LOOP</text>
 <text x="1160" y="43" text-anchor="end" font-size="13" fill="#63746b">PUBLIC KNOWLEDGE → VERIFIABLE SIGNALS</text>
 <g transform="translate(40 95)" filter="url(#shadow)">
  <rect width="245" height="285" rx="16" fill="#fffefa" stroke="#d9dfd4"/>
  <text x="22" y="33" font-size="13" fill="#63746b" letter-spacing="1.5">PUBLIC CTI SOURCES</text>
  <g transform="translate(20 54)">
   <rect width="205" height="58" rx="9" fill="#edf2f7"/>
   <path d="M16 16h19M16 24h25M16 32h17" stroke="#597a91" stroke-width="2"/>
   <text x="53" y="26" font-size="16" font-weight="700">Vulnerabilities</text>
   <text x="53" y="44" font-size="12" fill="#627683">CVE · CWE · CVSS</text>
  </g>
  <g transform="translate(20 124)">
   <rect width="205" height="58" rx="9" fill="#f7efe5"/>
   <path d="M18 16l-7 8 7 8M34 16l7 8-7 8M28 12l-7 25" fill="none" stroke="#ad7c45" stroke-width="1.8"/>
   <text x="53" y="26" font-size="16" font-weight="700">Detection rules</text>
   <text x="53" y="44" font-size="12" fill="#866e53">Sigma · Sentinel · Splunk</text>
  </g>
  <g transform="translate(20 194)">
   <rect width="205" height="58" rx="9" fill="#edeaf4"/>
   <path d="M17 15l18 9-18 11Z" fill="none" stroke="#7e6e9d" stroke-width="1.7"/>
   <circle cx="17" cy="15" r="4" fill="#7e6e9d"/><circle cx="35" cy="24" r="4" fill="#7e6e9d"/><circle cx="17" cy="35" r="4" fill="#7e6e9d"/>
   <text x="53" y="26" font-size="16" font-weight="700">Threat behavior</text>
   <text x="53" y="44" font-size="12" fill="#796c8e">ATT&amp;CK · CAPEC</text>
  </g>
 </g>
 <path d="M291 238H332" stroke="#64796e" stroke-width="2" marker-end="url(#arrow)"/>
 <g transform="translate(347 125)" filter="url(#shadow)">
  <rect width="245" height="225" rx="16" fill="#fffefa" stroke="#d9dfd4"/>
  <text x="22" y="36" font-size="25" font-family="Georgia,serif">Minerva-CTI</text>
  <text x="22" y="62" font-size="14" fill="#64746a">16 verifier-checkable tasks</text>
  <path d="M22 82H223" stroke="#e0e4da"/>
  <text x="22" y="111" font-size="15">Analyst-style prompt</text>
  <text x="22" y="144" font-size="15">Canonical target</text>
  <text x="22" y="177" font-size="15">Task-specific verifier</text>
  <circle cx="216" cy="106" r="9" fill="#dfebdc"/><path d="m212 106 3 3 5-6" fill="none" stroke="#3e7453" stroke-width="1.5"/>
  <circle cx="216" cy="139" r="9" fill="#dfebdc"/><path d="m212 139 3 3 5-6" fill="none" stroke="#3e7453" stroke-width="1.5"/>
  <circle cx="216" cy="172" r="9" fill="#dfebdc"/><path d="m212 172 3 3 5-6" fill="none" stroke="#3e7453" stroke-width="1.5"/>
 </g>
 <path d="M599 238H640" stroke="#64796e" stroke-width="2" marker-end="url(#arrow)"/>
 <g transform="translate(655 84)">
  <rect width="505" height="348" rx="20" fill="#e4ecdf" stroke="#bdcdb6"/>
  <text x="25" y="41" font-size="28" font-family="Georgia,serif">MinervaRL</text>
  <text x="480" y="38" text-anchor="end" font-size="12" fill="#557049">GRPO + AUXILIARY SELF-TRAINING</text>
  <rect x="24" y="66" width="457" height="72" rx="12" fill="#fffefa" stroke="#cbd8c6"/>
  <text x="44" y="96" font-size="18" font-weight="700">Sample → Verify → Update</text>
  <text x="44" y="120" font-size="14" fill="#657260">Standard reward-driven GRPO loop</text>
  <path d="M252 145V177" stroke="#64796e" stroke-width="1.8" marker-end="url(#arrow)"/>
  <rect x="276" y="149" width="182" height="27" rx="13" fill="#f8f6e7"/>
  <text x="367" y="167" text-anchor="middle" font-size="12" fill="#826d3d">No fully verified rollout?</text>
  <rect x="24" y="191" width="457" height="112" rx="12" fill="#2c5945"/>
  <text x="44" y="220" font-size="17" font-weight="700" fill="#ffffff">Teacher traces for hard prompts</text>
  <text x="44" y="246" font-size="14" fill="#d6e5d5">Condition on labels → verify and filter</text>
  <text x="44" y="276" font-size="14" fill="#eaf1e8">Distill on the original, answer-free prompt</text>
  <path d="M484 248H492V103H484" fill="none" stroke="#68825e" stroke-width="1.8" stroke-dasharray="5 5" marker-end="url(#arrow)"/>
  <text x="24" y="328" font-size="12" fill="#5d7055">Accepted traces create an additional supervised signal.</text>
 </g>
 <path d="M40 450H592" stroke="#d1d9cb"/>
 <text x="40" y="480" font-size="13" fill="#6c7865">An overview of the method · see the paper for the full algorithm.</text>
</g></svg>'''


def draw_results(results):
    colors={'Base':'#a9b2b1','GRPO':'#c28b58','MinervaRL':'#2b7055'}
    parts=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1120 570" role="img" aria-labelledby="t d"><title id="t">Mean scores across 12 CTI benchmarks</title><desc id="d">Base, GRPO, and MinervaRL scores for four backbones. All axes run from zero to 70. Exact values and additional baselines appear in the adjacent table.</desc><rect width="1120" height="570" rx="16" fill="#fbfcf9"/><g font-family="Arial,sans-serif" fill="#243b32">']
    parts.append('<text x="28" y="37" font-size="20" font-weight="700">Average across 12 CTI benchmarks</text><text x="28" y="63" font-size="14" fill="#667569">Single-sample greedy decoding · higher is better</text>')
    for i,model in enumerate(results['backbones']):
        x=28+(i%2)*550;y=100+(i//2)*230
        parts.append(f'<g transform="translate({x} {y})"><text x="0" y="23" font-size="20" font-weight="700">{escape(model)}</text>')
        for value in [0,20,40,60,70]:
            bx=100+value/70*350
            parts.append(f'<path d="M{bx:.1f} 40V177" stroke="#e5e9e1"/><text x="{bx:.1f}" y="198" text-anchor="middle" font-size="12" fill="#758074">{value}</text>')
        for j,method in enumerate(colors):
            score=next(r['average'] for r in results['rows'] if r['backbone']==model and r['method']==method)
            by=46+j*45;w=score/70*350
            parts.append(f'<text x="86" y="{by+19}" text-anchor="end" font-size="14">{method}</text><rect x="100" y="{by}" width="{w:.2f}" height="28" rx="4" fill="{colors[method]}"/><text x="{108+w:.2f}" y="{by+20}" font-size="15" font-weight="700">{score:.1f}</text>')
        parts.append('</g>')
    parts.append('</g></svg>')
    return ''.join(parts)


def main():
    assets=ROOT/'site/assets'
    results=json.loads((ROOT/'site/results.json').read_text(encoding='utf-8'))
    (assets/'minerva-overview.svg').write_text(draw_overview(),encoding='utf-8')
    (assets/'benchmark-comparison.svg').write_text(draw_results(results),encoding='utf-8')


if __name__=='__main__':main()
