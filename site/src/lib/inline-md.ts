/**
 * Render the small subset of Markdown used in curated factor and evidence prose:
 * `**bold**` spans and single newlines (`\n` → `<br>`).
 *
 * Curated fields such as `scoring_methodology` and `evidence_summary` are authored
 * with `**Label**` section headers and inline `**Protocol Name**` emphasis. They were
 * previously rendered as raw text, so the asterisks leaked into the page. The site's
 * existing CSS already styles `.body p strong`, so the intended output is `<strong>`.
 *
 * Input is trusted (our own DB-generated content) but we HTML-escape first so stray
 * `<`, `>`, or `&` in prose can never inject markup when used with `set:html`.
 */
export function inlineMarkdown(input: string | null | undefined): string {
  if (!input) return '';
  const escaped = input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  return escaped
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}
