#!/usr/bin/env python3
"""Render audited v3 evidence in one paper column; no study execution or fitting.

All numerical inputs must come from extract.py. No v2 defaults or synthetic mode.
Scientific rendering is withheld until all three seals and final completion.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

from extract import CAMPAIGNS, STRATA, EvidenceError, output_directory

HERE = Path(__file__).resolve().parent
WIDTH = 3.3
INK, BLUE, LIGHT, GRID, GRAY = '#303437', '#456C83', '#B9CDD8', '#DDE1E4', '#7E858A'
ROLES = ['lead', 'reviewer', 'implementation', 'investigation', 'measurement']
ENC = [(INK, 'o', ':'), (BLUE, 's', '--'), (INK, '^', '-.')]
CAPTIONS = {
    'workflow': 'The research and review loop advances only verified sources; assessment follows endpoint sealing.',
    'development': 'Direct original-seed comparisons at checkpoint completion; the hollow diamond is unmeasured identity. Stems end at nominal one-sided 90% lower bounds. Lines connect adaptive observations.',
    'endpoints': 'Fresh endpoint comparisons in both final strata. Estimates and nominal one-sided 90% lower bounds retain all three planned campaigns. Hollow diamonds mark algebraic identity; × marks unavailable values.',
    'families-transfer': 'Transfer-stratum family speedups relative to the original seed. Outlined values below 1 are regressions; × retains missing evidence. Shading uses a shared log scale across both strata.',
    'families-shift': 'Shift-stratum family speedups relative to the original seed. Outlined values below 1 are regressions; × retains missing evidence. Shading uses a shared log scale across both strata.',
}


def validate_bundle(bundle):
    if bundle.get('synthetic') is not False or bundle.get('study_version') != 'unattended-optimization-v3':
        raise EvidenceError('Only explicitly real, version-bound v3 evidence may be rendered')
    if not bundle.get('cohort_terminal') or not bundle.get('final_evidence_released') or bundle.get('final_assessment_status') != 'complete':
        raise EvidenceError('All original campaign seals and completed final assessment are required')
    tables = bundle.get('tables') or {}
    if {r['campaign'] for r in tables.get('campaigns', [])} != set(CAMPAIGNS):
        raise EvidenceError('Planned campaign denominator is missing')
    expected = {(c, s) for c in CAMPAIGNS for s in STRATA}
    rows = tables.get('heldout', [])
    if len(rows) != 6 or {(r['campaign'], r['stratum']) for r in rows} != expected:
        raise EvidenceError('All six planned endpoint cells must be retained')
    if not bundle.get('sources'):
        raise EvidenceError('Evidence manifest is missing')
    for row in tables.get('trajectories', []):
        if row.get('ratio') is not None and row.get('status') != 'algebraic_identity' and not row.get('measured'):
            raise EvidenceError('Unmeasured trajectory contains a scored ratio')


def configure():
    # Lazy import: refusal tests do not initialize or render a plotting backend.
    import os
    os.environ.setdefault('MPLCONFIGDIR', str(HERE / '.mpl-cache'))
    os.environ.setdefault('XDG_CACHE_HOME', str(HERE / '.cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        'font.family': 'DejaVu Sans', 'font.size': 8.5, 'axes.labelsize': 8.5,
        'xtick.labelsize': 8, 'ytick.labelsize': 8, 'legend.fontsize': 8,
        'text.color': INK, 'axes.labelcolor': INK, 'axes.edgecolor': GRAY,
        'xtick.color': INK, 'ytick.color': INK, 'axes.spines.top': False,
        'axes.spines.right': False, 'axes.linewidth': .55, 'xtick.major.width': .55,
        'ytick.major.width': .55, 'xtick.major.size': 3, 'ytick.major.size': 3,
        'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'none',
        'svg.hashsalt': 'unattended-optimization-v3-real-single-column',
        'savefig.facecolor': 'white',
    })
    return matplotlib, plt


class Exporter:
    def __init__(self, out, mpl, plt):
        self.out, self.mpl, self.plt, self.products = out, mpl, plt, []

    def save(self, fig, name, caption=None):
        fig.canvas.draw()
        # Locators retain ticks beyond the view limits. Axis.draw omits them,
        # even though the child Text's own visibility flag remains True.
        # Exclude those non-rendered labels from canvas clipping checks.
        omitted_tick_labels = set()
        for ax in fig.axes:
            for axis in (ax.xaxis, ax.yaxis):
                low, high = sorted(axis.get_view_interval())
                for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                    if not ax.axison or not axis.get_visible() or not low <= tick.get_loc() <= high:
                        omitted_tick_labels.update((tick.label1, tick.label2))
        texts = [x for x in fig.findobj(self.mpl.text.Text)
                 if x.get_visible() and x.get_text().strip() and x not in omitted_tick_labels]
        minimum = min(x.get_fontsize() for x in texts)
        if not 8 <= minimum or abs(fig.get_figwidth() - WIDTH) > 1e-6:
            raise EvidenceError(f'{name}: paper-column width or minimum type size violated')
        renderer = fig.canvas.get_renderer()
        for text in texts:
            box = text.get_window_extent(renderer)
            if box.x0 < -.2 or box.y0 < -.2 or box.x1 > fig.bbox.x1 + .2 or box.y1 > fig.bbox.y1 + .2:
                raise EvidenceError(f'{name}: text outside canvas: {text.get_text()}')
        for ext in ('svg', 'pdf', 'png'):
            path = self.out / f'v3-{name}.{ext}'
            meta = ({'Date': None, 'Description': 'Audited real v3 evidence; one paper column'} if ext == 'svg' else
                    {'CreationDate': None, 'ModDate': None, 'Subject': 'Audited real v3 evidence; one paper column'} if ext == 'pdf' else {})
            fig.savefig(path, dpi=220, bbox_inches=None, metadata=meta)
            self.products.append({'file': path.name, 'width_in': WIDTH, 'height_in': fig.get_figheight(),
                'min_font_pt': minimum, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'caption': caption or CAPTIONS.get(name, '')})
        self.plt.close(fig)


def clean(ax, axis='y'):
    ax.set_axisbelow(True)
    ax.grid(axis=axis, color=GRID, lw=.45)


def roles_for(tables):
    names = {r['role'] for r in tables['threads']} | {r['role'] for r in tables['cost_bounds']}
    return ROLES + sorted(names - set(ROLES))


def campaign_label(tables, campaign):
    row = next(r for r in tables['campaigns'] if r['campaign'] == campaign)
    return 'C' + campaign.rsplit('-', 1)[-1] + ('†' if row['status'] != 'complete' else '')


def workflow(ex):
    from matplotlib.patches import FancyArrowPatch, Rectangle
    fig = ex.plt.figure(figsize=(WIDTH, 1.8))
    ax = fig.add_axes([.02, .035, .96, .93]); ax.set(xlim=(0, 3.3), ylim=(0, 1.8)); ax.axis('off')
    for y, label in [(1.43, 'Freeze protocol'), (.99, 'Lead  →  Workers  →  Reviewer'),
                     (.55, 'Controller promotion gates'), (.11, 'Seal endpoints  →  Final assessment')]:
        ax.add_patch(Rectangle((.30, y), 2.93, .29, facecolor='white', edgecolor=GRAY, lw=.65))
        ax.text(1.765, y + .145, label, ha='center', va='center', fontsize=8.5, color=BLUE if y == .55 else INK)
    for top, bottom in [(1.43, 1.28), (.99, .84), (.55, .40)]:
        ax.add_patch(FancyArrowPatch((1.765, top - .018), (1.765, bottom + .018), arrowstyle='-|>', mutation_scale=7, lw=.65, color=INK))
    ax.plot([.30, .09, .09], [.695, .695, 1.135], color=BLUE, lw=.7)
    ax.add_patch(FancyArrowPatch((.09, 1.135), (.30, 1.135), arrowstyle='-|>', mutation_scale=7, lw=.7, color=BLUE))
    ex.save(fig, 'workflow')


def development(tables, ex):
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator
    import numpy as np
    missing = any(r['ratio'] is None for r in tables['trajectories'])
    fig = ex.plt.figure(figsize=(WIDTH, 2.6 if missing else 2.2))
    ax = fig.add_axes([.18, .34 if missing else .23, .78, .60 if missing else .71])
    values, times = [1.0], [0.0]
    for campaign, (color, marker, ls) in zip(CAMPAIGNS, ENC):
        rows = sorted([r for r in tables['trajectories'] if r['campaign'] == campaign],
            key=lambda r: r.get('elapsed_seconds') if r.get('elapsed_seconds') is not None else r['promotion_elapsed_seconds'])
        x = [(r.get('elapsed_seconds') if r.get('elapsed_seconds') is not None else r['promotion_elapsed_seconds']) / 60 for r in rows]
        y = [r['ratio'] if r['ratio'] is not None else np.nan for r in rows]
        times.extend(x); values.extend(v for v in y if np.isfinite(v))
        ax.plot(x, y, lw=.8, ls=ls, color=color)
        for at, row in zip(x, rows):
            if row['ratio'] is None:
                ax.plot(at, -.24, 'x', color=color, ms=4, mew=.75, transform=ax.get_xaxis_transform(), clip_on=False)
            elif row.get('measured'):
                low, point = row['one_sided90_lower'], row['ratio']; values.append(low)
                ax.plot([at, at], [low, point], color=color, lw=.8); ax.plot(at, low, '_', color=color, ms=5)
                ax.plot(at, point, marker=marker, ms=4.1, color=color, mec='white', mew=.45)
    ax.plot(0, 1, 'D', ms=4, mfc='white', mec=INK, mew=.7, clip_on=False)
    ax.axhline(1, color=GRAY, lw=.6, ls=(0, (3, 3)))
    duration = max(times) or 1
    extent = max(values) - min(values) or .1
    ax.set(xlim=(-.025 * duration, 1.04 * duration), ylim=(max(0, min(values) - .10 * extent), max(values) + .13 * extent),
           xlabel='Elapsed time (min)', ylabel='Seed / checkpoint time (×)')
    ax.xaxis.set_major_locator(MaxNLocator(5)); ax.yaxis.set_major_locator(MaxNLocator(5)); clean(ax)
    if missing:
        ax.xaxis.set_label_coords(.5, -.39)
    handles = [Line2D([], [], color=c, marker=m, ls=l, lw=.8, ms=4, label=campaign_label(tables, campaign))
               for campaign, (c, m, l) in zip(CAMPAIGNS, ENC)]
    ax.legend(handles=handles, loc='upper left', frameon=False, ncol=3, handlelength=1.4, columnspacing=.8, handletextpad=.45, borderaxespad=.1)
    ex.save(fig, 'development', CAPTIONS['development'] + (' × marks unavailable observations.' if missing else ''))


def endpoints(tables, ex):
    from matplotlib.ticker import MaxNLocator
    fig = ex.plt.figure(figsize=(WIDTH, 2.15)); ax = fig.add_axes([.12, .27, .36, .61]); cells = fig.add_axes([.52, .27, .47, .61])
    observed = [r[k] for r in tables['heldout'] for k in ('ratio', 'one_sided90_lower') if r.get(k) is not None]
    hi, lo = max(observed + [1]), min(observed + [1]); extent = hi - lo or .2
    for i, campaign in enumerate(CAMPAIGNS):
        for stratum, delta, col, color, marker in [('transfer', .15, .24, BLUE, 'o'), ('shift', -.15, .76, INK, 's')]:
            row = next(r for r in tables['heldout'] if r['campaign'] == campaign and r['stratum'] == stratum)
            value, lower = row.get('ratio'), row.get('one_sided90_lower'); y = 2 - i + delta
            label = '×'
            if value is not None:
                if row.get('measured'):
                    ax.plot([lower, value], [y, y], color=color, lw=.8); ax.plot(lower, y, '|', color=color, ms=5)
                    ax.plot(value, y, marker=marker, ms=4.2, mfc=color if stratum == 'transfer' else 'white', mec=color, mew=.8)
                    label = f'{value:.3g}\n[{lower:.3g}]'
                else:
                    ax.plot(value, y, 'D', ms=4, mfc='white', mec=color, mew=.7); label = f'{value:.3g} ◇'
            cells.text(col, 2 - i, label, va='center', ha='center', fontsize=8.3, color=color, linespacing=1.35)
    ax.axvline(1, color=GRAY, ls=(0, (3, 3)), lw=.6)
    ax.set(xlim=(max(0, lo - .10 * extent), hi + .12 * extent), ylim=(-.5, 2.55),
           yticks=[2, 1, 0], yticklabels=[campaign_label(tables, c) for c in CAMPAIGNS], xlabel='Speedup (×)')
    ax.xaxis.set_major_locator(MaxNLocator(4)); ax.tick_params(axis='y', length=0); ax.spines['left'].set_visible(False); clean(ax, 'x')
    cells.set(xlim=(0, 1), ylim=ax.get_ylim()); cells.axis('off')
    for at, label, color in [(.24, 'Transfer', BLUE), (.76, 'Shift', INK)]:
        cells.text(at, 2.74, label, ha='center', va='bottom', fontsize=8, color=color, clip_on=False)
    cells.plot([.02, .99], [2.42, 2.42], color=GRID, lw=.6)
    cells.text(.5, -1.06, 'Estimate [L90]', ha='center', va='top', fontsize=8, clip_on=False)
    ex.save(fig, 'endpoints')


def role_panels(tables, ex):
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import MaxNLocator
    roles = roles_for(tables)
    totals = [sum(r['inputTokens'] + r['outputTokens'] for r in tables['threads'] if r['campaign'] == c and r['role'] == role and r['usage_present']) / 1e6 for c in CAMPAIGNS for role in roles]
    xmax = max(totals + [.001]) * 1.10
    costs = [r['upper_usd'] for r in tables['cost_bounds'] if r.get('upper_usd') is not None]
    cmax = max(costs + [.01]) * 1.12
    for campaign in CAMPAIGNS:
        index = campaign.rsplit('-', 1)[-1]; label = campaign_label(tables, campaign)
        usage_available = next(r for r in tables['campaigns'] if r['campaign'] == campaign).get('terminal_usage_available', False)
        fig = ex.plt.figure(figsize=(WIDTH, 2.1 + .20 * max(0, len(roles) - 5))); ax = fig.add_axes([.31, .32, .65, .57])
        for j, role in enumerate(roles):
            rows = [r for r in tables['threads'] if r['campaign'] == campaign and r['role'] == role]
            known = [r for r in rows if r['usage_present']]
            if known:
                incoming, cached, outgoing = (sum(r[k] for r in known) / 1e6 for k in ('inputTokens', 'cachedInputTokens', 'outputTokens'))
                ax.barh(j, cached, height=.52, color=LIGHT, lw=0); ax.barh(j, incoming - cached, left=cached, height=.52, color=BLUE, lw=0)
                ax.barh(j, outgoing, left=incoming, height=.52, color=INK, lw=0)
                if len(known) != len(rows) or any(not r['observed_complete'] for r in rows):
                    ax.text(incoming + outgoing, j, ' *', ha='left', va='center', fontsize=8)
            else:
                ax.text(0, j, '×' if rows or not usage_available else '–', va='center', fontsize=8)
        ax.set(yticks=range(len(roles)), yticklabels=[r.capitalize() for r in roles], xlim=(0, xmax), ylim=(len(roles) - .35, -.6), xlabel='Observed tokens (millions)')
        ax.tick_params(axis='y', length=0); ax.spines['left'].set_visible(False); ax.xaxis.set_major_locator(MaxNLocator(4)); clean(ax, 'x')
        fig.legend([Rectangle((0, 0), 1, 1, color=c) for c in (LIGHT, BLUE, INK)], ['Cached input', 'Other input', 'Output'], frameon=False, ncol=3, loc='lower center', bbox_to_anchor=(.50, .00), handlelength=1, columnspacing=.7, handletextpad=.4)
        ex.save(fig, f'role-tokens-c{index}', f'{label} observed tokens by role. Cached input is a subset of input; reasoning is included in output. * marks incomplete observed accounting, × unknown usage, and – no registered threads.')
        fig = ex.plt.figure(figsize=(WIDTH, 1.95 + .20 * max(0, len(roles) - 5))); ax = fig.add_axes([.31, .27, .65, .64])
        for j, role in enumerate(roles):
            row = next((r for r in tables['cost_bounds'] if r['campaign'] == campaign and r['role'] == role), None)
            if row and row.get('lower_usd') is not None:
                low, high = row['lower_usd'], row['upper_usd']
                ax.plot([low, high], [j, j], color=BLUE, lw=2); ax.plot([low, high], [j, j], '|', color=BLUE, ms=6)
                if row.get('missing_usage_threads') or row.get('interrupted_usage_tail_unknown'):
                    ax.text(high, j, ' *', va='center', fontsize=8)
            else:
                ax.text(0, j, '×' if row or not usage_available else '–', va='center', fontsize=8)
        ax.set(yticks=range(len(roles)), yticklabels=[r.capitalize() for r in roles], xlim=(0, cmax), ylim=(len(roles) - .35, -.6), xlabel='Observed API-equivalent cost (USD)')
        ax.tick_params(axis='y', length=0); ax.spines['left'].set_visible(False); ax.xaxis.set_major_locator(MaxNLocator(4)); clean(ax, 'x')
        ex.save(fig, f'role-cost-c{index}', f'{label} hypothetical Standard API-equivalent intervals for observed token subtotals. Intervals reflect price/cache-write uncertainty, not sampling error or a complete bill. * flags known usage gaps; unreported work has unknown cost.')


def family_panels(tables, ex):
    import math
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    from matplotlib.patches import Rectangle
    rows = [r for r in tables['families'] if r['context'] == 'heldout_endpoint']
    def short(name):
        # The frozen fixture names retain their historical v2 prefix even
        # though these are freshly measured v3 outcomes.
        for stratum in STRATA:
            for prefix in (f'v2-{stratum}-', f'{stratum}-'):
                if name.startswith(prefix):
                    return name[len(prefix):]
        return name
    names = sorted({short(r['family']) for r in rows})
    if not names:
        return
    all_log = [math.log2(r['ratio']) for r in rows]
    span = max(1, math.ceil(max(abs(x) for x in all_log)))
    cmap = LinearSegmentedColormap.from_list('restrained', ['#80858A', '#F7F7F5', BLUE]); cmap.set_bad('#E8E9E8')
    for stratum in STRATA:
        fig = ex.plt.figure(figsize=(WIDTH, 2.55)); ax = fig.add_axes([.37, .33, .59, .60])
        matrix = np.full((len(names), 3), np.nan)
        for j, family in enumerate(names):
            for k, campaign in enumerate(CAMPAIGNS):
                item = next((r for r in rows if r['stratum'] == stratum and r['campaign'] == campaign and short(r['family']) == family), None)
                if item: matrix[j, k] = item['ratio']
        ax.imshow(np.log2(matrix), cmap=cmap, norm=TwoSlopeNorm(vmin=-span, vcenter=0, vmax=span), aspect='auto')
        for y in range(len(names)):
            for x in range(3):
                value = matrix[y, x]
                if np.isfinite(value) and value < 1:
                    ax.add_patch(Rectangle((x - .49, y - .49), .98, .98,
                        facecolor='none', edgecolor=INK, lw=.8))
                ax.text(x, y, f'{value:.2f}' if np.isfinite(value) else '×', ha='center', va='center', fontsize=8.3,
                        color='white' if np.isfinite(value) and abs(math.log2(value)) > span * .65 else INK)
        ax.set(xticks=range(3), xticklabels=[campaign_label(tables, c) for c in CAMPAIGNS], yticks=range(len(names)), yticklabels=[s.replace('-', ' ').replace('_', ' ').capitalize() for s in names])
        ax.tick_params(length=0, pad=4); [s.set_visible(False) for s in ax.spines.values()]
        cax = fig.add_axes([.43, .15, .48, .033]); scalar = ex.mpl.cm.ScalarMappable(norm=TwoSlopeNorm(vmin=-span, vcenter=0, vmax=span), cmap=cmap)
        cb = fig.colorbar(scalar, cax=cax, orientation='horizontal', ticks=[-span, 0, span]); cb.ax.set_xticklabels([f'{2**(-span):.3g}', '1', f'{2**span:g}']); cb.outline.set_linewidth(.4)
        cb.set_label('Seed / endpoint time (×)', fontsize=8, labelpad=3)
        ex.save(fig, f'families-{stratum}')
        # Distribution supplement preserves all paired blocks without inventing family confidence intervals.
        for campaign in CAMPAIGNS:
            fig = ex.plt.figure(figsize=(WIDTH, 2.55)); ax = fig.add_axes([.37, .24, .59, .69])
            points = [r for r in tables['raw_pairs'] if r['context'] == 'heldout_endpoint' and r['campaign'] == campaign and r['stratum'] == stratum]
            for j, name in enumerate(names):
                selected = [r for r in points if short(r['family']) == name]
                if selected:
                    # Deterministic block-index offsets are visual separation, not an extra random draw.
                    ax.scatter([r['paired_ratio'] for r in selected], [j + ((r['block'] % 7) - 3) * .04 for r in selected], s=7, color=LIGHT, edgecolors='none', zorder=2)
                    center = next(r['ratio'] for r in rows if r['campaign'] == campaign and r['stratum'] == stratum and short(r['family']) == name)
                    ax.plot(center, j, 'o', color=BLUE, ms=3.5)
                else:
                    ax.text(1, j, '×', va='center', ha='center', fontsize=8)
            ax.set_xscale('log', base=2); ax.axvline(1, color=GRAY, lw=.6, ls=(0, (3, 3)))
            ax.set(yticks=range(len(names)), yticklabels=[s.replace('-', ' ').replace('_', ' ').capitalize() for s in names], ylim=(len(names) - .35, -.6), xlabel='Paired seed / endpoint time (×)')
            ax.tick_params(axis='y', length=0); ax.spines['left'].set_visible(False); clean(ax, 'x')
            from matplotlib.ticker import LogLocator, FuncFormatter
            ax.xaxis.set_major_locator(LogLocator(base=2, numticks=4)); ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))
            name = f'family-pairs-{stratum}-c{campaign.rsplit("-", 1)[-1]}'
            ex.save(fig, name, f'{campaign_label(tables, campaign)}, {stratum}: all temporal paired-block ratios and the frozen median-log family estimate. Block dispersion is descriptive and is not a confidence interval; × retains missing comparisons.')


def render(bundle, out):
    validate_bundle(bundle)
    mpl, plt = configure()
    ex = Exporter(out, mpl, plt)
    tables = bundle['tables']
    workflow(ex); development(tables, ex); endpoints(tables, ex); role_panels(tables, ex); family_panels(tables, ex)
    return {'study_version': bundle['study_version'], 'synthetic': False, 'placement_width_in': WIDTH,
            'matplotlib_version': mpl.__version__, 'products': ex.products,
            'placement': 'Place each figure at exactly 3.3 inches in one column; never span both columns or shrink type.',
            'visual_qa': 'Automated width/font/clipping checks only. Inspect rendered figures and compiled manuscript pages before publication.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path); parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(); raw = args.data.read_bytes(); bundle = json.loads(raw)
    validate_bundle(bundle)
    out = output_directory(args.out); manifest = render(bundle, out)
    manifest.update(data_file=args.data.name, data_sha256=hashlib.sha256(raw).hexdigest(), script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out / 'render-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    unique = {r['file'].rsplit('.', 1)[0]: r['caption'] for r in manifest['products']}
    (out / 'captions.txt').write_text('\n\n'.join(f'{name}: {caption}' for name, caption in unique.items()) + '\n')
    print(f'Rendered {len(unique)} single-column figures in {out}')


if __name__ == '__main__':
    try:
        main()
    except (EvidenceError, KeyError, ValueError, OSError) as exc:
        raise SystemExit(f'Figure rendering refused: {exc}')
