import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const srcRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function readSource(...parts: string[]): string {
  return readFileSync(path.join(srcRoot, ...parts), 'utf8');
}

describe('public copy review', () => {
  it('uses v1.7 critical-red rules in methodology and factor detail templates', () => {
    const sources = [
      readSource('pages', 'methodology.astro'),
      readSource('pages', 'factors', '[id].astro'),
      readSource('pages', 'protocols', '[slug]', 'factors', '[factor].astro'),
      readSource(
        'pages',
        'protocols',
        '[slug]',
        'surfaces',
        '[surface]',
        'factors',
        '[factor].astro',
      ),
      readSource('components', 'MethodologyTable.astro'),
    ];

    for (const source of sources) {
      expect(source).not.toContain('D / F (single-factor)');
    }

    const methodology = sources[0];
    expect(methodology).toContain('blocks an A and adds 5 points');
    expect(methodology).toContain('Two or more critical reds force D or worse');
    expect(methodology).toContain('three or more force F');
    expect(methodology).toContain('core-five category caps can lower the final grade further');
  });

  it('removes the unresolved attribution placeholder and applies proofreading corrections', () => {
    const about = readSource('pages', 'about.astro');
    const methodology = readSource('pages', 'methodology.astro');
    const changelog = readSource('pages', 'methodology', 'changelog.astro');

    expect(about).not.toContain('vN.N');
    expect(about).toContain('defirisk.co, rubric {RUBRIC_VERSION}');
    expect(methodology).toContain('<code>n/a (under embargo)</code>, and');
    expect(changelog).toContain('A minor-version bump');
    expect(changelog).toContain('v1.5.0');
    expect(changelog).toContain('v1.6.0');
    expect(changelog).toContain('CC BY 4.0');
  });
});
