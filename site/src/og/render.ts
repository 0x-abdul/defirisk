/**
 * OG image renderer wrapping satori + @resvg/resvg-js.
 * Used by site/scripts/build-og-images.mjs at build time only.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// Font is loaded once and reused for all renders
let _fontData: ArrayBuffer | null = null;
let _fontBoldData: ArrayBuffer | null = null;

function getFontData(): ArrayBuffer {
  if (_fontData) return _fontData;
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const fontPath = path.resolve(
    __dirname,
    '../../node_modules/@fontsource/inter/files/inter-latin-400-normal.woff',
  );
  _fontData = readFileSync(fontPath).buffer as ArrayBuffer;
  return _fontData;
}

function getFontBoldData(): ArrayBuffer {
  if (_fontBoldData) return _fontBoldData;
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const fontPath = path.resolve(
    __dirname,
    '../../node_modules/@fontsource/inter/files/inter-latin-700-normal.woff',
  );
  _fontBoldData = readFileSync(fontPath).buffer as ArrayBuffer;
  return _fontBoldData;
}

export type SatoriNode = {
  type: string;
  props: {
    style?: Record<string, unknown>;
    children?: SatoriNode | string | (SatoriNode | string)[] | null;
    [key: string]: unknown;
  };
};

/** Convenience JSX-like factory for satori element trees. */
export function h(
  type: string,
  props: Record<string, unknown> & { style?: Record<string, unknown> },
  ...children: (SatoriNode | string | null | undefined)[]
): SatoriNode {
  const flatChildren = children.flat().filter((c) => c != null);
  return {
    type,
    props: {
      ...props,
      children: flatChildren.length === 1 ? flatChildren[0] : flatChildren.length === 0 ? undefined : flatChildren,
    },
  };
}

export async function renderOgCard(
  element: SatoriNode,
  options: { width?: number; height?: number } = {},
): Promise<Buffer> {
  const { default: satori } = await import('satori');
  const { Resvg } = await import('@resvg/resvg-js');

  const { width = 1200, height = 630 } = options;

  const svg = await satori(element as never, {
    width,
    height,
    fonts: [
      { name: 'Inter', data: getFontData(), weight: 400 },
      { name: 'Inter', data: getFontBoldData(), weight: 700 },
    ],
  });

  const resvg = new Resvg(svg, { fitTo: { mode: 'width', value: width } });
  return Buffer.from(resvg.render().asPng());
}
