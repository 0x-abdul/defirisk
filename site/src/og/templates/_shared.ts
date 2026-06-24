import { h, type SatoriNode } from '../render.ts';

// Colors mirror the D3 tokens from site/src/styles/tokens.css (light mode).
// OG cards are static PNGs and render once at build time, so a hardcoded
// light-mode palette is correct because they cannot toggle to dark via CSS vars.
export const COLORS = {
  bg: '#fafaf9',
  ink: '#0f1011',
  muted: '#686b71',
  border: '#e7e5e0',
  white: '#ffffff',
  gradeA: '#118a4d', gradeAbg: '#dff2e3',
  gradeB: '#3da55f', gradeBbg: '#e6f1da',
  gradeC: '#c4881b', gradeCbg: '#f8eccc',
  gradeD: '#cc6420', gradeDbg: '#f7dec5',
  gradeF: '#b62a1f', gradeFbg: '#f6d3cd',
  gradeN: '#a5a8af', gradeNbg: '#f5f4f1',
  critical: '#b62a1f', criticalBg: '#f6d3cd',
};

export const CARD = {
  outer: {
    display: 'flex',
    width: 1200,
    height: 630,
    padding: '60px 72px',
    fontFamily: 'Geist, Inter, sans-serif',
  },
};

export function gradeColor(letter: string): { text: string; bg: string } {
  switch (letter) {
    case 'A': return { text: COLORS.gradeA, bg: COLORS.gradeAbg };
    case 'B': return { text: COLORS.gradeB, bg: COLORS.gradeBbg };
    case 'C': return { text: COLORS.gradeC, bg: COLORS.gradeCbg };
    case 'D': return { text: COLORS.gradeD, bg: COLORS.gradeDbg };
    case 'F': return { text: COLORS.gradeF, bg: COLORS.gradeFbg };
    default:  return { text: COLORS.gradeN, bg: COLORS.gradeNbg };
  }
}

export function logoMark(): SatoriNode {
  // Aperture mark: circle with dot, approximated for Satori (no stroke-dasharray support)
  return h('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      marginBottom: 8,
    },
  },
    h('div', {
      style: {
        width: 28,
        height: 28,
        borderRadius: '50%',
        border: `3px solid ${COLORS.ink}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      },
    },
      h('div', {
        style: {
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: COLORS.ink,
        },
      }),
    ),
    h('div', {
      style: {
        fontSize: 17,
        fontWeight: 600,
        color: COLORS.ink,
        letterSpacing: '-0.02em',
      },
    }, 'DeFi Risk'),
  );
}

export function gradePill(letter: string, size: number = 80): SatoriNode {
  const { text, bg } = gradeColor(letter);
  return h('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: size,
      height: size,
      borderRadius: size / 4,
      background: bg,
      fontSize: size * 0.45,
      fontWeight: 700,
      color: text,
      flexShrink: 0,
    },
  }, letter === 'ineligible' ? 'N/A' : letter);
}

