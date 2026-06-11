import { h, type SatoriNode } from '../render.ts';
import { COLORS, CARD, logoMark, gradeColor } from './_shared.ts';

export function quizResultCard(data: {
  score: number;
  total: number;
  grade: string;
  message?: string;
}): SatoriNode {
  const pct = Math.round((data.score / data.total) * 100);
  const { text, bg } = gradeColor(data.grade);

  return h('div', {
    style: {
      ...CARD.outer,
      background: bg,
      flexDirection: 'column',
      justifyContent: 'space-between',
    },
  } as never,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
      logoMark(),
      h('div', {
        style: { fontSize: 22, color: COLORS.muted, letterSpacing: '0.05em', fontWeight: 700 },
      }, 'REKT-PROOF QUIZ'),
      h('div', {
        style: {
          fontSize: 80,
          fontWeight: 700,
          color: text,
          lineHeight: 1,
        },
      }, `${pct}%`),
      h('div', {
        style: { fontSize: 28, color: COLORS.muted },
      }, `${data.score} of ${data.total} correct`),
      data.message
        ? h('div', {
          style: { fontSize: 24, color: COLORS.ink, lineHeight: 1.4, maxWidth: 820 },
        }, data.message)
        : null,
    ),
    h('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        paddingTop: 20,
        borderTop: `2px solid ${text}33`,
      },
    },
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, 'defirisk.co/quiz/'),
      h('div', { style: { flex: 1 } }),
      h('div', { style: { fontSize: 18, fontWeight: 700, color: text } }, `Grade ${data.grade}`),
    ),
  );
}
